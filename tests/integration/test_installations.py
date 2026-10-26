from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import UUID, uuid4
from time import perf_counter
import pytest
from sqlalchemy import text, event
from fastapi.testclient import TestClient
from production_besten.api.app import create_app
from tests.integration.test_project_intake import intake, mutate
from tests.integration.test_product_editor import editor, save, action, read
from tests.integration.test_production_release import command, simulate_raw

FIELDS=('installation_site_name','installation_address','installation_locality','installation_contact_name','installation_contact_phone','installation_access_notes')
SITE=dict(zip(FIELDS,('Obra principal','Calle de prueba 123','Localidad de prueba','Contacto obra','555-0100','Portón lateral')))


def location(api,path,body=None,key=None):
    pid=path.split('/')[2]
    project=api.get('/projects/'+pid).json()
    return mutate(api,'PATCH',f'/projects/{pid}/installation-location',body or SITE|{'expected_row_version':project['row_version']},key)


def overview(api,path):
    r=api.get(path.replace('product-definition','installations'))
    assert r.status_code==200,r.text
    return r.json()


@pytest.fixture
def installation(editor):
    case,api,path,lot=editor
    second=deepcopy(lot['operations'][0]);second.update(code='INSTALL',name='Instalación',operation_kind='installation',predecessor_codes=['CUT'])
    second['phases'][0]['original_estimate_minutes']=780
    second['phases'][0]['labor_requirements'][0]['work_minutes']=780
    lot['operations'].append(second)
    assert save(api,path,[lot]).status_code==200
    assert action(api,path,'freeze').status_code==200
    assert location(api,path).status_code==200
    assert command(api,path,'release').status_code==200
    return case,api,path,lot


def test_location_empty_for_historical_and_no_installation(editor):
    case,api,path,_=editor
    p=api.get('/projects/'+str(case.project_id)).json()
    assert all(p[k] is None for k in FIELDS)
    assert not overview(api,path)['required']


@pytest.mark.parametrize('field',FIELDS)
def test_structured_location_roundtrip(editor,field):
    _,api,path,_=editor
    r=location(api,path)
    assert r.status_code==200,r.text
    assert r.json()['project'][field]==SITE[field]
    assert overview(api,path)[field]==SITE[field]


@pytest.mark.parametrize('field',['installation_address','installation_locality'])
def test_location_gate(installation,field):
    case,api,path,_=installation
    assert location(api,path,SITE|{field:'  ','expected_row_version':overview(api,path)['row_version']}).status_code==200
    item=overview(api,path)['installations'][0]
    assert not item['ready_to_schedule'] and not item['ready_to_start']
    result=simulate_raw(engine_for(api),case,(UUID(overview(api,path)['project_id']),))
    assert result.blocked_phases>=1


def engine_for(api):return api.app.state.container.engine


def test_location_does_not_mutate_customer(installation):
    _,api,path,_=installation
    p=api.get('/projects/'+path.split('/')[2]).json()
    assert p['customer_phone']!=SITE['installation_contact_phone']
    assert p['installation_contact_phone']==SITE['installation_contact_phone']


def test_location_idempotency_and_conflict(editor):
    _,api,path,_=editor
    body=SITE|{'expected_row_version':overview(api,path)['row_version']};key=uuid4()
    first=location(api,path,body,key);second=location(api,path,body,key)
    assert first.status_code==second.status_code==200
    assert second.json()['idempotent_replay']
    assert location(api,path,body|{'installation_address':'Otra'},key).status_code==409
    assert location(api,path,body).status_code==409


def test_location_concurrent(editor):
    _,api,path,_=editor
    body=SITE|{'expected_row_version':overview(api,path)['row_version']}
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:location(api,path,body),range(2)))
    assert sorted(r.status_code for r in results)==[200,409]


@pytest.mark.parametrize('scope',['tenant','plant'])
@pytest.mark.parametrize('endpoint',['installations','installation-location','complete'])
def test_isolation(installation,scope,endpoint):
    case,api,path,_=installation
    api.headers['X-Dev-Organization-Id' if scope=='tenant' else 'X-Dev-Plant-Id']=str(case.other_organization_id if scope=='tenant' else uuid4())
    url=path.replace('product-definition',endpoint)
    r=api.get(url) if endpoint=='installations' else mutate(api,'PATCH' if endpoint=='installation-location' else 'POST',url,{'expected_row_version':1})
    assert r.status_code==404,r.text


