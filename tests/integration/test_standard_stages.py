from copy import deepcopy
import json
from pathlib import Path
from uuid import uuid4

from sqlalchemy import text

from tests.integration.test_product_editor import editor, read, save, action
from tests.integration.test_project_intake import intake, mutate


ROOT = Path(__file__).resolve().parents[2]
BESTEN = 'cc1f3ea8-d31c-4a84-9c2b-0b207ba715f3'


def seed_stages(engine, case):
    source = (ROOT/'db/operations/besten_standard_stages.sql').read_text(encoding='utf-8')
    source = source.replace(BESTEN, str(case.organization_id)).replace('BEGIN;', '').replace('COMMIT;', '')
    with engine.begin() as conn:
        conn.execute(text("UPDATE production.operation_definitions SET code='CORTE_ESCUADRADORA' WHERE id=:id"), {'id':case.operation_definition_id})
        conn.exec_driver_sql(source)


def test_catalog_upgrade_preserves_ids_and_is_idempotent(engine, editor):
    case, api, _, _ = editor
    seed_stages(engine, case)
    options = api.get('/product-definition/options').json()['operations']
    assert [o['display_order'] for o in options] == list(range(1, 10))
    assert options[1]['id'] == str(case.operation_definition_id)
    seed_stages(engine, case)
    assert api.get('/product-definition/options').json()['operations'] == options
    assert options[0]['code'] == 'PREPARACION_PROYECTO'
    assert options[6]['code'] == 'CONTROL_CALIDAD'
    assert options[7]['code'] == 'EMBALAJE'


def test_name_order_identity_requirements_and_parallel_edges(engine, editor):
    case, api, path, lot = editor
    seed_stages(engine, case)
    lot['route_version_id'] = None
    first = lot['operations'][0]; first['name'] = 'Corte de fondos'
    second = deepcopy(first); second.update(code='DRAWERS', name='Corte de cajones')
    lot['operations'].append(second)
    saved = save(api, path, [lot]).json()['lots']
    old = deepcopy(saved[0]['operations'][0])
    saved[0]['operations'].reverse()
    saved[0]['operations'][1]['name'] = 'Corte de fondos y laterales'
    # Contradictory read-only metadata never overrides the definition FK.
    saved[0]['operations'][1]['stage_name'] = 'Armado'
    result = save(api, path, saved); assert result.status_code == 200, result.text
    ops = result.json()['lots'][0]['operations']
    assert [o['code'] for o in ops] == ['DRAWERS', 'CUT']
    assert [o['operation_order'] for o in ops] == [1, 2]
    assert all(o['stage_name'] == 'Corte' and o['stage_order'] == 2 for o in ops)
    assert ops[1]['id'] == old['id']
    assert ops[1]['phases'] == old['phases']
    assert ops[1]['predecessor_codes'] == old['predecessor_codes'] == []
    result = save(api, path, [{**result.json()['lots'][0], 'operations':[ops[1]]}])
    assert result.json()['lots'][0]['operations'][0]['operation_order'] == 1
    assert result.json()['errors'] == []  # The seven unused stages need no operations.
    assert action(api, path, 'freeze').status_code == 200


def test_visual_order_does_not_require_topological_order(engine, editor):
    case, api, path, lot = editor
    seed_stages(engine, case)
    first = lot['operations'][0]
    second = deepcopy(first); second.update(code='NEXT', predecessor_codes=['CUT'])
    lot['operations'] = [second, first]
    response = save(api, path, [lot]); assert response.status_code == 200, response.text
    assert response.json()['lots'][0]['operations'][0]['predecessor_codes'] == ['CUT']


def test_catalog_edit_does_not_relabel_frozen_snapshot(engine, editor):
    case, api, path, lot = editor
    seed_stages(engine, case)
    assert save(api, path, [lot]).status_code == 200
    frozen = action(api, path, 'freeze'); assert frozen.status_code == 200, frozen.text
    before = frozen.json()['revisions']
    stage = next(s for s in api.get('/master-data/snapshot').json()['stages'] if s['id']==str(case.operation_definition_id))
    response = mutate(api, 'PATCH', '/master-data/stages/'+stage['id'], {
        'code':stage['code'], 'name':'Corte actualizado', 'display_order':2,
        'expected_row_version':stage['row_version']})
    assert response.status_code == 200, response.text
    after = read(api, path)
    assert after['status'] == 'frozen' and after['revisions'] == before
    op = before[0]['snapshot']['lots'][0]['operations'][0]
    assert op['stage_name'] == 'Corte' and op['stage_order'] == 2
    assert save(api, path, after['lots']).status_code == 409


