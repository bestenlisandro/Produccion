from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import text

from tests.integration.test_product_editor import editor, read, save, action
from tests.integration.test_project_intake import intake, mutate
from tests.integration.test_production_release import command, readiness
from tests.integration.scheduling_helpers import add_employee, HORIZON_START
from tests.integration.test_standard_stages import seed_stages


@pytest.mark.parametrize('count',[1,2])
@pytest.mark.parametrize('stage',[0,6,7])
def test_author_freeze_clone_unskilled_phase_in_any_new_stage(engine,editor,count,stage):
    case,api,path,lot=editor
    seed_stages(engine,case)
    options=api.get('/product-definition/options').json()
    lot['operations'][0].update(name='Acomodar materiales',operation_definition_id=options['operations'][stage]['id'])
    ph=lot['operations'][0]['phases'][0]
    ph.update(name='Acomodar',required_people=count,labor_requirements=[])
    with engine.connect() as conn:
        skills=conn.execute(text('SELECT id,code,name FROM capacity.skills WHERE organization_id=:org ORDER BY id'),{'org':case.organization_id}).all()
    response=save(api,path,[lot]);assert response.status_code==200,response.text
    assert response.json()['errors']==[]
    reopened=read(api,path)
    phase=reopened['lots'][0]['operations'][0]['phases'][0]
    assert phase['required_people']==count and phase['labor_requirements']==[]
    assert action(api,path,'validate').json()['errors']==[]
    frozen=action(api,path,'freeze');assert frozen.status_code==200,frozen.text
    snapshot=deepcopy(frozen.json()['revisions'][0]['snapshot'])
    assert snapshot['lots'][0]['operations'][0]['phases'][0]['required_people']==count
    assert snapshot['lots'][0]['operations'][0]['phases'][0]['labor_requirements']==[]
    assert action(api,path,'new-revision').status_code==200
    clone=read(api,path)['lots'][0]['operations'][0]['phases'][0]
    assert clone['required_people']==count and clone['labor_requirements']==[]
    with engine.connect() as conn:
        assert conn.scalar(text('SELECT count(*) FROM production.operation_labor_requirements WHERE required_operation_phase_id=:phase'),{'phase':UUID(phase['id'])})==0
        assert conn.execute(text('SELECT id,code,name FROM capacity.skills WHERE organization_id=:org ORDER BY id'),{'org':case.organization_id}).all()==skills
    assert read(api,path)['revisions'][0]['snapshot']==snapshot


@pytest.mark.parametrize('count',[1,2])
def test_generic_people_reach_scheduler_and_old_frozen_demand_is_stable(engine,editor,count):
    case,api,path,lot=editor
    lot['operations'][0]['phases'][0].update(required_people=count,labor_requirements=[],physical_requirements=[])
    with engine.begin() as conn:
        for name in ['Emiliano','Gonzalo']:
            add_employee(conn,case,name,skill_id=case.skill_id)
        inactive=add_employee(conn,case,'Inactivo')
        conn.execute(text("UPDATE capacity.employees SET status='inactive' WHERE id=:id"),{'id':inactive})
        conn.execute(text('DELETE FROM capacity.employee_skills WHERE organization_id=:org'),{'org':case.organization_id})
        conn.execute(text("UPDATE capacity.employees SET code='Mariano',display_name='Mariano' WHERE id=:id"),{'id':case.employee_id})
        conn.execute(text('UPDATE core.plants SET current_plan_version_id=NULL WHERE id=:id'),{'id':case.plant_id})
    assert save(api,path,[lot]).status_code==200
    assert action(api,path,'freeze').status_code==200
    assert command(api,path,'release').status_code==200
    ready=readiness(api,path)
    body={'expected_row_version':ready['row_version'],'evaluation_token':ready['evaluation_token'],'reason':'Disposable generic labor test',
          'horizon_start':HORIZON_START.isoformat(),'horizon_end':(HORIZON_START+timedelta(days=7)).isoformat()}
    simulated=command(api,path,'simulations',body)
    assert simulated.status_code==200 and simulated.json()['complete'],simulated.text
    with engine.connect() as conn:
        inp=conn.scalar(text('SELECT input_snapshot FROM planning.schedule_solutions WHERE id=:id'),{'id':UUID(simulated.json()['solution_id'])})
        phase=inp['capacity_and_state']['phases'][0]
        assert phase['required_people']==count and phase['labor']==[]
        assert all(e['skills']==[] for e in inp['capacity_and_state']['employees'])
        assert {e['code'] for e in inp['capacity_and_state']['employees']}=={'Mariano','Emiliano','Gonzalo'}
        teams=conn.execute(text('SELECT assignment_segment_id,count(DISTINCT employee_id),count(*) FROM planning.human_segment_assignments WHERE schedule_solution_id=:solution GROUP BY assignment_segment_id'),{'solution':UUID(simulated.json()['solution_id'])}).all()
        assert teams and all(distinct==total==count for _,distinct,total in teams)
        assert conn.scalar(text('SELECT current_plan_version_id FROM core.plants WHERE id=:id'),{'id':case.plant_id}) is None
    # Explicitly open a draft only in the disposable fixture, then change the live count.
    assert action(api,path,'new-revision').status_code==200
    draft=read(api,path);draft['lots'][0]['operations'][0]['phases'][0]['required_people']=3
    assert save(api,path,draft['lots']).status_code==200
    from tests.integration.test_production_release import simulate_raw
    run=simulate_raw(engine,case,project_ids=(UUID(draft['project_id']),))
    with engine.connect() as conn:
        value=conn.scalar(text('SELECT input_snapshot FROM planning.schedule_solutions WHERE id=:id'),{'id':run.solution_id})
    assert value['capacity_and_state']['phases'][0]['required_people']==count