def test_location_rollback(editor):
    _,api,path,_=editor
    broken=TestClient(create_app(engine=engine_for(api),failpoints={'project_intake':'after_intake'}),raise_server_exceptions=False);broken.headers.update(api.headers)
    r=location(broken,path);assert r.status_code==500,r.text
    assert overview(api,path)['installation_address'] is None


@pytest.mark.parametrize('minutes',[60,390,780])
def test_same_scheduler_installation_multiday(installation,minutes):
    case,api,path,lot=installation
    if minutes!=780:
        assert action(api,path,'new-revision').status_code==200
        data=read(api,path)['lots'];ph=data[0]['operations'][1]['phases'][0];ph['original_estimate_minutes']=minutes;ph['labor_requirements'][0]['work_minutes']=minutes
        assert save(api,path,data).status_code==200
        assert action(api,path,'freeze').status_code==200
        assert command(api,path,'release').status_code==200
    result=simulate_raw(engine_for(api),case,(UUID(overview(api,path)['project_id']),))
    assert result.planned_phases==2
    with engine_for(api).connect() as conn:
        rows=conn.execute(text("SELECT h.employee_id,h.time_range,o.code FROM planning.human_segment_assignments h JOIN planning.assignment_segments s ON s.id=h.assignment_segment_id JOIN planning.planned_phase_assignments a ON a.id=s.planned_phase_assignment_id JOIN planning.phase_plan_results p ON p.id=a.phase_plan_result_id JOIN production.required_operation_phases ph ON ph.id=p.required_operation_phase_id JOIN production.required_operations o ON o.id=ph.required_operation_id WHERE h.schedule_solution_id=:id ORDER BY lower(h.time_range)"),{'id':result.solution_id}).all()
    assert sum(int((r.time_range.upper-r.time_range.lower).total_seconds()/60) for r in rows if r.code=='INSTALL')==minutes
    if minutes==780:assert len([r for r in rows if r.code=='INSTALL'])>1
    assert all(not (a.employee_id==b.employee_id and a.time_range.lower<b.time_range.upper and b.time_range.lower<a.time_range.upper) for i,a in enumerate(rows) for b in rows[i+1:])


def test_start_before_production_rejected(installation):
    _,api,path,_=installation
    item=overview(api,path)['installations'][0]
    from production_besten.application.execution_services import StartOperationService
    from production_besten.domain.execution import StartOperation
    from production_besten.persistence.execution_uow import PostgresExecutionUnitOfWorkFactory
    from production_besten.domain.errors import InvalidExecutionState
    from tests.integration.scheduling_helpers import HORIZON_START
    case=installation[0]
    with pytest.raises(InvalidExecutionState):
        StartOperationService(PostgresExecutionUnitOfWorkFactory(engine_for(api))).execute(StartOperation(case.organization_id,UUID(item['operation_id']),UUID(item['phase_id']),HORIZON_START,case.actor_id,uuid4()))


def test_cannot_close_pending_installation(installation):
    _,api,path,_=installation
    r=mutate(api,'POST',path.replace('product-definition','complete'),{'expected_row_version':overview(api,path)['row_version']})
    assert r.status_code==409,r.text


@pytest.mark.parametrize('bad',[{'installation_address':'a'*501},{'installation_locality':'a'*201},{'unexpected':'value'}])
def test_location_validation(editor,bad):
    _,api,path,_=editor
    assert location(api,path,bad|{'expected_row_version':overview(api,path)['row_version']}).status_code==422


from tests.integration.scheduling_helpers import HORIZON_START