def test_catalog_commands_retry_concurrency_and_tenant(editor):
    case, api, _, _ = editor
    key = uuid4(); body={'code':'PREP','name':'Preparación', 'display_order':1}
    created=mutate(api,'POST','/master-data/stages',body,key)
    assert created.status_code == 201, created.text
    assert mutate(api,'POST','/master-data/stages',body,key).json()['idempotent_replay']
    stage=created.json()['entity']; path='/master-data/stages/'+stage['id']
    update=body|{'name':'Preparación técnica','expected_row_version':1}
    assert mutate(api,'PATCH',path,update).status_code == 200
    assert mutate(api,'PATCH',path,update).status_code == 409
    api.headers['X-Dev-Organization-Id']=str(case.other_organization_id)
    assert mutate(api,'PATCH',path,update).status_code == 404


def test_operation_name_required_and_stage_move_preserves_phases(engine, editor):
    case, api, path, lot = editor
    seed_stages(engine, case)
    lot['operations'][0]['name']=' '
    assert save(api,path,[lot]).status_code == 422
    lot['operations'][0]['name']='Armado de cajones'
    stages=api.get('/product-definition/options').json()['operations']
    lot['operations'][0]['operation_definition_id']=stages[5]['id']
    key=uuid4(); version=read(api,path)['row_version']
    response=save(api,path,[lot],version,key); assert response.status_code == 200, response.text
    op=response.json()['lots'][0]['operations'][0]
    assert op['stage_order'] == 6 and op['stage_name'] == 'Armado'
    assert len(op['phases']) == 1 and op['phases'][0]['original_estimate_minutes'] == 30
    # Simulate an audit response written by the pre-M12 API, in this disposable DB.
    historical=response.json()
    for operation in historical['lots'][0]['operations']:
        for field in ('stage_code','stage_name','stage_order','operation_order'):
            operation.pop(field)
    with engine.begin() as conn:
        conn.execute(text('UPDATE audit.audit_entries SET after_data=CAST(:data AS jsonb) WHERE organization_id=:org AND request_id=:key'),
                     {'data':json.dumps(historical),'org':case.organization_id,'key':key})
    replay=save(api,path,[lot],version,key)
    assert replay.status_code == 200 and replay.json()['idempotent_replay'], replay.text
    assert replay.json()['lots'][0]['operations'][0]['id'] == op['id']


def test_m12_down_up_preserves_existing_data(engine, editor):
    case, _, _, _ = editor
    with engine.connect() as conn:
        transaction=conn.begin()
        try:
            before=conn.execute(text('SELECT id,code,name FROM production.operation_definitions ORDER BY id')).all()
            for path in ['db/rollback/012_standard_stage_order.sql','db/migrations/012_standard_stage_order.sql']:
                source=(ROOT/path).read_text(encoding='utf-8').replace('BEGIN;','').replace('COMMIT;','')
                conn.exec_driver_sql(source)
            assert conn.execute(text('SELECT id,code,name FROM production.operation_definitions ORDER BY id')).all()==before
        finally:
            transaction.rollback()


def test_new_stages_schedule_concrete_operations_without_current(engine, editor):
    from datetime import timedelta
    from tests.integration.test_production_release import command, readiness
    from tests.integration.test_initial_simulation_review import gantt, current
    from tests.integration.scheduling_helpers import HORIZON_START

    case, api, path, lot = editor
    seed_stages(engine, case)
    stages = api.get('/product-definition/options').json()['operations']
    original = lot['operations'][0]
    lot['route_version_id'] = None
    lot['operations'] = []
    for index, name in [(0, 'Despiece de alacenas'), (6, 'Control final'), (7, 'Embalaje superior')]:
        op = deepcopy(original)
        op.update(code=f'CONCRETE_{index}', name=name, operation_definition_id=stages[index]['id'])
        lot['operations'].append(op)
    saved = save(api,path,[lot]); assert saved.status_code == 200, saved.text
    ids = {o['id'] for o in saved.json()['lots'][0]['operations']}
    assert action(api,path,'freeze').status_code == 200
    assert command(api,path,'release').status_code == 200
    with engine.begin() as conn:
        conn.execute(text('UPDATE core.plants SET current_plan_version_id=NULL WHERE id=:id'), {'id':case.plant_id})
    prepared = readiness(api,path)
    body = {'expected_row_version':prepared['row_version'], 'evaluation_token':prepared['evaluation_token'],
            'reason':'Standard stages test only', 'horizon_start':HORIZON_START.isoformat(),
            'horizon_end':(HORIZON_START+timedelta(days=7)).isoformat()}
    simulated = command(api,path,'simulations',body)
    assert simulated.status_code == 200 and simulated.json()['complete'], simulated.text
    visible = gantt(api,simulated.json()['scenario_id'])
    assert visible.status_code == 200, visible.text
    operations = visible.json()['operations']
    assert len(operations) == 3
    assert {o['operation_id'] for o in operations} == ids
    assert {o['operation_name'] for o in operations} == {'Despiece de alacenas','Control final','Embalaje superior'}
    assert all(o['duration_minutes'] == 30 and o['people'] and o['resources'] for o in operations)
    assert current(engine,case) is None
