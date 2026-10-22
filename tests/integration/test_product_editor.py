from copy import deepcopy
from datetime import timedelta
from time import perf_counter
import json
from uuid import uuid4, UUID
import pytest
from sqlalchemy import text, event
from fastapi.testclient import TestClient
from production_besten.api.app import create_app
from tests.integration.test_project_intake import intake, mutate
from tests.integration.test_product_definition_commands import _route
from tests.integration.scheduling_helpers import prepare_basic, generate, solution_segments


@pytest.fixture
def editor(engine,intake):
    case,api,body,_=intake
    prepare_basic(engine,case)
    p=mutate(api,'POST','/projects',body).json()
    mutate(api,'POST',f"/projects/{p['id']}/status",{'expected_row_version':1,'status':'active'})
    route,_,_=_route(engine,case)
    path=f"/projects/{p['id']}/product-definition"
    lot={'code':'LOT','name':'Cocina','quantity':2,'unit':'unidad','route_version_id':str(route),'operations':[{'code':'CUT','name':'Corte','operation_definition_id':str(case.operation_definition_id),'predecessor_codes':[],'phases':[{'code':'WORK','name':'Trabajo','estimate_kind':'elapsed','original_estimate_minutes':30,'split_policy':'splittable','labor_requirements':[{'skill_id':str(case.skill_id),'min_people':1,'max_people':1,'work_minutes':30}],'physical_requirements':[{'work_center_id':str(case.work_center_id),'physical_resource_type_id':str(case.resource_type_id),'quantity':1,'capacity_units':1,'usage_mode':'active_use'}]}]}]}
    return case,api,path,lot


def read(api,path):
    response=api.get(path)
    assert response.status_code==200,response.text
    return response.json()


def save(api,path,lots,version=None,key=None):
    return mutate(api,'PUT',path,{'expected_row_version':version or read(api,path)['row_version'],'lots':lots},key)


def action(api,path,name,version=None,key=None):
    return mutate(api,'POST',path+'/'+name,{'expected_row_version':version or read(api,path)['row_version'],'reason':'Prueba definición'},key)


def test_empty_and_options(editor):
    _,api,path,_=editor
    assert read(api,path)['status']=='empty'
    opts=api.get('/product-definition/options').json()
    assert all(opts[k] for k in ('operations','skills','centers','routes','resource_types'))


def test_save_multiple_lots_operations_phases_and_edit(editor):
    _,api,path,lot=editor
    other=deepcopy(lot);other['code']='OTHER';other['name']='Armario'
    op=deepcopy(lot['operations'][0]);op['code']='ASSEMBLE';op['predecessor_codes']=['CUT'];op['phases'].append(deepcopy(op['phases'][0]));op['phases'][1]['code']='FINISH'
    lot['operations'].append(op)
    response=save(api,path,[lot,other]);assert response.status_code==200,response.text
    data=response.json();assert len(data['lots'])==2 and len(data['lots'][0]['operations'])==2
    data['lots'][0]['name']='Cocina editada';data['lots'][0]['operations'][1]['phases'][0]['original_estimate_minutes']=90
    response=save(api,path,data['lots']);assert response.status_code==200,response.text
    assert response.json()['lots'][0]['name']=='Cocina editada'
    assert response.json()['lots'][0]['operations'][1]['phases'][0]['original_estimate_minutes']==90


@pytest.mark.parametrize('variant',['self','cycle','outside','order','duplicate','skill','center','resource','definition'])
def test_graph_and_tenant_catalog_validation(editor,variant):
    _,api,path,lot=editor
    op=lot['operations'][0]
    if variant=='self':op['predecessor_codes']=['CUT']
    if variant=='outside':op['predecessor_codes']=['MISSING']
    if variant in {'cycle','order'}:
        other=deepcopy(op);other['code']='NEXT';other['predecessor_codes']=['CUT'];lot['operations'].append(other);op['predecessor_codes']=['NEXT'] if variant=='cycle' else ['NEXT'];other['predecessor_codes']=[] if variant=='order' else ['CUT']
    if variant=='duplicate':lot['operations'].append(deepcopy(op))
    if variant=='skill':op['phases'][0]['labor_requirements'][0]['skill_id']=str(uuid4())
    if variant=='center':op['phases'][0]['physical_requirements'][0]['work_center_id']=str(uuid4())
    if variant=='resource':op['phases'][0]['physical_requirements'][0]['physical_resource_type_id']=str(uuid4())
    if variant=='definition':op['operation_definition_id']=str(uuid4())
    response=save(api,path,[lot]);assert response.status_code==409,response.text
    assert not read(api,path)['lots']


