from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timezone, timedelta
from time import perf_counter
from uuid import uuid4
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text,event
from production_besten.api.app import create_app
from production_besten.application.project_intake_services import ProjectIntakeService
from production_besten.domain.project_intake import ProjectIntakeCommand
from production_besten.domain.errors import ProductDefinitionConflict,IdempotencyConflict
from production_besten.persistence.project_intake_uow import PostgresProjectIntakeUnitOfWorkFactory
from tests.integration.test_operational_frontend_api import _publish_operation
from tests.integration.scheduling_helpers import prepare_basic,generate,current_state,add_operation,HORIZON_START


@pytest.fixture
def intake(engine,seeded_case):
    case=seeded_case
    with engine.begin() as conn:
        row=conn.execute(text("SELECT customer_id,priority_id FROM core.projects WHERE id=:id"),{"id":case.project_id}).one()
        conn.execute(text("UPDATE core.project_priorities SET code='NORMAL',name='Normal',rank=3 WHERE id=:id"),{"id":row.priority_id})
        high=uuid4()
        conn.execute(text("INSERT INTO core.project_priorities(id,organization_id,code,name,rank) VALUES (:id,:org,'HIGH','Alta',2)"),{"id":high,"org":case.organization_id})
    client=TestClient(create_app(engine=engine,enable_dev_context=True))
    client.headers.update({"X-Dev-Organization-Id":str(case.organization_id),"X-Dev-Plant-Id":str(case.plant_id),"X-Dev-User-Id":str(case.actor_id)})
    return case,client,{"code":"P-NEW","name":"Proyecto nuevo","customer_id":str(row.customer_id),"priority_id":str(row.priority_id),"committed_date":"2026-12-10"},high


def mutate(client,method,path,body,key=None):
    return client.request(method,path,json=body,headers={"Idempotency-Key":str(key or uuid4())})


def test_project_create_list_detail_options_and_readiness(engine,intake):
    case,api,body,_=intake
    before=current_state(engine,case)
    created=mutate(api,'POST','/projects',body)
    assert created.status_code==201,created.text
    project=created.json()
    assert project['status']=='draft' and project['ready_for_definition'] and not project['plannable']
    assert project['measurement']['occurred_at'] is None
    assert current_state(engine,case)==before
    assert api.get('/projects/'+project['id']).json()==project
    assert len(api.get('/projects').json())==2
    options=api.get('/project-intake/options').json()
    assert [p['code'] for p in options['priorities']]==['HIGH','NORMAL']
    assert options['plant']['id']==str(case.plant_id)


@pytest.mark.parametrize('field,value',[('name','Nueva referencia'),('description','Notas comerciales'),('committed_date','2026-12-20')])
def test_edit_mutable_fields_preserves_frozen_snapshot(engine,intake,field,value):
    case,api,body,_=intake
    project=mutate(api,'POST','/projects',body).json()
    with engine.connect() as conn:
        original=conn.scalar(text('SELECT canonical_snapshot FROM production.product_definition_revisions WHERE id=:id'),{'id':case.definition_revision_id})
    update={key:project[key] for key in ('name','description','customer_id','priority_id','committed_date')}|{field:value,'expected_row_version':1}
    response=mutate(api,'PATCH','/projects/'+project['id'],update)
    assert response.status_code==200,response.text
    assert response.json()['project'][field]==value
    with engine.connect() as conn:
        assert conn.scalar(text('SELECT canonical_snapshot FROM production.product_definition_revisions WHERE id=:id'),{'id':case.definition_revision_id})==original


def test_edit_customer_uses_existing_entity(engine,intake):
    case,api,body,_=intake
    customer=uuid4()
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO core.customers(id,organization_id,code,display_name,email,phone) VALUES (:id,:org,'SECOND','Cliente Dos','cliente@example.invalid','123')"),{'id':customer,'org':case.organization_id})
    p=mutate(api,'POST','/projects',body).json()
    response=mutate(api,'PATCH','/projects/'+p['id'],{key:p[key] for key in ('name','description','priority_id','committed_date')}|{'customer_id':str(customer),'expected_row_version':1})
    assert response.status_code==200,response.text
    assert response.json()['project']['customer_name']=='Cliente Dos'
    assert response.json()['project']['customer_phone']=='123'


@pytest.mark.parametrize('kind',['measurement','replanteo'])
def test_milestones_append_facts_and_supersede_corrections(engine,intake,kind):
    case,api,body,_=intake
    p=mutate(api,'POST','/projects',body).json()
    for version,notes in ((1,'Primera constatación'),(2,'Corrección de observación')):
        response=mutate(api,'POST',f"/projects/{p['id']}/{kind}",{'expected_row_version':version,'occurred_at':'2026-09-01T12:00:00-03:00','notes':notes})
        assert response.status_code==200,response.text
        assert response.json()['project'][kind]['notes']==notes
    with engine.connect() as conn:
        rows=conn.execute(text('SELECT supersedes_id FROM core.project_milestones WHERE project_id=:id ORDER BY created_at'),{'id':p['id']}).all()
        assert len(rows)==2 and rows[0].supersedes_id is None and rows[1].supersedes_id is not None


