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
from production_besten.application.replanning_services import AcceptReplanService
from production_besten.domain.errors import ScenarioExpired
from production_besten.domain.replanning import AcceptReplan
from production_besten.persistence.scheduling_uow import PostgresSchedulingUnitOfWorkFactory

pytestmark = pytest.mark.usefixtures("fixed_acceptance_clock")


def promotion_snapshot(engine, case, scenario):
    with engine.connect() as conn:
        return tuple(conn.execute(text(query), {'org':case.organization_id,'plant':case.plant_id,'scenario':scenario}).all() for query in [
            'SELECT current_plan_version_id,promotion_lock_version FROM core.plants WHERE id=:plant',
            'SELECT id,status,valid_during FROM planning.plan_versions WHERE organization_id=:org ORDER BY id',
            'SELECT id,status,row_version,parameters FROM planning.scenarios WHERE id=:scenario',
            'SELECT id,after_data FROM audit.audit_entries WHERE organization_id=:org ORDER BY id',
            'SELECT id,payload FROM integration.outbox_messages WHERE organization_id=:org ORDER BY id',
        ])


@pytest.mark.parametrize('has_current',[False,True])
@pytest.mark.parametrize('moment',['ended','end_boundary','in_progress'])
def test_expired_accept_is_atomic_with_and_without_current(engine, initial, has_current, moment):
    case,api,path,body=initial
    scenario=UUID(command(api,path,'simulations',body).json()['scenario_id'])
    with engine.begin() as conn:
        if has_current:
            conn.execute(text("UPDATE planning.plan_versions SET status='published',valid_during=tstzrange(lower(valid_during),NULL,'[)') WHERE id=:id"),{'id':case.plan_version_id})
            conn.execute(text('UPDATE core.plants SET current_plan_version_id=:plan WHERE id=:id'),{'plan':case.plan_version_id,'id':case.plant_id})
            conn.execute(text("UPDATE planning.scenarios SET scenario_kind='replan',base_plan_version_id=:plan WHERE id=:id"),{'plan':case.plan_version_id,'id':scenario})
        start,end=conn.execute(text('SELECT min(planned_start_at),max(planned_end_at) FROM planning.operation_plan_results WHERE schedule_solution_id=(SELECT id FROM planning.schedule_solutions WHERE scenario_id=:id)'),{'id':scenario}).one()
        lock=conn.scalar(text('SELECT promotion_lock_version FROM core.plants WHERE id=:id'),{'id':case.plant_id})
        conn.execute(text("UPDATE core.plants SET timezone='America/Argentina/Cordoba' WHERE id=:id"),{'id':case.plant_id})
    now={'ended':end+timedelta(seconds=1),'end_boundary':end,'in_progress':start+(end-start)/2}[moment]
    before=promotion_snapshot(engine,case,scenario)
    accept=AcceptReplan(case.organization_id,case.plant_id,case.actor_id,uuid4(),scenario,lock)
    with pytest.raises(ScenarioExpired):
        AcceptReplanService(PostgresSchedulingUnitOfWorkFactory(engine,now=lambda:now)).execute(accept)
    assert promotion_snapshot(engine,case,scenario)==before


def test_old_scenario_with_future_work_is_accepted_and_replay_survives_expiry(engine, initial):
    case,api,path,body=initial
    scenario=UUID(command(api,path,'simulations',body).json()['scenario_id'])
    with engine.begin() as conn:
        conn.execute(text("UPDATE planning.scenarios SET created_at='2020-01-01T00:00:00Z' WHERE id=:id"),{'id':scenario})
        start=conn.scalar(text('SELECT min(planned_start_at) FROM planning.operation_plan_results WHERE schedule_solution_id=(SELECT id FROM planning.schedule_solutions WHERE scenario_id=:id)'),{'id':scenario})
        lock=conn.scalar(text('SELECT promotion_lock_version FROM core.plants WHERE id=:id'),{'id':case.plant_id})
    accept=AcceptReplan(case.organization_id,case.plant_id,case.actor_id,uuid4(),scenario,lock)
    service=lambda now:AcceptReplanService(PostgresSchedulingUnitOfWorkFactory(engine,now=lambda:now))
    api.app.state.container.clock=lambda:start-timedelta(seconds=1)
    assert not gantt(api,str(scenario)).json()['scenario']['expired']
    accepted=service(start-timedelta(seconds=1)).execute(accept)
    assert current(engine,case)==accepted.plan_version_id
    replay=service(start+timedelta(days=2)).execute(accept)
    assert replay.idempotent_replay and replay.plan_version_id==accepted.plan_version_id