@pytest.mark.parametrize('table,field', [('capacity.skills','skill_id'),('capacity.work_centers','work_center_id'),('capacity.physical_resource_types','physical_resource_type_id')])
def test_inactive_master_not_offered_or_accepted(engine,editor,table,field):
    _,api,path,lot=editor
    req=lot['operations'][0]['phases'][0]['labor_requirements' if field=='skill_id' else 'physical_requirements'][0]
    with engine.begin() as conn:conn.execute(text(f"UPDATE {table} SET status='inactive' WHERE id=:id"),{'id':UUID(req[field])})
    assert save(api,path,[lot]).status_code==409


@pytest.mark.parametrize('invalid',['empty','operation','phase','zero'])
def test_incomplete_draft_saves_but_never_freezes(editor,invalid):
    _,api,path,lot=editor
    lots=[lot]
    if invalid=='empty':lots=[]
    if invalid=='route':lot['route_version_id']=None
    if invalid=='operation':lot['operations']=[]
    if invalid=='phase':lot['operations'][0]['phases']=[]
    if invalid=='zero':lot['operations'][0]['phases'][0]['original_estimate_minutes']=0
    response=save(api,path,lots);assert response.status_code==200,response.text
    assert response.json()['errors']
    assert action(api,path,'freeze').status_code==400


def test_freeze_retry_new_revision_history_and_current(engine,editor):
    case,api,path,lot=editor
    assert save(api,path,[lot]).status_code==200
    before=read(api,path);key=uuid4()
    frozen=action(api,path,'freeze',before['row_version'],key);assert frozen.status_code==200,frozen.text
    frozen=frozen.json();assert frozen['status']=='frozen'
    replay=action(api,path,'freeze',before['row_version'],key);assert replay.status_code==200 and replay.json()['idempotent_replay']
    original=frozen['revisions'][0]
    assert save(api,path,frozen['lots']).status_code==409
    assert action(api,path,'new-revision').status_code==200
    draft=read(api,path);assert draft['draft_id']!=frozen['draft_id']
    draft['lots'][0]['operations'][0]['phases'][0]['original_estimate_minutes']=75
    assert save(api,path,draft['lots']).status_code==200
    next_rev=action(api,path,'freeze');assert next_rev.status_code==200,next_rev.text
    revisions=next_rev.json()['revisions'];assert revisions[0]['id']!=original['id']
    assert next(r for r in revisions if r['id']==original['id'])['snapshot']==original['snapshot']
    with engine.connect() as conn:
        assert conn.scalar(text('SELECT current_plan_version_id FROM core.plants WHERE id=:id'),{'id':case.plant_id})==case.plan_version_id


def test_scheduler_uses_frozen_demand_while_next_draft_changes(engine,editor):
    case,api,path,lot=editor
    other=deepcopy(lot['operations'][0]);other['code']='NEXT';other['predecessor_codes']=['CUT'];lot['operations'].append(other)
    assert save(api,path,[lot]).status_code==200
    assert action(api,path,'freeze').status_code==200
    frozen=read(api,path);pid=UUID(frozen['project_id']);revision=UUID(frozen['revisions'][0]['id'])
    run=generate(engine,case,project_ids=(pid,),definition_id=revision)
    segments=solution_segments(engine,run.solution_id)
    assert len(segments)==2
    with engine.connect() as conn:
        inp=conn.scalar(text('SELECT input_snapshot FROM planning.schedule_solutions WHERE id=:id'),{'id':run.solution_id})
    assert all(p['original_minutes']==30 for p in inp['capacity_and_state']['phases'])
    assert action(api,path,'new-revision').status_code==200
    draft=read(api,path);draft['lots'][0]['operations'][0]['phases'][0]['original_estimate_minutes']=95
    assert save(api,path,draft['lots']).status_code==200
    run2=generate(engine,case,project_ids=(pid,),definition_id=revision)
    with engine.connect() as conn:
        inp2=conn.scalar(text('SELECT input_snapshot FROM planning.schedule_solutions WHERE id=:id'),{'id':run2.solution_id})
    assert [p['original_minutes'] for p in inp2['capacity_and_state']['phases']]==[30,30]
    assert action(api,path,'freeze').status_code==200
    next_revision=UUID(read(api,path)['revisions'][0]['id'])
    run3=generate(engine,case,project_ids=(pid,),definition_id=next_revision)
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT status FROM planning.scenarios WHERE id=:id"),{'id':run2.scenario_id})=='stale'
        assert conn.scalar(text('SELECT current_plan_version_id FROM core.plants WHERE id=:id'),{'id':case.plant_id})==case.plan_version_id


