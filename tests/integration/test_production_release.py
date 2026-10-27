from copy import deepcopy
from datetime import datetime,timezone,timedelta
from dataclasses import replace
from uuid import UUID,uuid4
from time import perf_counter
import pytest
from sqlalchemy import text,event
from fastapi.testclient import TestClient
from production_besten.api.app import create_app
from tests.integration.test_product_editor import editor,save,action,read
from tests.integration.test_project_intake import intake,mutate
from tests.integration.scheduling_helpers import HORIZON_START,current_state
from production_besten.application.scheduling_services import GenerateScheduleService
from production_besten.domain.scheduling.models import GenerateSchedule
from production_besten.persistence.scheduling_uow import PostgresSchedulingUnitOfWorkFactory


def readiness(api,path):
    r=api.get(path.replace('product-definition','production-readiness'));assert r.status_code==200,r.text
    return r.json()


def command(api,path,name,body=None,key=None):
    r=readiness(api,path)
    payload=body or {'expected_row_version':r['row_version'],'evaluation_token':r['evaluation_token'],'reason':'Decisión explícita de prueba'}
    return mutate(api,'POST',path.replace('product-definition',name),payload,key)


def frozen(editor):
    case,api,path,lot=editor
    assert save(api,path,[lot]).status_code==200
    assert action(api,path,'freeze').status_code==200
    return case,api,path,lot


def simulate_raw(engine,case,project_ids=()):
    with engine.connect() as conn:definition=conn.scalar(text('SELECT current_product_definition_revision_id FROM core.plants WHERE id=:id'),{'id':case.plant_id})
    return GenerateScheduleService(PostgresSchedulingUnitOfWorkFactory(engine)).execute(GenerateSchedule(case.organization_id,case.plant_id,case.actor_id,'REL-'+uuid4().hex,'Release test',HORIZON_START,HORIZON_START+timedelta(days=7),definition,current_state(engine,case),tuple(project_ids)))


@pytest.mark.parametrize('stage',['empty','draft','frozen','released','withdrawn'])
def test_readiness_lifecycle(engine,editor,stage):
    _,api,path,lot=editor
    if stage!='empty':assert save(api,path,[lot]).status_code==200
    if stage not in {'empty','draft'}:assert action(api,path,'freeze').status_code==200
    if stage in {'released','withdrawn'}:assert command(api,path,'release').status_code==200
    if stage=='withdrawn':assert command(api,path,'unrelease').status_code==200
    r=readiness(api,path)
    assert r['ready']==(stage in {'frozen','released','withdrawn'})
    assert r['released']==(stage=='released')
    assert r['eligible']==(stage=='released')


@pytest.mark.parametrize('code',['MEASUREMENT','REPLANTEO'])
def test_milestone_gate_blocks_until_fact(engine,editor,code):
    case,api,path,lot=editor
    data=save(api,path,[lot]).json();op=data['lots'][0]['operations'][0];ph=op['phases'][0];definition=uuid4()
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO core.milestone_definitions(id,organization_id,code,name,category,sequence_no) VALUES (:id,:org,:code,:code,'production',20)"),{'id':definition,'org':case.organization_id,'code':code})
        conn.execute(text("INSERT INTO production.operation_gates(organization_id,required_operation_id,required_operation_phase_id,timing,gate_type,milestone_definition_id) VALUES (:org,:op,:ph,'before_start','MILESTONE',:definition)"),{'org':case.organization_id,'op':UUID(op['id']),'ph':UUID(ph['id']),'definition':definition})
    assert action(api,path,'freeze').status_code==200
    assert not readiness(api,path)['ready']
    assert command(api,path,'release').status_code==409
    endpoint='measurement' if code=='MEASUREMENT' else 'replanteo'
    project=api.get('/projects/'+data['project_id']).json()
    r=mutate(api,'POST',f"/projects/{data['project_id']}/{endpoint}",{'expected_row_version':project['row_version'],'occurred_at':'2026-10-01T12:00:00Z','notes':'Hecho realizado'})
    assert r.status_code==200,r.text
    assert readiness(api,path)['ready']
    assert command(api,path,'release').status_code==200