def test_expiry_http409_and_read_model_inspects_outside_visible_range(engine, initial, monkeypatch):
    case,api,path,body=initial
    scenario=command(api,path,'simulations',body).json()['scenario_id']
    with engine.connect() as conn:
        end=conn.scalar(text('SELECT max(planned_end_at) FROM planning.operation_plan_results WHERE schedule_solution_id=(SELECT id FROM planning.schedule_solutions WHERE scenario_id=:id)'),{'id':scenario})
    monkeypatch.setattr('production_besten.persistence.scheduling_uow._utcnow',lambda:end+timedelta(seconds=1))
    api.app.state.container.clock=lambda:end+timedelta(seconds=1)
    visible=gantt(api,scenario).json()
    assert visible['scenario']['expired'] and not visible['scenario']['stale']
    outside=api.get('/planning/current/gantt',params={'from':(HORIZON_START+timedelta(days=20)).isoformat(),'to':(HORIZON_START+timedelta(days=21)).isoformat(),'scenario_id':scenario}).json()
    assert outside['scenario']['expired']
    before=promotion_snapshot(engine,case,scenario)
    response=mutate(api,'POST',f'/scenarios/{scenario}/accept',{'expected_promotion_lock_version':visible['scenario']['promotion_lock_version']})
    assert response.status_code==409,response.text
    assert response.json()['error']['code']=='SCENARIO_EXPIRED'
    assert 'Generá una nueva simulación' in response.json()['error']['message']
    assert promotion_snapshot(engine,case,scenario)==before


@pytest.fixture
def initial(engine,editor):
    case,api,path,lot=editor
    assert save(api,path,[lot]).status_code==200
    assert action(api,path,'freeze').status_code==200
    assert command(api,path,'release').status_code==200
    with engine.begin() as conn:
        # Retain fixture history; the plant has no published CURRENT to compare against.
        conn.execute(text("UPDATE planning.plan_versions SET status='superseded',valid_during=tstzrange(lower(valid_during),:at,'[)') WHERE id=:id"),{'id':case.plan_version_id,'at':case.cutoff_at-timedelta(hours=6)})
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


def test_historical_initial_and_confirmed_remain_comparable_against_current(engine,initial):
    case,api,path,body=initial
    older_body=body|{'horizon_start':(HORIZON_START+timedelta(days=1)).isoformat()}
    older=command(api,path,'simulations',older_body).json()['scenario_id']
    source=command(api,path,'simulations',body).json()['scenario_id']
    data=gantt(api,source).json()
    accepted=mutate(api,'POST',f'/scenarios/{source}/accept',{'expected_promotion_lock_version':data['scenario']['promotion_lock_version']})
    assert accepted.status_code==201,accepted.text
    current_data=gantt(api).json()
    options=current_data['available_scenarios']
    assert {older,source}<={o['id'] for o in options}
    assert [o['created_at'] for o in options]==sorted([o['created_at'] for o in options],reverse=True)
    origin=next(o for o in options if o['id']==source)
    assert origin['status']=='confirmed' and origin['scenario_kind']=='initial'
    assert origin['origin_plan_version_number']==current_data['plan_version_number']
    before=promotion_snapshot(engine,case,UUID(older))
    historical=gantt(api,older).json()
    assert historical['plan_version_id']==current_data['plan_version_id']
    assert historical['operations']==current_data['operations']
    assert historical['scenario']['stale']
    assert historical['scenario']['operations'][0]['difference']=='DELAYED'
    assert historical['scenario']['operations'][0]['delta_minutes']==24*60
    assert historical['scenario']['operations'][0]['planned_start']!=historical['operations'][0]['planned_start']
    confirmed=gantt(api,source).json()
    assert confirmed['scenario']['origin_plan_version_number']==current_data['plan_version_number']
    assert all(o['difference']=='UNCHANGED' for o in confirmed['scenario']['operations'])
    api.app.state.container.clock=lambda:HORIZON_START+timedelta(days=3)
    expired=gantt(api,older).json()
    assert expired['scenario']['expired']
    assert next(o for o in expired['available_scenarios'] if o['id']==older)['expired']
    assert promotion_snapshot(engine,case,UUID(older))==before


def test_historical_selector_isolated_by_organization_and_plant(engine,initial):
    from tests.integration.conftest import seed_case
    from production_besten.persistence.api_queries import PostgresApiQueries
    case,api,path,body=initial
    scenario=command(api,path,'simulations',body).json()['scenario_id']
    foreign=seed_case(engine)
    query=PostgresApiQueries(engine)
    data=query.gantt(case.organization_id,case.plant_id,HORIZON_START,HORIZON_START+timedelta(days=7),'project')
    assert scenario in {str(o['id']) for o in data['available_scenarios']}
    with engine.connect() as conn:
        foreign_scenarios=set(conn.scalars(text('SELECT id FROM planning.scenarios WHERE organization_id=:org'),{'org':foreign.organization_id}))
    assert not foreign_scenarios & {o['id'] for o in data['available_scenarios']}
    from production_besten.domain.errors import EntityNotFound
    with pytest.raises(EntityNotFound):
        query.gantt(case.organization_id,foreign.plant_id,HORIZON_START,HORIZON_START+timedelta(days=7),'project',UUID(scenario))


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
    assert op['planned_segments']
    assert all(s['started_at'] < s['ended_at'] for s in op['planned_segments'])
    assert op['stage_name'] and op['skill_codes']
    assert data['plant_name']
    assert 'definition_snapshot' not in data['scenario']
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
