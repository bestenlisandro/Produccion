from datetime import datetime,timezone
from uuid import uuid4
import pytest
from sqlalchemy import text
from tests.integration.test_product_editor import editor,save,action
from tests.integration.test_project_intake import intake,mutate
from tests.integration.test_production_release import command,readiness
from tests.integration.scheduling_helpers import add_employee


@pytest.fixture
def local_pilot(engine,editor):
    case,api,path,lot=editor
    with engine.begin() as conn:
        p={'org':case.organization_id,'plant':case.plant_id,'cal':case.calendar_id,'employee':case.employee_id,'skill':case.skill_id}
        conn.execute(text("UPDATE core.plants SET timezone='America/Argentina/Cordoba',current_plan_version_id=NULL WHERE id=:plant"),p)
        conn.execute(text("UPDATE capacity.calendars SET timezone='America/Argentina/Cordoba' WHERE id=:cal"),p)
        conn.execute(text("UPDATE planning.plan_versions SET status='superseded',valid_during=tstzrange(lower(valid_during),now(),'[)') WHERE organization_id=:org"),p)
        conn.execute(text('DELETE FROM capacity.calendar_working_intervals WHERE calendar_id=:cal'),p)
        for weekday in range(1,6):
            for start,end in [('08:00','12:00'),('12:45','17:00')]:
                conn.execute(text("INSERT INTO capacity.calendar_working_intervals(organization_id,calendar_id,weekday,local_start,local_end,valid_during) VALUES (:org,:cal,:day,CAST(:start AS time),CAST(:end AS time),daterange('2026-10-26',NULL,'[)'))"),p|{'day':weekday,'start':start,'end':end})
        conn.execute(text("UPDATE capacity.employees SET code='MARIANO',display_name='Mariano' WHERE id=:employee"),p)
        add_employee(conn,case,'Emiliano',skill_id=case.skill_id)
        add_employee(conn,case,'Gonzalo',skill_id=case.skill_id)
        conn.execute(text("UPDATE capacity.employee_skills SET valid_during=daterange('2026-10-26',NULL,'[)') WHERE organization_id=:org"),p)
        conn.execute(text("UPDATE capacity.skills SET name='Corte / Escuadradora' WHERE id=:skill"),p)
        conn.execute(text("UPDATE core.projects SET code='A685',name='Alacenas' WHERE id=:id"),{'id':path.split('/')[2]})
    lot['name']='Alacenas';lot['route_version_id']=None
    lot['operations'][0]['name']='Corte'
    lot['operations'][0]['phases'][0]['labor_requirements'][0].update(min_people=2,max_people=2,work_minutes=60)
    assert save(api,path,[lot]).status_code==200
    assert action(api,path,'freeze').status_code==200
    assert command(api,path,'release').status_code==200
    clock={'now':datetime(2026,10,25,15,tzinfo=timezone.utc)}
    api.app.state.container.clock=lambda:clock['now']
    prepared=readiness(api,path)
    body={'expected_row_version':prepared['row_version'],'evaluation_token':prepared['evaluation_token'],'reason':'A685 local horizon regression','horizon_start':'2026-10-26','horizon_end':'2026-11-03'}
    return case,api,path,clock,body


@pytest.mark.parametrize('now,expected',[
    ('2026-10-25T15:00:00+00:00','2026-10-26T11:00:00+00:00'),
    ('2026-10-26T18:00:00+00:00','2026-10-26T18:00:00+00:00'),
    ('2026-10-26T15:15:00+00:00','2026-10-26T15:45:00+00:00'),
    ('2026-10-26T21:00:00+00:00','2026-10-27T11:00:00+00:00'),
])
def test_a685_local_skills_today_future_lunch_and_next_workday(engine,local_pilot,now,expected):
    case,api,path,clock,body=local_pilot
    clock['now']=datetime.fromisoformat(now)
    response=command(api,path,'simulations',body)
    assert response.status_code==200,response.text
    result=response.json()
    assert result['complete'] and result['planned_phases']==1 and result['blocked_phases']==0
    with engine.connect() as conn:
        row=conn.execute(text('SELECT input_snapshot,horizon_range FROM planning.schedule_solutions WHERE id=:id'),{'id':result['solution_id']}).one()
        people=row.input_snapshot['capacity_and_state']['employees']
        assert {p['code'] for p in people}=={'MARIANO','Emiliano','Gonzalo'}
        assert all(str(case.skill_id) in p['skills'] for p in people)
        assert row.horizon_range.lower>=clock['now']
        if now.startswith('2026-10-25'):assert row.horizon_range.lower==datetime(2026,10,26,3,tzinfo=timezone.utc)
        start=conn.scalar(text('SELECT min(planned_start_at) FROM planning.operation_plan_results WHERE schedule_solution_id=:id'),{'id':result['solution_id']})
        assert start==datetime.fromisoformat(expected)
        assert conn.scalar(text('SELECT current_plan_version_id FROM core.plants WHERE id=:plant'),{'plant':case.plant_id}) is None
    visible=api.get('/planning/current/gantt',params={'from':'2026-10-26T03:00:00Z','to':'2026-11-02T03:00:00Z','scenario_id':result['scenario_id']})
    assert visible.status_code==200 and visible.json()['scenario']['complete']


def test_retry_clock_change_does_not_duplicate_but_explicit_new_key_can(engine,local_pilot):
    case,api,path,clock,body=local_pilot
    key=uuid4()
    first=command(api,path,'simulations',body,key)
    assert first.status_code==200,first.text
    clock['now']=datetime(2026,10,26,18,tzinfo=timezone.utc)
    retry=command(api,path,'simulations',body,key)
    assert retry.status_code==200 and retry.json()['idempotent_replay']
    assert retry.json()['scenario_id']==first.json()['scenario_id']
    another=command(api,path,'simulations',body,uuid4())
    assert another.status_code==200 and another.json()['scenario_id']!=first.json()['scenario_id']
    changed=command(api,path,'simulations',body|{'horizon_start':'2026-10-27'},key)
    assert changed.status_code==409
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM planning.scenarios WHERE organization_id=:org AND scenario_kind='initial' AND status='ready'"),{'org':case.organization_id})==2
        assert conn.scalar(text('SELECT current_plan_version_id FROM core.plants WHERE id=:id'),{'id':case.plant_id}) is None