def test_absent_milestone_gates_are_not_fake_requirements(editor):
    _,api,path,_=frozen(editor)
    r=readiness(api,path)
    assert all(not i['applicable'] and i['satisfied'] for i in r['items'] if i['code'].startswith('MILESTONE:'))


@pytest.mark.parametrize('method',['release','unrelease'])
def test_idempotent_release_and_withdrawal(editor,method):
    _,api,path,_=frozen(editor)
    if method=='unrelease':assert command(api,path,'release').status_code==200
    before=readiness(api,path);body={'expected_row_version':before['row_version'],'evaluation_token':before['evaluation_token'],'reason':'Intención estable'};key=uuid4()
    first=command(api,path,method,body,key);assert first.status_code==200,first.text
    second=command(api,path,method,body,key);assert second.status_code==200 and second.json()['idempotent_replay']
    assert len(second.json()['history'])==len(first.json()['history'])
    assert command(api,path,method,body|{'reason':'Otra intención'},key).status_code==409


def test_release_alone_preserves_current_and_enables_scheduler(engine,editor):
    case,api,path,_=frozen(editor);pid=UUID(readiness(api,path)['project_id'])
    before=simulate_raw(engine,case)
    with engine.connect() as conn:
        snapshot=conn.scalar(text('SELECT input_snapshot FROM planning.schedule_solutions WHERE id=:id'),{'id':before.solution_id})
    assert str(pid) not in {p['id'] for p in snapshot['capacity_and_state']['projects']}
    r=command(api,path,'release');assert r.status_code==200,r.text
    with engine.connect() as conn:assert conn.scalar(text('SELECT current_plan_version_id FROM core.plants WHERE id=:id'),{'id':case.plant_id})==case.plan_version_id
    after=simulate_raw(engine,case,(pid,))
    assert after.planned_phases==1
    assert command(api,path,'unrelease').status_code==200
    after_withdraw=simulate_raw(engine,case)
    with engine.connect() as conn:
        snapshot=conn.scalar(text('SELECT input_snapshot FROM planning.schedule_solutions WHERE id=:id'),{'id':after_withdraw.solution_id})
    assert str(pid) not in {p['id'] for p in snapshot['capacity_and_state']['projects']}


@pytest.mark.parametrize('stage',['empty','draft'])
def test_no_ready_release_rejected(editor,stage):
    _,api,path,lot=editor
    if stage=='draft':save(api,path,[lot])
    assert command(api,path,'release').status_code==409


@pytest.mark.parametrize('dimension',['row','definition','master','priority','date'])
def test_stale_evaluation_conflicts(engine,editor,dimension):
    case,api,path,lot=frozen(editor);r=readiness(api,path);body={'expected_row_version':r['row_version'],'evaluation_token':r['evaluation_token'],'reason':'Stale attempt'}
    if dimension in {'row','priority','date'}:
        with engine.begin() as conn:conn.execute(text('UPDATE core.projects SET row_version=row_version+1 WHERE id=:id'),{'id':UUID(r['project_id'])})
    elif dimension=='master':
        with engine.begin() as conn:conn.execute(text("UPDATE capacity.skills SET status='inactive' WHERE id=:id"),{'id':case.skill_id})
    else:assert action(api,path,'new-revision').status_code==200
    response=command(api,path,'release',body);assert response.status_code==409,response.text
    assert response.json()['error']['code']=='PRODUCTION_RELEASE_VERSION_CONFLICT'