def plan_accept(api,path):
    r=mutate(api,'POST',path.replace('product-definition','installation-plan'),{'cutoff_at':HORIZON_START.isoformat(),'horizon_end':(HORIZON_START+timedelta(days=10)).isoformat(),'reason':'Planificar con instalación'})
    assert r.status_code==200,r.text
    scenario=api.get('/scenarios/'+r.json()['scenario_id']).json()
    accepted=mutate(api,'POST','/scenarios/'+scenario['id']+'/accept',{'expected_promotion_lock_version':scenario['promotion_lock_version'],'reason':'Aceptar instalación'})
    assert accepted.status_code in (200,201),accepted.text
    return accepted.json()


def start_and_finish(api,op,at):
    r=mutate(api,'POST',f"/operations/{op['id']}/start",{'phase_id':op['phases'][0]['id'],'started_at':at.isoformat()})
    assert r.status_code in (200,201),r.text
    r=mutate(api,'POST',f"/operations/{op['id']}/finish",{'phase_id':op['phases'][0]['id'],'completed_at':(at+timedelta(minutes=30)).isoformat()})
    assert r.status_code==200,r.text


def test_full_postgres_chain_with_delay_and_close(installation):
    case,api,path,_=installation;engine=engine_for(api)
    before=case.plan_version_id
    assert action(api,path,'new-revision').status_code==200
    lots=read(api,path)['lots'];ph=lots[0]['operations'][1]['phases'][0]
    ph['original_estimate_minutes']=600;ph['labor_requirements'][0]['work_minutes']=600
    assert save(api,path,lots).status_code==200
    assert action(api,path,'freeze').status_code==200
    assert command(api,path,'release').status_code==200
    published=plan_accept(api,path)
    assert published['plan_version_id']!=str(before)
    day=api.get('/planning/current/day',params={'date':HORIZON_START.date().isoformat()})
    assert day.status_code==200 and any(o['operation_name']=='Instalación' for o in day.json()['operations']),day.text
    gantt=api.get('/planning/current/gantt',params={'from':HORIZON_START.isoformat(),'to':(HORIZON_START+timedelta(days=10)).isoformat(),'group_by':'person'})
    assert gantt.status_code==200 and any(o['operation_name']=='Instalación' for o in gantt.json()['operations']),gantt.text
    ops=read(api,path)['lots'][0]['operations'];production,install=ops
    start_and_finish(api,production,HORIZON_START)
    item=overview(api,path)['installations'][0];assert item['ready_to_start']
    assert len(item['scheduled_dates'])>=2
    start_body={'phase_id':install['phases'][0]['id'],'started_at':(HORIZON_START+timedelta(minutes=30)).isoformat()};key=uuid4()
    first=mutate(api,'POST',f"/operations/{install['id']}/start",start_body,key);assert first.status_code==201,first.text
    assert mutate(api,'POST',f"/operations/{install['id']}/start",start_body,key).json()['idempotent_replay']
    assert mutate(api,'POST',f"/operations/{install['id']}/start",start_body).status_code==409
    execution=first.json()['execution_id'];end=HORIZON_START+timedelta(hours=6,minutes=30)
    segment={'phase_id':install['phases'][0]['id'],'started_at':start_body['started_at'],'ended_at':end.isoformat(),'work_minutes':360,'humans':[{'employee_id':str(case.employee_id),'work_minutes':360}],'physical_usages':[{'physical_resource_id':str(case.physical_resource_id),'work_minutes':360}]};key=uuid4()
    r=mutate(api,'POST',f'/executions/{execution}/segments',segment,key);assert r.status_code==201,r.text
    assert mutate(api,'POST',f'/executions/{execution}/segments',segment,key).json()['idempotent_replay']
    item=overview(api,path)['installations'][0];assert item['executed_minutes']==360 and item['state']=='running'
    body={'expected_revision_no':item['remaining_revision_no'],'cutoff_at':end.isoformat(),'reason':'Demora real','remaining':[{'dimension':'LABOR_WORK','phase_id':install['phases'][0]['id'],'minutes':360}]};key=uuid4()
    url=f"/installations/{install['id']}/remaining-estimate"
    first=mutate(api,'POST',url,body,key);assert first.status_code==200,first.text
    assert first.json()['original_labor_minutes']==600
    assert first.json()['updated_total_labor_minutes']==720
    assert mutate(api,'POST',url,body,key).json()['idempotent_replay']
    assert mutate(api,'POST',url,body).status_code==409
    with engine.connect() as conn:current=conn.scalar(text('SELECT current_plan_version_id FROM core.plants WHERE id=:id'),{'id':case.plant_id})
    r=mutate(api,'POST',f"/operations/{install['id']}/replan",{'cutoff_at':end.isoformat(),'horizon_end':(end+timedelta(days=10)).isoformat(),'reason':'Demora instalación'})
    assert r.status_code==201,r.text
    with engine.connect() as conn:
        assert conn.scalar(text('SELECT current_plan_version_id FROM core.plants WHERE id=:id'),{'id':case.plant_id})==current
        assert conn.scalar(text('SELECT count(*) FROM execution.execution_segments WHERE operation_execution_id=:id'),{'id':UUID(execution)})==1
    scenario=api.get('/scenarios/'+r.json()['scenario_id']).json()
    accepted=mutate(api,'POST',f"/scenarios/{scenario['id']}/accept",{'expected_promotion_lock_version':scenario['promotion_lock_version']})
    assert accepted.status_code==201,accepted.text
    finish={'phase_id':install['phases'][0]['id'],'completed_at':(end+timedelta(days=1)).isoformat()};key=uuid4()
    assert mutate(api,'POST',f"/operations/{install['id']}/finish",finish,key).status_code==200
    assert mutate(api,'POST',f"/operations/{install['id']}/finish",finish,key).json()['idempotent_replay']
    assert mutate(api,'POST',f"/operations/{install['id']}/finish",finish).status_code==409
    p=overview(api,path);assert p['can_complete']
    key=uuid4();body={'expected_row_version':p['row_version']}
    assert mutate(api,'POST',path.replace('product-definition','complete'),body,key).status_code==200
    assert mutate(api,'POST',path.replace('product-definition','complete'),body,key).json()['idempotent_replay']
    final=overview(api,path)
    assert final['completed']
    assert not final['installations'][0]['blockers']
    assert not final['installations'][0]['ready_to_schedule']