def test_draft_without_freeze_not_scheduled(engine,editor):
    case,api,path,lot=editor
    assert save(api,path,[lot]).status_code==200
    run=generate(engine,case,project_ids=())
    with engine.connect() as conn:
        inp=conn.scalar(text('SELECT input_snapshot FROM planning.schedule_solutions WHERE id=:id'),{'id':run.solution_id})
    assert read(api,path)['project_id'] not in {p['id'] for p in inp['capacity_and_state']['projects']}


@pytest.mark.parametrize('change',['save','freeze','validate','new-revision'])
def test_concurrency_has_visible_conflict(editor,change):
    _,api,path,lot=editor
    assert save(api,path,[lot]).status_code==200
    response=save(api,path,[lot],1) if change=='save' else action(api,path,change,1)
    assert response.status_code==409
    assert response.json()['error']['code']=='PRODUCT_EDITOR_VERSION_CONFLICT'


def test_idempotency_payload_and_context_conflicts(editor):
    _,api,path,lot=editor
    version=read(api,path)['row_version'];key=uuid4()
    result=save(api,path,[lot],version,key);assert result.status_code==200
    assert save(api,path,[lot],version,key).json()['idempotent_replay']
    lot['name']='Different'
    assert save(api,path,[lot],version,key).status_code==409
    assert action(api,path,'validate',version,key).status_code==409


@pytest.mark.parametrize('method,tail',[('GET',''),('PUT',''),('POST','freeze'),('POST','validate'),('POST','new-revision')])
def test_cross_tenant_and_project_404(editor,method,tail):
    case,api,path,lot=editor
    api.headers['X-Dev-Organization-Id']=str(case.other_organization_id)
    response=api.get(path) if method=='GET' else mutate(api,method,path+('/'+tail if tail else ''),{'expected_row_version':2,'lots':[lot]} if method=='PUT' else {'expected_row_version':2})
    assert response.status_code==404,response.text


def test_rollback_is_atomic(engine,editor):
    case,api,path,lot=editor
    broken=TestClient(create_app(engine=engine,failpoints={'product_editor':'after_editor'}),raise_server_exceptions=False);broken.headers.update(api.headers)
    assert save(broken,path,[lot]).status_code==500
    assert not read(api,path)['lots']


@pytest.mark.parametrize('field,value',[('quantity',-1),('name',''),('name','   '),('operations',None)])
def test_structural_input_422(editor,field,value):
    _,api,path,lot=editor;lot[field]=value
    assert save(api,path,[lot]).status_code==422


def test_remove_draft_phase_operation_and_reorder(editor):
    _,api,path,lot=editor
    op=deepcopy(lot['operations'][0]);op['code']='NEXT';op['predecessor_codes']=['CUT'];lot['operations'].append(op)
    saved=save(api,path,[lot]).json();saved['lots'][0]['operations'][0]['phases']=[]
    assert save(api,path,saved['lots']).status_code==200
    saved=read(api,path);saved['lots'][0]['operations']=saved['lots'][0]['operations'][:1]
    result=save(api,path,saved['lots']);assert result.status_code==200,result.text
    assert len(result.json()['lots'][0]['operations'])==1


def test_definition_benchmark_5_lots_50_operations_100_phases(engine,editor):
    _,api,path,lot=editor;lots=[]
    for li in range(5):
        l=deepcopy(lot);l['code']=f'L{li}';l['operations']=[]
        for oi in range(10):
            op=deepcopy(lot['operations'][0]);op['code']=f'O{oi}';op['predecessor_codes']=[f'O{oi-1}'] if oi else []
            ph=deepcopy(op['phases'][0]);ph['code']='SECOND';op['phases'].append(ph);l['operations'].append(op)
        lots.append(l)
    response=save(api,path,lots);assert response.status_code==200,response.text
    queries=[]
    def capture(*args):queries.append(1)
    event.listen(engine,'before_cursor_execute',capture)
    try:
        start=perf_counter();response=api.get(path);elapsed=(perf_counter()-start)*1000
    finally:event.remove(engine,'before_cursor_execute',capture)
    assert response.status_code==200
    assert len(queries)<25
    print(f'PRODUCT_EDITOR_BENCHMARK ms={elapsed:.2f} bytes={len(response.content)} queries={len(queries)}')