@pytest.mark.parametrize('endpoint',['production-readiness','release','unrelease','simulations'])
def test_tenant_plant_404(editor,endpoint):
    case,api,path,lot=frozen(editor);r=readiness(api,path)
    api.headers['X-Dev-Organization-Id']=str(case.other_organization_id)
    url=path.replace('product-definition',endpoint)
    body={'expected_row_version':r['row_version'],'evaluation_token':r['evaluation_token'],'reason':'No acceso'}
    if endpoint=='simulations':body|={'horizon_start':HORIZON_START.isoformat(),'horizon_end':(HORIZON_START+timedelta(days=7)).isoformat()}
    response=api.get(url) if endpoint=='production-readiness' else mutate(api,'POST',url,body)
    assert response.status_code==404,response.text


@pytest.mark.parametrize('endpoint',['production-readiness','release','unrelease','simulations'])
def test_cross_plant_scope(editor,endpoint):
    _,api,path,_=frozen(editor);r=readiness(api,path);api.headers['X-Dev-Plant-Id']=str(uuid4())
    body={'expected_row_version':r['row_version'],'evaluation_token':r['evaluation_token'],'reason':'Otra planta'}
    if endpoint=='simulations':body|={'horizon_start':HORIZON_START.isoformat(),'horizon_end':(HORIZON_START+timedelta(days=7)).isoformat()}
    url=path.replace('product-definition',endpoint)
    response=api.get(url) if endpoint=='production-readiness' else mutate(api,'POST',url,body)
    assert response.status_code==404


def test_release_rollback(engine,editor):
    case,api,path,_=frozen(editor)
    broken=TestClient(create_app(engine=engine,failpoints={'production_release':'after_release'},clock=lambda:HORIZON_START),raise_server_exceptions=False);broken.headers.update(api.headers)
    assert command(broken,path,'release').status_code==500
    assert not readiness(api,path)['released']
    with engine.connect() as conn:assert conn.scalar(text("SELECT count(*) FROM planning.effective_events WHERE organization_id=:org AND source_system='production_release'"),{'org':case.organization_id})==0


def test_concurrent_release_has_one_winner(editor):
    from concurrent.futures import ThreadPoolExecutor
    _,api,path,_=frozen(editor);r=readiness(api,path);body={'expected_row_version':r['row_version'],'evaluation_token':r['evaluation_token'],'reason':'Decisión'}
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:command(api,path,'release',body),range(2)))
    assert sorted(r.status_code for r in results)==[200,409]


@pytest.mark.parametrize('field,value',[('expected_row_version',0),('evaluation_token','bad'),('reason','')])
def test_inputs_422(editor,field,value):
    _,api,path,_=frozen(editor);r=readiness(api,path);body={'expected_row_version':r['row_version'],'evaluation_token':r['evaluation_token'],'reason':'Correcto'}|{field:value}
    assert command(api,path,'release',body).status_code==422


def test_simulation_endpoint_retry_is_idempotent(engine,editor):
    case,api,path,_=frozen(editor);assert command(api,path,'release').status_code==200
    r=readiness(api,path);key=uuid4();body={'expected_row_version':r['row_version'],'evaluation_token':r['evaluation_token'],'reason':'Simulación explícita','horizon_start':HORIZON_START.isoformat(),'horizon_end':(HORIZON_START+timedelta(days=7)).isoformat()}
    first=command(api,path,'simulations',body,key);assert first.status_code==200,first.text
    assert first.json()['planned_phases']==1
    assert command(api,path,'simulations',body,key).json()['idempotent_replay']
    with engine.connect() as conn:assert conn.scalar(text('SELECT current_plan_version_id FROM core.plants WHERE id=:id'),{'id':case.plant_id})==case.plan_version_id


def test_release_readiness_benchmark(engine,editor):
    _,api,path,_=frozen(editor);queries=[]
    def record(*args):queries.append(1)
    event.listen(engine,'before_cursor_execute',record)
    try:start=perf_counter();r=api.get(path.replace('product-definition','production-readiness'));elapsed=(perf_counter()-start)*1000
    finally:event.remove(engine,'before_cursor_execute',record)
    assert r.status_code==200 and len(queries)<25
    print(f'PRODUCTION_READINESS_BENCHMARK ms={elapsed:.2f} queries={len(queries)} bytes={len(r.content)}')