def test_project_without_installation_completes(editor):
    case,api,path,lot=editor
    assert save(api,path,[lot]).status_code==200
    assert action(api,path,'freeze').status_code==200
    assert command(api,path,'release').status_code==200
    plan_accept(api,path)
    start_and_finish(api,read(api,path)['lots'][0]['operations'][0],HORIZON_START)
    p=overview(api,path);assert not p['required'] and p['can_complete']
    assert mutate(api,'POST',path.replace('product-definition','complete'),{'expected_row_version':p['row_version']}).status_code==200


@pytest.mark.parametrize('team',[1,2,3,6])
def test_installation_team_size(installation,team):
    case,api,path,_=installation;engine=engine_for(api)
    if team>1:
        with engine.begin() as conn:
            for n in range(team-1):
                employee=uuid4()
                conn.execute(text("INSERT INTO capacity.employees(id,organization_id,plant_id,code,display_name,base_calendar_id) VALUES (:id,:org,:plant,:code,'Instalador fixture',:cal)"),{'id':employee,'org':case.organization_id,'plant':case.plant_id,'code':'INSTALL-'+employee.hex,'cal':case.calendar_id})
                conn.execute(text("INSERT INTO capacity.employee_skills(organization_id,employee_id,skill_id,valid_during,enabled) VALUES (:org,:id,:skill,daterange('2026-01-01','2027-01-01','[)'),true)"),{'org':case.organization_id,'id':employee,'skill':case.skill_id})
        assert action(api,path,'new-revision').status_code==200
        lots=read(api,path)['lots'];req=lots[0]['operations'][1]['phases'][0]['labor_requirements'][0];req.update(min_people=team,max_people=team,work_minutes=780*team)
        assert save(api,path,lots).status_code==200
        assert action(api,path,'freeze').status_code==200
        assert command(api,path,'release').status_code==200
    result=simulate_raw(engine,case,(UUID(overview(api,path)['project_id']),))
    with engine.connect() as conn:
        counts=conn.execute(text("SELECT count(DISTINCT h.employee_id) FROM planning.human_segment_assignments h JOIN planning.assignment_segments s ON s.id=h.assignment_segment_id JOIN planning.planned_phase_assignments a ON a.id=s.planned_phase_assignment_id JOIN planning.phase_plan_results p ON p.id=a.phase_plan_result_id JOIN production.required_operation_phases ph ON ph.id=p.required_operation_phase_id JOIN production.required_operations o ON o.id=ph.required_operation_id WHERE h.schedule_solution_id=:id AND o.code='INSTALL' GROUP BY s.id"),{'id':result.solution_id}).scalars().all()
    assert counts and all(n==team for n in counts)