def test_manual_lot_route_uses_existing_command_and_published_history(editor):
    _,api,path,lot=editor;lot['route_version_id']=None
    saved=save(api,path,[lot]);assert saved.status_code==200,saved.text
    data=saved.json();assert data['lots'][0]['route_version_id'] and not data['errors']
    old_route=data['lots'][0]['route_version_id']
    data['lots'][0]['operations'][0]['name']='Otra operación'
    updated=save(api,path,data['lots']);assert updated.status_code==200,updated.text
    assert updated.json()['lots'][0]['route_version_id']!=old_route


def test_deleted_next_draft_retains_frozen_scheduler_demand(engine,editor):
    case,api,path,lot=editor
    assert save(api,path,[lot]).status_code==200
    assert action(api,path,'freeze').status_code==200
    data=read(api,path);revision=UUID(data['revisions'][0]['id']);pid=UUID(data['project_id'])
    assert action(api,path,'new-revision').status_code==200
    assert save(api,path,[]).status_code==200
    result=generate(engine,case,project_ids=(pid,),definition_id=revision)
    assert len(solution_segments(engine,result.solution_id))==1

@pytest.mark.parametrize('demand,simultaneous',[(1,True),(2,False)])
def test_editor_aggregate_demand_reaches_scheduler(engine,editor,demand,simultaneous):
    case,api,path,lot=editor
    with engine.begin() as conn:
        conn.execute(text("UPDATE capacity.work_centers SET capacity_mode='cumulative',aggregate_capacity=2 WHERE id=:id"),{'id':case.work_center_id})
        conn.execute(text("UPDATE capacity.physical_resources SET scheduling_mode='cumulative',capacity_units=2 WHERE id=:id"),{'id':case.physical_resource_id})
    original=lot['operations'][0];original['phases'][0]['labor_requirements']=[]
    original['phases'][0]['physical_requirements']=[{'work_center_id':str(case.work_center_id),'quantity':1,'capacity_units':demand,'usage_mode':'active_use'}]
    for code in ['B','C']:
        op=deepcopy(original);op['code']=code;lot['operations'].append(op)
    assert save(api,path,[lot]).status_code==200
    assert action(api,path,'freeze').status_code==200
    data=read(api,path)
    result=generate(engine,case,project_ids=(UUID(data['project_id']),),definition_id=UUID(data['revisions'][0]['id']))
    segments=solution_segments(engine,result.solution_id);assert len(segments)==3
    assert (segments[0]['start_at']==segments[1]['start_at'])==simultaneous
    assert segments[2]['start_at']>=segments[0]['end_at']


def test_freeze_new_revision_marks_current_reconciliation_and_scenario_stale(engine,editor):
    case,api,path,lot=editor
    assert save(api,path,[lot]).status_code==200
    assert action(api,path,'freeze').status_code==200
    data=read(api,path);op=UUID(data['lots'][0]['operations'][0]['id'])
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO planning.operation_plan_results(id,organization_id,schedule_solution_id,required_operation_id,result_status,planned_start_at,planned_end_at,remaining_work_minutes,explanation) VALUES (:id,:org,:solution,:op,'planned',:start,:end,30,'{}')"),{'id':uuid4(),'org':case.organization_id,'solution':case.schedule_solution_id,'op':op,'start':case.cutoff_at,'end':case.cutoff_at+timedelta(minutes=30)})
        before=conn.scalar(text('SELECT jsonb_agg(to_jsonb(r) ORDER BY id) FROM planning.operation_plan_results r WHERE schedule_solution_id=:solution'),{'solution':case.schedule_solution_id})
    scenario=generate(engine,case,project_ids=(UUID(data['project_id']),),definition_id=UUID(data['revisions'][0]['id']))
    assert action(api,path,'new-revision').status_code==200
    data=read(api,path);data['lots'][0]['operations'][0]['phases'][0]['original_estimate_minutes']=45
    assert save(api,path,data['lots']).status_code==200
    assert action(api,path,'freeze').status_code==200
    with engine.connect() as conn:
        assert conn.scalar(text('SELECT current_plan_version_id FROM core.plants WHERE id=:id'),{'id':case.plant_id})==case.plan_version_id
        assert conn.scalar(text('SELECT jsonb_agg(to_jsonb(r) ORDER BY id) FROM planning.operation_plan_results r WHERE schedule_solution_id=:solution'),{'solution':case.schedule_solution_id})==before
        assert conn.scalar(text('SELECT status FROM planning.scenarios WHERE id=:id'),{'id':scenario.scenario_id})=='stale'
        assert conn.scalar(text("SELECT change_summary->>'current_affected' FROM planning.planning_state_revisions WHERE id=(SELECT current_revision_id FROM planning.planning_state_heads WHERE plant_id=:plant)"),{'plant':case.plant_id})=='true'