@pytest.mark.parametrize('kind',['material','drawing'])
def test_material_and_document_readiness_uses_own_structures(engine,editor,kind):
    case,api,path,lot=editor;data=save(api,path,[lot]).json();lot_id=UUID(data['lots'][0]['id']);target=uuid4()
    with engine.begin() as conn:
        if kind=='drawing':conn.execute(text("INSERT INTO production.drawing_packages(id,organization_id,project_lot_id,code,name) VALUES (:id,:org,:lot,'PLAN','Plano requerido')"),{'id':target,'org':case.organization_id,'lot':lot_id})
        else:conn.execute(text("INSERT INTO production.material_requirements(id,organization_id,project_lot_id,code,description,required_quantity,unit) VALUES (:id,:org,:lot,'BOARD','Tablero',2,'unit')"),{'id':target,'org':case.organization_id,'lot':lot_id})
    assert action(api,path,'freeze').status_code==200
    assert not readiness(api,path)['ready'] and command(api,path,'release').status_code==409
    with engine.begin() as conn:
        if kind=='drawing':conn.execute(text("INSERT INTO production.drawing_releases(organization_id,drawing_package_id,release_no,status,released_at,released_by) VALUES (:org,:target,1,'released',now(),:actor)"),{'org':case.organization_id,'target':target,'actor':case.actor_id})
        else:
            supplier,delivery,line=uuid4(),uuid4(),uuid4()
            conn.execute(text("INSERT INTO production.suppliers(id,organization_id,code,name) VALUES (:id,:org,'LOCAL','Proveedor fixture')"),{'id':supplier,'org':case.organization_id})
            conn.execute(text("INSERT INTO production.supplier_deliveries(id,organization_id,supplier_id,delivered_at,delivery_kind,source_system) VALUES (:id,:org,:supplier,now(),'receipt','test')"),{'id':delivery,'org':case.organization_id,'supplier':supplier})
            conn.execute(text("INSERT INTO production.supplier_delivery_lines(id,organization_id,supplier_delivery_id,line_no,material_code,quantity,unit,movement_sign) VALUES (:id,:org,:delivery,1,'BOARD',2,'unit',1)"),{'id':line,'org':case.organization_id,'delivery':delivery})
            conn.execute(text("INSERT INTO production.material_allocations(organization_id,supplier_delivery_line_id,material_requirement_id,quantity,unit,movement_sign) VALUES (:org,:line,:target,2,'unit',1)"),{'org':case.organization_id,'line':line,'target':target})
    assert readiness(api,path)['ready']
    assert command(api,path,'release').status_code==200


def test_unrelease_rejects_started_execution(engine,editor):
    from production_besten.application.execution_services import StartOperationService
    from production_besten.persistence.execution_uow import PostgresExecutionUnitOfWorkFactory
    from production_besten.domain.execution import StartOperation
    case,api,path,_=frozen(editor);assert command(api,path,'release').status_code==200
    op=read(api,path)['lots'][0]['operations'][0]
    StartOperationService(PostgresExecutionUnitOfWorkFactory(engine)).execute(StartOperation(case.organization_id,UUID(op['id']),UUID(op['phases'][0]['id']),case.cutoff_at,case.actor_id,uuid4()))
    response=command(api,path,'unrelease');assert response.status_code==409,response.text
    assert readiness(api,path)['released']