def test_five_person_installation_requires_five_real_eligible_people(installation):
    case,api,path,_=installation
    engine=engine_for(api)

    def add_people(count):
        with engine.begin() as conn:
            for _ in range(count):
                employee=uuid4()
                conn.execute(text("INSERT INTO capacity.employees(id,organization_id,plant_id,code,display_name,base_calendar_id) VALUES (:id,:org,:plant,:code,'Disposable installer',:cal)"),{'id':employee,'org':case.organization_id,'plant':case.plant_id,'code':'INSTALL-'+employee.hex,'cal':case.calendar_id})
                conn.execute(text("INSERT INTO capacity.employee_skills(organization_id,employee_id,skill_id,valid_during,enabled) VALUES (:org,:id,:skill,daterange('2026-01-01','2027-01-01','[)'),true)"),{'org':case.organization_id,'id':employee,'skill':case.skill_id})

    add_people(2)
    assert action(api,path,'new-revision').status_code==200
    lots=read(api,path)['lots']
    req=lots[0]['operations'][1]['phases'][0]['labor_requirements'][0]
    req.update(min_people=5,max_people=5,work_minutes=780*5)
    assert save(api,path,lots).status_code==200
    assert action(api,path,'freeze').status_code==200
    assert command(api,path,'release').status_code==200
    assert overview(api,path)['installations'][0]['required_people']==5
    assert overview(api,path)['installations'][0]['ready_to_schedule']
    blocked=simulate_raw(engine,case,(UUID(overview(api,path)['project_id']),))
    assert not blocked.complete and blocked.blocked_phases>=1
    with engine.connect() as conn:
        assert conn.scalar(text('SELECT count(*) FROM capacity.employees WHERE organization_id=:org'),{'org':case.organization_id})==3
        assert conn.scalar(text("SELECT count(*) FROM planning.human_segment_assignments h JOIN planning.assignment_segments s ON s.id=h.assignment_segment_id JOIN planning.planned_phase_assignments a ON a.id=s.planned_phase_assignment_id JOIN planning.phase_plan_results p ON p.id=a.phase_plan_result_id JOIN production.required_operation_phases ph ON ph.id=p.required_operation_phase_id JOIN production.required_operations o ON o.id=ph.required_operation_id WHERE h.schedule_solution_id=:id AND o.code='INSTALL'"),{'id':blocked.solution_id})==0
    assert read(api,path)['lots'][0]['operations'][1]['phases'][0]['labor_requirements'][0]['min_people']==5

    add_people(2)
    feasible=simulate_raw(engine,case,(UUID(overview(api,path)['project_id']),))
    assert feasible.complete and feasible.planned_phases==2
    with engine.connect() as conn:
        counts=conn.execute(text("SELECT count(DISTINCT h.employee_id) FROM planning.human_segment_assignments h JOIN planning.assignment_segments s ON s.id=h.assignment_segment_id JOIN planning.planned_phase_assignments a ON a.id=s.planned_phase_assignment_id JOIN planning.phase_plan_results p ON p.id=a.phase_plan_result_id JOIN production.required_operation_phases ph ON ph.id=p.required_operation_phase_id JOIN production.required_operations o ON o.id=ph.required_operation_id WHERE h.schedule_solution_id=:id AND o.code='INSTALL' GROUP BY s.id"),{'id':feasible.solution_id}).scalars().all()
    assert counts and all(count==5 for count in counts)