@pytest.mark.parametrize('occurred_at',['2099-01-01T12:00:00Z','2026-09-01T12:00:00'])
def test_planned_or_naive_measurement_is_not_a_completed_fact(intake,occurred_at):
    _,api,body,_=intake
    p=mutate(api,'POST','/projects',body).json()
    assert mutate(api,'POST',f"/projects/{p['id']}/measurement",{'expected_row_version':1,'occurred_at':occurred_at}).status_code==400
    assert api.get('/projects/'+p['id']).json()['row_version']==1


def test_lifecycle_archive_preserves_history_and_is_terminal(engine,intake):
    case,api,body,_=intake
    p=mutate(api,'POST','/projects',body).json()
    for version,status in enumerate(('active','inactive','active','archived'),1):
        r=mutate(api,'POST',f"/projects/{p['id']}/status",{'expected_row_version':version,'status':status})
        assert r.status_code==200,r.text
        assert r.json()['project']['status']==status
    assert api.get('/projects/'+p['id']).status_code==200
    assert mutate(api,'POST',f"/projects/{p['id']}/status",{'expected_row_version':5,'status':'active'}).status_code==409
    with engine.connect() as conn:
        assert conn.scalar(text('SELECT count(*) FROM audit.audit_entries WHERE entity_id=:id'),{'id':p['id']})==5


def test_invalid_transition_and_real_execution_block_archive(intake):
    case,api,body,_=intake
    p=mutate(api,'POST','/projects',body).json()
    assert mutate(api,'POST',f"/projects/{p['id']}/status",{'expected_row_version':1,'status':'inactive'}).status_code==409
    r=mutate(api,'POST',f'/projects/{case.project_id}/status',{'expected_row_version':1,'status':'archived'})
    assert r.status_code==409 and 'ejecución' in r.text


def test_new_project_never_creates_plannable_demand(engine,intake):
    case,api,body,_=intake
    prepare_basic(engine,case)
    p=mutate(api,'POST','/projects',body).json()
    mutate(api,'POST',f"/projects/{p['id']}/status",{'expected_row_version':1,'status':'active'})
    result=generate(engine,case,project_ids=())
    with engine.connect() as conn:
        stored=conn.scalar(text('SELECT input_snapshot FROM planning.schedule_solutions WHERE id=:id'),{'id':result.solution_id})
    assert str(p['id']) not in {p['id'] for p in stored['capacity_and_state']['projects']}
    assert not api.get('/projects/'+p['id']).json()['plannable']


@pytest.mark.parametrize('field',['priority_id','committed_date'])
def test_admin_planning_change_reconciles_without_rewriting_current(engine,intake,field):
    case,api,_,high=intake
    prepare_basic(engine,case)
    _publish_operation(engine,case)
    scenario=generate(engine,case)
    p=api.get('/projects/'+str(case.project_id)).json()
    state=current_state(engine,case)
    with engine.connect() as conn:
        plan=conn.scalar(text('SELECT row_to_json(p) FROM planning.plan_versions p WHERE id=:id'),{'id':case.plan_version_id})
        actual=conn.execute(text('SELECT row_to_json(e) FROM execution.execution_segments e WHERE organization_id=:org ORDER BY id'),{'org':case.organization_id}).scalars().all()
    body={key:p[key] for key in ('name','description','customer_id','priority_id','committed_date')}|{field:str(high) if field=='priority_id' else '2026-01-01','expected_row_version':1}
    r=mutate(api,'PATCH','/projects/'+p['id'],body)
    assert r.status_code==200,r.text
    assert r.json()['project']['plan_requires_reconciliation']
    assert current_state(engine,case)!=state
    with engine.connect() as conn:
        assert conn.scalar(text('SELECT row_to_json(p) FROM planning.plan_versions p WHERE id=:id'),{'id':case.plan_version_id})==plan
        assert conn.execute(text('SELECT row_to_json(e) FROM execution.execution_segments e WHERE organization_id=:org ORDER BY id'),{'org':case.organization_id}).scalars().all()==actual
        assert conn.scalar(text('SELECT status FROM planning.scenarios WHERE id=:id'),{'id':scenario.scenario_id})=='stale'
    if field=='committed_date':assert r.json()['project']['overdue']
    else:
        next_result=generate(engine,case)
        with engine.connect() as conn:
            stored=conn.scalar(text('SELECT input_snapshot FROM planning.schedule_solutions WHERE id=:id'),{'id':next_result.solution_id})
        assert stored['capacity_and_state']['projects'][0]['priority_code']=='HIGH'