def test_new_freeze_needs_new_release_and_keeps_current_revision(engine,editor):
    case,api,path,_=frozen(editor);assert command(api,path,'release').status_code==200
    data=read(api,path);old_def=data['revisions'][0]['id'];pid=UUID(data['project_id'])
    first=simulate_raw(engine,case,(pid,))
    with engine.begin() as conn:
        conn.execute(text('UPDATE planning.plan_versions SET product_definition_revision_id=:def WHERE id=:id'),{'def':UUID(old_def),'id':case.plan_version_id})
        conn.execute(text("INSERT INTO planning.operation_plan_results(organization_id,schedule_solution_id,required_operation_id,result_status,planned_start_at,planned_end_at,remaining_work_minutes,explanation) VALUES (:org,:solution,:op,'planned',:start,:finish,30,'{}')"),{'org':case.organization_id,'solution':case.schedule_solution_id,'op':UUID(data['lots'][0]['operations'][0]['id']),'start':case.cutoff_at,'finish':case.cutoff_at+timedelta(minutes=30)})
    assert action(api,path,'new-revision').status_code==200
    assert not readiness(api,path)['ready'] and readiness(api,path)['released']
    draft=read(api,path);draft['lots'][0]['operations'][0]['phases'][0]['original_estimate_minutes']=45
    assert save(api,path,draft['lots']).status_code==200
    assert action(api,path,'freeze').status_code==200
    assert not readiness(api,path)['released']
    excluded=simulate_raw(engine,case)
    assert command(api,path,'release').status_code==200
    second=simulate_raw(engine,case,(pid,))
    with engine.connect() as conn:
        assert str(conn.scalar(text('SELECT product_definition_revision_id FROM planning.plan_versions WHERE id=:id'),{'id':case.plan_version_id}))==old_def
        assert conn.scalar(text('SELECT current_plan_version_id FROM core.plants WHERE id=:id'),{'id':case.plant_id})==case.plan_version_id
        assert conn.scalar(text('SELECT status FROM planning.scenarios WHERE id=:id'),{'id':first.scenario_id})=='stale'
        frozen_input=conn.scalar(text('SELECT input_snapshot FROM planning.schedule_solutions WHERE id=:id'),{'id':second.solution_id})
        assert frozen_input['capacity_and_state']['phases'][0]['original_minutes']==45
    assert api.get('/projects/'+str(pid)).json()['plan_requires_reconciliation']


def test_hundred_readiness_indicators_constant_queries(engine,editor):
    case,api,path,_=frozen(editor);queries=[]
    def capture(*args):queries.append(1)
    event.listen(engine,'before_cursor_execute',capture)
    try:one=api.get('/projects');one_count=len(queries)
    finally:event.remove(engine,'before_cursor_execute',capture)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO core.projects(organization_id,plant_id,customer_id,priority_id,code,name) SELECT organization_id,plant_id,customer_id,priority_id,'BENCH-'||n,'Proyecto '||n FROM core.projects CROSS JOIN generate_series(1,98) n WHERE id=:id"),{'id':UUID(readiness(api,path)['project_id'])})
    queries=[];event.listen(engine,'before_cursor_execute',capture)
    try:start=perf_counter();many=api.get('/projects');elapsed=(perf_counter()-start)*1000
    finally:event.remove(engine,'before_cursor_execute',capture)
    assert many.status_code==200 and len(many.json())==100
    assert len(queries)==one_count
    assert all('production_readiness' in p for p in many.json())
    print(f'PRODUCTION_RELEASE_LIST_BENCHMARK projects=100 ms={elapsed:.2f} queries={len(queries)} bytes={len(many.content)}')

@pytest.mark.parametrize('field',['priority','committed'])
def test_operational_priority_and_committed_date_survive_release(engine,editor,field):
    case,api,path,_=frozen(editor);assert command(api,path,'release').status_code==200
    pid=readiness(api,path)['project_id'];p=api.get('/projects/'+pid).json()
    body={k:p[k] for k in ['name','customer_id','priority_id','description','committed_date']}|{'expected_row_version':p['row_version']}
    if field=='priority':body['priority_id']=api.get('/project-intake/options').json()['priorities'][0]['id']
    else:body['committed_date']='2026-01-01'
    response=mutate(api,'PATCH','/projects/'+pid,body);assert response.status_code==200,response.text
    assert readiness(api,path)['released']
    result=simulate_raw(engine,case,(UUID(pid),))
    with engine.connect() as conn:inp=conn.scalar(text('SELECT input_snapshot FROM planning.schedule_solutions WHERE id=:id'),{'id':result.solution_id})
    project=inp['capacity_and_state']['projects'][0]
    assert project['priority_code']=='HIGH' if field=='priority' else project['committed_date']=='2026-01-01'