def test_add_real_skill_and_remove_last_does_not_store_null_or_magic_skill(engine,editor):
    case,api,path,lot=editor
    ph=lot['operations'][0]['phases'][0];ph['required_people']=1
    assert save(api,path,[lot]).status_code==200
    assert read(api,path)['lots'][0]['operations'][0]['phases'][0]['labor_requirements'][0]['skill_id']==str(case.skill_id)
    draft=read(api,path);phase=draft['lots'][0]['operations'][0]['phases'][0];phase['labor_requirements']=[]
    assert save(api,path,draft['lots']).status_code==200
    assert read(api,path)['lots'][0]['operations'][0]['phases'][0]['labor_requirements']==[]
    with engine.connect() as conn:
        assert conn.scalar(text('SELECT count(*) FROM production.operation_labor_requirements WHERE required_operation_phase_id=:id'),{'id':UUID(phase['id'])})==0


@pytest.mark.parametrize('value',[-1,32768])
def test_invalid_headcount_rejected(editor,value):
    _,api,path,lot=editor;lot['operations'][0]['phases'][0]['required_people']=value
    assert save(api,path,[lot]).status_code==422


def test_installation_without_skill_still_requires_real_team(engine,editor):
    _,api,path,lot=editor
    lot['operations'][0]['operation_kind']='installation'
    ph=lot['operations'][0]['phases'][0];ph.update(required_people=2,labor_requirements=[])
    response=save(api,path,[lot]);assert response.status_code==200 and response.json()['errors']==[],response.text
    assert action(api,path,'freeze').status_code==200
    overview=api.get(path.replace('product-definition','installations'))
    assert overview.status_code==200,overview.text
    assert overview.json()['installations'][0]['required_people']==2
    assert not any('equipo válido' in b for b in overview.json()['installations'][0]['blockers'])


def test_m13_upgrade_down_preserves_legacy_and_guards_new_demand(engine,editor):
    case,_,_,_=editor
    root=Path(__file__).resolve().parents[2]
    with engine.connect() as conn:
        transaction=conn.begin()
        try:
            conn.execute(text('UPDATE production.required_operation_phases SET required_people=0'))
            before=conn.execute(text("SELECT (to_jsonb(p)-'required_people') FROM production.required_operation_phases p WHERE id=:id"),{'id':case.phase_id}).scalar_one()
            for path in ['db/rollback/013_phase_required_people.sql','db/migrations/013_phase_required_people.sql']:
                source=(root/path).read_text(encoding='utf-8').replace('BEGIN;','').replace('COMMIT;','')
                conn.exec_driver_sql(source)
            assert conn.scalar(text('SELECT required_people FROM production.required_operation_phases WHERE id=:id'),{'id':case.phase_id})==0
            assert conn.scalar(text("SELECT (to_jsonb(p)-'required_people') FROM production.required_operation_phases p WHERE id=:id"),{'id':case.phase_id})==before
            conn.execute(text('UPDATE production.required_operation_phases SET required_people=2 WHERE id=:id'),{'id':case.phase_id})
            with pytest.raises(Exception,match='Independent human demand'):
                with conn.begin_nested():
                    conn.exec_driver_sql((root/'db/rollback/013_phase_required_people.sql').read_text(encoding='utf-8').replace('BEGIN;','').replace('COMMIT;',''))
        finally:
            transaction.rollback()