@pytest.mark.parametrize('operation',['list','detail','update','measurement','status'])
def test_cross_tenant_isolation(engine,intake,operation):
    case,api,_,_=intake
    p=api.get('/projects/'+str(case.project_id)).json()
    api.headers['X-Dev-Organization-Id']=str(case.other_organization_id)
    if operation=='list':r=api.get('/projects')
    elif operation=='detail':r=api.get('/projects/'+p['id'])
    elif operation=='update':r=mutate(api,'PATCH','/projects/'+p['id'],{key:p[key] for key in ('name','description','customer_id','priority_id','committed_date')}|{'expected_row_version':1})
    elif operation=='status':r=mutate(api,'POST',f"/projects/{p['id']}/status",{'status':'inactive','expected_row_version':1})
    else:r=mutate(api,'POST',f"/projects/{p['id']}/measurement",{'occurred_at':'2026-09-01T12:00:00Z','expected_row_version':1})
    assert r.status_code==404


def test_idempotency_replays_and_payload_or_plant_reuse_conflicts(engine,intake):
    case,api,body,_=intake
    key=uuid4()
    first=mutate(api,'POST','/projects',body,key)
    second=mutate(api,'POST','/projects',body,key)
    assert first.status_code==second.status_code==201 and first.json()==second.json()
    assert mutate(api,'POST','/projects',body|{'name':'Other'},key).status_code==409
    plant=uuid4()
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO core.plants(id,organization_id,code,name,timezone,base_calendar_id) VALUES (:id,:org,'SECOND','Second','UTC',:cal)"),{'id':plant,'org':case.organization_id,'cal':case.calendar_id})
    api.headers['X-Dev-Plant-Id']=str(plant)
    assert mutate(api,'POST','/projects',body,key).status_code==409


def test_concurrency_rejects_silent_last_write_wins(engine,intake):
    case,api,body,_=intake
    p=mutate(api,'POST','/projects',body).json()
    payload={key:p[key] for key in ('name','description','customer_id','priority_id','committed_date')}
    command=ProjectIntakeCommand(case.organization_id,case.plant_id,case.actor_id,uuid4(),'update',payload,p['id'],1)
    def update(name):
        return ProjectIntakeService(PostgresProjectIntakeUnitOfWorkFactory(engine)).execute(replace(command,command_id=uuid4(),payload=payload|{'name':name}))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=[]
        for future in [pool.submit(update,'One'),pool.submit(update,'Two')]:
            try:future.result();results.append('ok')
            except ProductDefinitionConflict:results.append('conflict')
    assert sorted(results)==['conflict','ok']


def test_rollback_is_atomic(engine,intake):
    case,api,body,_=intake
    failing=TestClient(create_app(engine=engine,enable_dev_context=True,failpoints={'project_intake':'after_intake'}),raise_server_exceptions=False)
    failing.headers.update(api.headers)
    key=uuid4()
    assert mutate(failing,'POST','/projects',body,key).status_code==500
    with engine.connect() as conn:
        assert conn.scalar(text('SELECT count(*) FROM core.projects WHERE organization_id=:org AND code=:code'),{'org':case.organization_id,'code':body['code']})==0
        assert conn.scalar(text('SELECT count(*) FROM audit.audit_entries WHERE request_id=:id'),{'id':key})==0


@pytest.mark.parametrize('query',[{'search':'nuevo'},{'priority':'NORMAL'},{'status':'draft'},{'committed_from':'2026-12-01','committed_to':'2026-12-31'}])
def test_list_filter_and_search(intake,query):
    _,api,body,_=intake
    p=mutate(api,'POST','/projects',body).json()
    rows=api.get('/projects',params=query).json()
    assert p['id'] in [r['id'] for r in rows]


def test_contract_404_409_422_and_openapi(intake):
    _,api,body,_=intake
    assert api.get('/projects/'+str(uuid4())).status_code==404
    assert mutate(api,'POST','/projects',body|{'name':''}).status_code==422
    assert api.post('/projects',json=body).status_code==422
    assert mutate(api,'POST','/projects',body).status_code==201
    assert mutate(api,'POST','/projects',body).status_code==409
    assert '/projects/{project_id}/measurement' in api.get('/openapi.json').json()['paths']