@pytest.mark.parametrize('master',['skills','physical_resource_types','work_centers'])
def test_inactive_installation_requirements_block(installation,master):
    case,api,path,_=installation
    identifier={'skills':case.skill_id,'physical_resource_types':case.resource_type_id,'work_centers':case.work_center_id}[master]
    with engine_for(api).begin() as conn:conn.execute(text('UPDATE capacity.'+master+" SET status='inactive' WHERE id=:id"),{'id':identifier})
    assert not overview(api,path)['installations'][0]['ready_to_schedule']


@pytest.mark.parametrize('calendar_action',['remove','replace'])
def test_installation_calendar_exception(installation,calendar_action):
    case,api,path,_=installation
    with engine_for(api).begin() as conn:
        conn.execute(text("INSERT INTO capacity.calendar_exceptions(organization_id,calendar_id,exception_date,effect,time_range,capacity_factor,reason) VALUES (:org,:cal,:day,CAST(:effect AS capacity.calendar_effect),CASE WHEN CAST(:start AS timestamptz) IS NULL THEN NULL ELSE tstzrange(CAST(:start AS timestamptz),CAST(:end AS timestamptz),'[)') END,1,'Test instalación')"),{'org':case.organization_id,'cal':case.calendar_id,'day':HORIZON_START.date(),'effect':calendar_action,'start':None if calendar_action=='remove' else (HORIZON_START+timedelta(hours=2)).isoformat(),'end':None if calendar_action=='remove' else (HORIZON_START+timedelta(hours=4)).isoformat()})
    result=simulate_raw(engine_for(api),case,(UUID(overview(api,path)['project_id']),))
    assert result.planned_phases==2


def test_agenda_benchmark_50_installations(installation):
    case,api,path,_=installation;engine=engine_for(api)
    assert action(api,path,'new-revision').status_code==200
    lots=read(api,path)['lots'];template=lots[0]['operations'][1];lots[0]['operations']=lots[0]['operations'][:1]
    for n in range(50):
        op=deepcopy(template);op.pop('id',None);op['code']='INSTALL-'+str(n)
        for ph in op['phases']:ph.pop('id',None)
        lots[0]['operations'].append(op)
    assert save(api,path,lots).status_code==200
    assert action(api,path,'freeze').status_code==200
    assert command(api,path,'release').status_code==200
    statements=[]
    def count(*args):statements.append(1)
    event.listen(engine,'before_cursor_execute',count)
    try:
        start=perf_counter();r=api.get('/installations');elapsed=(perf_counter()-start)*1000
    finally:event.remove(engine,'before_cursor_execute',count)
    assert r.status_code==200 and len(r.json()[0]['installations'])==50,r.text
    assert len(statements)<30
    print(f'INSTALLATION_AGENDA_BENCHMARK 50 installations: {elapsed:.2f} ms; {len(statements)} queries; {len(r.content)} bytes')


@pytest.mark.parametrize('team',[0,7])
def test_invalid_installation_team_cannot_freeze(editor,team):
    _,api,path,lot=editor
    lot['operations'][0]['operation_kind']='installation'
    lot['operations'][0]['phases'][0]['labor_requirements'][0].update(min_people=team,max_people=team)
    r=save(api,path,[lot]);assert r.status_code in (409,422),r.text


def test_m11_columns_nullable_and_no_defaults(engine):
    with engine.connect() as conn:
        rows=conn.execute(text("SELECT column_name,is_nullable,column_default FROM information_schema.columns WHERE table_schema='core' AND table_name='projects' AND column_name LIKE 'installation_%'")).all()
    assert len(rows)==6 and all(r.is_nullable=='YES' and r.column_default is None for r in rows)


def test_completed_production_does_not_reopen(editor):
    _,api,path,lot=editor
    assert save(api,path,[lot]).status_code==200
    assert action(api,path,'freeze').status_code==200
    assert command(api,path,'release').status_code==200
    plan_accept(api,path)
    op=read(api,path)['lots'][0]['operations'][0];start_and_finish(api,op,HORIZON_START)
    response=mutate(api,'POST',f"/operations/{op['id']}/start",{'phase_id':op['phases'][0]['id'],'started_at':(HORIZON_START+timedelta(days=1)).isoformat()})
    assert response.status_code==409,response.text
