from datetime import timedelta
from uuid import UUID,uuid4
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from production_besten.api.app import create_app
from tests.integration.test_product_editor import editor,save,action
from tests.integration.test_project_intake import intake,mutate
from tests.integration.test_production_release import command,readiness
from tests.integration.scheduling_helpers import HORIZON_START


@pytest.fixture
def initial(engine,editor):
    case,api,path,lot=editor
    assert save(api,path,[lot]).status_code==200
    assert action(api,path,'freeze').status_code==200
    assert command(api,path,'release').status_code==200
    with engine.begin() as conn:
        # Retain fixture history; the plant has no published CURRENT to compare against.
        conn.execute(text("UPDATE planning.plan_versions SET status='superseded',valid_during=tstzrange(lower(valid_during),now(),'[)') WHERE id=:id"),{'id':case.plan_version_id})
        conn.execute(text('UPDATE core.plants SET current_plan_version_id=NULL WHERE id=:id'),{'id':case.plant_id})
    prepared=readiness(api,path)
    body={'expected_row_version':prepared['row_version'],'evaluation_token':prepared['evaluation_token'],'reason':'First simulation review','horizon_start':HORIZON_START.isoformat(),'horizon_end':(HORIZON_START+timedelta(days=7)).isoformat()}
    return case,api,path,body


def gantt(api,scenario=None):
    params={'from':HORIZON_START.isoformat(),'to':(HORIZON_START+timedelta(days=7)).isoformat(),'group_by':'person'}
    if scenario:params['scenario_id']=str(scenario)
    return api.get('/planning/current/gantt',params=params)


def current(engine,case):
    with engine.connect() as conn:return conn.scalar(text('SELECT current_plan_version_id FROM core.plants WHERE id=:id'),{'id':case.plant_id})


def test_first_simulation_review_then_explicit_accept(engine,initial):
    case,api,path,body=initial
    key=uuid4()
    response=command(api,path,'simulations',body,key)
    assert response.status_code==200,response.text
    scenario=response.json()['scenario_id']
    assert response.json()['complete']
    replay=command(api,path,'simulations',body,key)
    assert replay.status_code==200 and replay.json()['scenario_id']==scenario
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM audit.audit_entries WHERE organization_id=:org AND action_code='PROJECT_PRODUCTION_SIMULATED' AND request_id=:key"),{'org':case.organization_id,'key':key})==1
    assert current(engine,case) is None
    options=gantt(api)
    assert options.status_code==200 and options.json()['plan_version_id'] is None
    assert scenario in {s['id'] for s in options.json()['available_scenarios']}
    visible=gantt(api,scenario)
    assert visible.status_code==200,visible.text
    data=visible.json()
    assert data['plan_version_id'] is None and data['scenario']['id']==scenario
    assert data['scenario']['scenario_kind']=='initial' and data['scenario']['complete'] and not data['scenario']['stale']
    assert len(data['operations'])==1
    op=data['operations'][0]
    assert op['planned_start'] and op['planned_finish'] and op['people'] and op['resources']
    assert op['duration_minutes']==30
    assert current(engine,case) is None
    accept_key=uuid4()
    accept_body={'expected_promotion_lock_version':data['scenario']['promotion_lock_version'],'reason':'Explicit human acceptance in test'}
    accepted=mutate(api,'POST',f'/scenarios/{scenario}/accept',accept_body,accept_key)
    assert accepted.status_code==201,accepted.text
    assert accepted.json()['previous_plan_version_id'] is None
    assert current(engine,case)==UUID(accepted.json()['plan_version_id'])
    retry=mutate(api,'POST',f'/scenarios/{scenario}/accept',accept_body,accept_key)
    assert retry.status_code==200 and retry.json()['idempotent_replay']
    assert gantt(api).json()['plan_version_id']==accepted.json()['plan_version_id']


def test_incomplete_initial_solution_remains_visible_and_cannot_be_accepted(engine,initial):
    case,api,path,body=initial
    with engine.begin() as conn:
        conn.execute(text("UPDATE capacity.employees SET status='inactive' WHERE organization_id=:org"),{'org':case.organization_id})
    response=command(api,path,'simulations',body)
    assert response.status_code==200,response.text
    scenario=response.json()['scenario_id']
    assert not response.json()['complete']
    data=gantt(api,scenario).json()
    assert not data['scenario']['complete'] and data['operations'][0]['blocker_code']
    assert data['operations'][0]['planned_start'] is None
    rejected=mutate(api,'POST',f'/scenarios/{scenario}/accept',{'expected_promotion_lock_version':data['scenario']['promotion_lock_version']})
    assert rejected.status_code==409,rejected.text
    assert current(engine,case) is None


def test_initial_scenario_isolation_and_atomic_accept_rollback(engine,initial):
    case,api,path,body=initial
    scenario=command(api,path,'simulations',body).json()['scenario_id']
    other=TestClient(create_app(engine=engine,enable_dev_context=True));other.headers.update(api.headers)
    other.headers['X-Dev-Organization-Id']=str(case.other_organization_id)
    assert gantt(other,scenario).status_code==404
    broken=TestClient(create_app(engine=engine,enable_dev_context=True,failpoints={'scheduling':'after_current_pointer'}),raise_server_exceptions=False)
    broken.headers.update(api.headers)
    data=gantt(api,scenario).json()
    accepted=mutate(broken,'POST',f'/scenarios/{scenario}/accept',{'expected_promotion_lock_version':data['scenario']['promotion_lock_version']})
    assert accepted.status_code==500,accepted.text
    assert current(engine,case) is None
    assert gantt(api,scenario).json()['scenario']['status']=='ready'