def test_hundred_projects_list_benchmark_and_constant_queries(engine,intake):
    case,api,body,_=intake
    with engine.begin() as conn:
        for i in range(99):
            conn.execute(text("INSERT INTO core.projects(organization_id,plant_id,customer_id,priority_id,code,name) VALUES (:org,:plant,:customer,:priority,:code,:code)"),{'org':case.organization_id,'plant':case.plant_id,'customer':body['customer_id'],'priority':body['priority_id'],'code':f'P-{i:03}'})
    queries=[]
    def record(*args):queries.append(args[2])
    event.listen(engine,'before_cursor_execute',record)
    try:
        start=perf_counter();response=api.get('/projects');elapsed=(perf_counter()-start)*1000
    finally:event.remove(engine,'before_cursor_execute',record)
    assert response.status_code==200 and len(response.json())==100
    assert len(queries)==5
    print(f'PROJECT_INTAKE_BENCHMARK projects=100 endpoint_ms={elapsed:.2f} payload_bytes={len(response.content)} sql_queries={len(queries)}')


def freeze(engine,case):
    from production_besten.application.product_definition_services import CreateProductDefinitionRevisionService
    from production_besten.domain.product_definition import CreateProductDefinitionRevision
    from production_besten.persistence.product_definition_uow import PostgresProductDefinitionUnitOfWorkFactory
    return CreateProductDefinitionRevisionService(PostgresProductDefinitionUnitOfWorkFactory(engine)).execute(
        CreateProductDefinitionRevision(case.organization_id,case.plant_id,case.actor_id,uuid4(),'Freeze fixture before intake'))


@pytest.mark.parametrize('freeze_first',[True,False])
def test_unfrozen_project_with_operations_remains_outside_scheduler(engine,intake,freeze_first):
    case,api,body,_=intake
    prepare_basic(engine,case)
    definition_id=freeze(engine,case).revision_id if freeze_first else case.definition_revision_id
    p=mutate(api,'POST','/projects',body).json()
    mutate(api,'POST',f"/projects/{p['id']}/status",{'expected_row_version':1,'status':'active'})
    from uuid import UUID
    with engine.begin() as conn:
        add_operation(conn,case,'UNRELEASED',project_id=UUID(p['id']),resource_type_id=case.resource_type_id)
    result=generate(engine,case,project_ids=(),definition_id=definition_id)
    with engine.connect() as conn:
        stored=conn.scalar(text('SELECT input_snapshot FROM planning.schedule_solutions WHERE id=:id'),{'id':result.solution_id})
    assert p['id'] not in {project['id'] for project in stored['capacity_and_state']['projects']}
    assert not api.get('/projects/'+p['id']).json()['plannable']


def test_priority_edit_changes_competing_projects_next_schedule_order(engine,intake):
    case,api,body,_=intake
    prepare_basic(engine,case,minutes=120)
    competitor=uuid4()
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO core.projects(id,organization_id,plant_id,customer_id,priority_id,code,name,status,committed_date) VALUES (:id,:org,:plant,:customer,:priority,'COMPETITOR','Competitor','active','2026-01-01')"),{'id':competitor,'org':case.organization_id,'plant':case.plant_id,'customer':body['customer_id'],'priority':body['priority_id']})
        _,phase=add_operation(conn,case,'COMPETE',project_id=competitor,resource_type_id=case.resource_type_id)
    revision=freeze(engine,case)
    first=generate(engine,case,project_ids=(),definition_id=revision.revision_id)
    from tests.integration.scheduling_helpers import solution_segments
    assert solution_segments(engine,first.solution_id)[0]['required_operation_phase_id']==phase
    project=api.get('/projects/'+str(case.project_id)).json()
    high=api.get('/project-intake/options').json()['priorities'][0]['id']
    update={key:project[key] for key in ('name','description','customer_id','priority_id','committed_date')}|{'priority_id':high,'expected_row_version':1}
    assert mutate(api,'PATCH','/projects/'+project['id'],update).status_code==200
    next_result=generate(engine,case,project_ids=(),definition_id=revision.revision_id)
    assert solution_segments(engine,next_result.solution_id)[0]['required_operation_phase_id']==case.phase_id
    with engine.connect() as conn:
        assert conn.scalar(text('SELECT current_plan_version_id FROM core.plants WHERE id=:id'),{'id':case.plant_id})==case.plan_version_id


def test_committed_estimated_communicated_dates_never_overwrite_each_other(engine,intake):
    case,api,_,_=intake
    prepare_basic(engine,case);_publish_operation(engine,case)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO portal.communicated_dates(organization_id,project_id,date_kind,communicated_date,approved_by,communicated_at) VALUES (:org,:project,'installation','2026-12-01',:actor,now())"),{'org':case.organization_id,'project':case.project_id,'actor':case.actor_id})
    p=api.get('/projects/'+str(case.project_id)).json()
    update={key:p[key] for key in ('name','description','customer_id','priority_id','committed_date')}|{'committed_date':'2026-12-20','expected_row_version':1}
    changed=mutate(api,'PATCH','/projects/'+p['id'],update).json()['project']
    assert changed['committed_date']=='2026-12-20'
    assert changed['communicated_date']==p['communicated_date']=='2026-12-01'
    assert changed['estimated_date']==p['estimated_date']
    assert changed['planned_operation_ids']