def test_withdrawal_preserves_current_results_and_marks_reconciliation(engine,editor):
    case,api,path,_=frozen(editor);assert command(api,path,'release').status_code==200
    data=read(api,path);pid=UUID(data['project_id']);op=UUID(data['lots'][0]['operations'][0]['id'])
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO planning.operation_plan_results(organization_id,schedule_solution_id,required_operation_id,result_status,planned_start_at,planned_end_at,remaining_work_minutes,explanation) VALUES (:org,:solution,:op,'planned',:start,:finish,30,'{}')"),{'org':case.organization_id,'solution':case.schedule_solution_id,'op':op,'start':case.cutoff_at,'finish':case.cutoff_at+timedelta(minutes=30)})
        before=conn.scalar(text('SELECT jsonb_agg(to_jsonb(r) ORDER BY id) FROM planning.operation_plan_results r WHERE schedule_solution_id=:solution'),{'solution':case.schedule_solution_id})
    assert command(api,path,'unrelease').status_code==200
    with engine.connect() as conn:
        assert conn.scalar(text('SELECT jsonb_agg(to_jsonb(r) ORDER BY id) FROM planning.operation_plan_results r WHERE schedule_solution_id=:solution'),{'solution':case.schedule_solution_id})==before
        assert conn.scalar(text('SELECT current_plan_version_id FROM core.plants WHERE id=:id'),{'id':case.plant_id})==case.plan_version_id
    assert api.get('/projects/'+str(pid)).json()['plan_requires_reconciliation']


def test_real_http_measurement_replanteo_freeze_release_simulate(engine,editor):
    case,api,path,lot=editor;data=save(api,path,[lot]).json();op=data['lots'][0]['operations'][0]
    with engine.begin() as conn:
        for seq,code in enumerate(['MEASUREMENT','REPLANTEO'],20):
            mid=uuid4()
            conn.execute(text("INSERT INTO core.milestone_definitions(id,organization_id,code,name,category,sequence_no) VALUES (:id,:org,:code,:code,'production',:seq)"),{'id':mid,'org':case.organization_id,'code':code,'seq':seq})
            conn.execute(text("INSERT INTO production.operation_gates(organization_id,required_operation_id,required_operation_phase_id,timing,gate_type,milestone_definition_id) VALUES (:org,:op,:phase,'before_start','MILESTONE',:milestone)"),{'org':case.organization_id,'op':UUID(op['id']),'phase':UUID(op['phases'][0]['id']),'milestone':mid})
    assert action(api,path,'freeze').status_code==200
    assert command(api,path,'release').status_code==409
    for endpoint in ['measurement','replanteo']:
        project=api.get('/projects/'+data['project_id']).json()
        assert mutate(api,'POST',f"/projects/{data['project_id']}/{endpoint}",{'expected_row_version':project['row_version'],'occurred_at':'2026-09-01T12:00:00Z','notes':'Proceso realizado'}).status_code==200
    assert command(api,path,'release').status_code==200
    r=readiness(api,path)
    response=command(api,path,'simulations',{'expected_row_version':r['row_version'],'evaluation_token':r['evaluation_token'],'reason':'E2E HTTP PostgreSQL','horizon_start':HORIZON_START.isoformat(),'horizon_end':(HORIZON_START+timedelta(days=7)).isoformat()})
    assert response.status_code==200,response.text
    assert response.json()['planned_phases']==1
    with engine.connect() as conn:assert conn.scalar(text('SELECT current_plan_version_id FROM core.plants WHERE id=:id'),{'id':case.plant_id})==case.plan_version_id