@pytest.mark.parametrize('dimension',['skill','resource'])
def test_frozen_editor_scheduler_selects_actual_skilled_person_and_resource(engine,editor,dimension):
    case,api,path,lot=editor
    assert save(api,path,[lot]).status_code==200
    assert action(api,path,'freeze').status_code==200
    data=read(api,path);result=generate(engine,case,project_ids=(UUID(data['project_id']),),definition_id=UUID(data['revisions'][0]['id']))
    with engine.connect() as conn:
        table,column=('planning.human_segment_assignments','employee_id') if dimension=='skill' else ('planning.physical_resource_reservations','physical_resource_id')
        actual=conn.scalars(text(f'SELECT {column} FROM {table} WHERE schedule_solution_id=:id'),{'id':result.solution_id}).all()
    assert actual and set(actual)=={case.employee_id if dimension=='skill' else case.physical_resource_id}

def test_simultaneous_saves_reject_lost_update(editor):
    from concurrent.futures import ThreadPoolExecutor
    _,api,path,lot=editor;version=read(api,path)['row_version']
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses=list(pool.map(lambda _:save(api,path,[deepcopy(lot)],version),range(2)))
    assert sorted(r.status_code for r in responses)==[200,409]
    assert len(read(api,path)['lots'])==1


def test_freezing_second_project_never_freezes_first_projects_next_draft(engine,editor):
    case,api,path,lot=editor
    assert save(api,path,[lot]).status_code==200
    assert action(api,path,'freeze').status_code==200
    first=read(api,path);assert action(api,path,'new-revision').status_code==200
    changed=read(api,path);changed['lots'][0]['operations'][0]['phases'][0]['original_estimate_minutes']=99
    assert save(api,path,changed['lots']).status_code==200
    with engine.connect() as conn:refs=conn.execute(text('SELECT customer_id,priority_id FROM core.projects WHERE id=:id'),{'id':case.project_id}).one()
    other=mutate(api,'POST','/projects',{'code':'SECOND_PROJECT','name':'Otro proyecto','customer_id':str(refs.customer_id),'priority_id':str(refs.priority_id)}).json()
    other_path=f"/projects/{other['id']}/product-definition"
    assert save(api,other_path,[lot]).status_code==200
    response=action(api,other_path,'freeze');assert response.status_code==200,response.text
    with engine.connect() as conn:
        snapshot=conn.scalar(text('SELECT canonical_snapshot FROM production.product_definition_revisions WHERE id=:id'),{'id':UUID(response.json()['revisions'][0]['id'])})
    project=next(p for p in snapshot['projects'] if p['code']=='P-NEW')
    assert project['lots'][0]['operations'][0]['phases'][0]['original_estimate_minutes']==30

def test_execution_cannot_consume_an_unfrozen_draft(engine,editor):
    from production_besten.application.execution_services import StartOperationService
    from production_besten.domain.execution import StartOperation
    from production_besten.domain.errors import InvalidExecutionState
    from production_besten.persistence.execution_uow import PostgresExecutionUnitOfWorkFactory
    case,api,path,lot=editor
    assert save(api,path,[lot]).status_code==200
    data=read(api,path);op=data['lots'][0]['operations'][0];phase=op['phases'][0]
    svc=StartOperationService(PostgresExecutionUnitOfWorkFactory(engine))
    command=StartOperation(case.organization_id,UUID(op['id']),UUID(phase['id']),case.cutoff_at,case.actor_id,uuid4())
    with pytest.raises(InvalidExecutionState,match='borrador pendiente'):svc.execute(command)
    assert action(api,path,'freeze').status_code==200
    result=svc.execute(command);assert result.operation_execution_id
    # Existing recorded execution prevents rewriting normalized demand.
    assert action(api,path,'new-revision').status_code==409
    assert read(api,path)['status']=='frozen'

def test_inactive_skill_remains_readable_in_frozen_revision(engine,editor):
    case,api,path,lot=editor
    assert save(api,path,[lot]).status_code==200
    assert action(api,path,'freeze').status_code==200
    before=read(api,path)
    with engine.begin() as conn:conn.execute(text("UPDATE capacity.skills SET status='inactive' WHERE id=:id"),{'id':case.skill_id})
    after=read(api,path)
    assert after['status']=='frozen' and not after['errors']
    assert after['revisions'][0]['snapshot']==before['revisions'][0]['snapshot']
    assert action(api,path,'new-revision').status_code==200
    assert read(api,path)['errors']
    assert save(api,path,read(api,path)['lots']).status_code==409
