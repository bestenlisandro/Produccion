from copy import deepcopy
from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy import text

from tests.integration.test_project_intake import intake
from tests.integration.test_product_editor import editor, save, action, read
from tests.integration.test_production_release import command, readiness, simulate_raw
from tests.integration.test_material_arrival import stages
from tests.integration.scheduling_helpers import HORIZON_START


def test_current_v1_reads_ready_simulation_from_revision5_with_parallel_branches(engine, editor, caplog):
    case, api, path, lot = editor
    stages(engine, case)
    with engine.begin() as c:
        c.execute(text("INSERT INTO production.operation_definitions(organization_id,code,name,category,display_order) VALUES (:org,'INSTALACION','Instalación','production_stage',9)"), {'org':case.organization_id})
    definitions = {o['code']: o['id'] for o in api.get('/product-definition/options').json()['operations']}
    names = [('CUT', 'Corte Fondos', 'CORTE_ESCUADRADORA'),
             ('MUL', 'Multiple', 'PERFORADORA_MULTIPLE'),
             ('ARM', 'Armado', 'ARMADO'), ('INST', 'Instalacion', 'INSTALACION')]
    base = lot['operations'][0]
    lot['route_version_id'] = None
    lot['operations'] = []
    for i, (code, name, stage) in enumerate(names):
        op = deepcopy(base)
        op.update(code=code, name=name, operation_definition_id=definitions[stage],
                  predecessor_codes=[names[i-1][0]] if i else [])
        lot['operations'].append(op)
    # Fixture-only arrangement: the existing published plan is CURRENT V1.
    with engine.begin() as c:
        c.execute(text('UPDATE production.product_definition_revisions SET revision_no=3 WHERE id=:id'), {'id':case.definition_revision_id})
    assert save(api, path, [lot]).status_code == 200
    frozen4 = action(api, path, 'freeze').json()
    assert frozen4['revisions'][0]['revision_no'] == 4
    assert command(api, path, 'release').status_code == 200
    previous = simulate_raw(engine, case, [UUID(frozen4['project_id'])])
    rev4 = UUID(frozen4['revisions'][0]['id'])
    with engine.begin() as c:
        c.execute(text('UPDATE planning.plan_versions SET schedule_solution_id=:solution,product_definition_revision_id=:revision,source_scenario_id=:scenario WHERE id=:id'),
                  dict(solution=previous.solution_id, revision=rev4, scenario=previous.scenario_id, id=case.plan_version_id))
    assert action(api, path, 'new-revision').status_code == 200
    lots = read(api, path)['lots']
    lot = lots[0]
    lot['material_arrival'] = dict(route_code='MATERIAL_ROUTE_1', materials=['18','03'], optional_process_codes=[])
    ops = {o['code']:o for o in lot['operations']}
    ops['CUT'].update(name='Corte Fondos 3 mm', predecessor_codes=[])
    ops['MUL'].update(name='Procesado Múltiple 18 mm', predecessor_codes=[])
    ops['ARM']['predecessor_codes'] = ['CUT','MUL']
    assert save(api, path, lots).status_code == 200
    frozen5 = action(api, path, 'freeze').json()
    assert frozen5['revisions'][0]['revision_no'] == 5
    assert frozen5['revisions'][0]['snapshot']['lots'][0]['material_arrival']['route_code'] == 'MATERIAL_ROUTE_1'
    assert command(api, path, 'release').status_code == 200
    ready = readiness(api, path)
    response = command(api, path, 'simulations', dict(expected_row_version=ready['row_version'], evaluation_token=ready['evaluation_token'], reason='New revision review', horizon_start=(HORIZON_START+timedelta(days=1)).isoformat(), horizon_end=(HORIZON_START+timedelta(days=7)).isoformat()))
    assert response.status_code == 200, response.text
    scenario = response.json()['scenario_id']
    assert response.json()['complete']
    with engine.connect() as c:
        before = c.execute(text('SELECT to_jsonb(v) FROM planning.plan_versions v WHERE id=:id'), {'id':case.plan_version_id}).scalar_one()
        assert c.scalar(text('SELECT scenario_kind::text FROM planning.scenarios WHERE id=:id'), {'id':UUID(scenario)}) == 'simulation'
    result = api.get('/planning/current/gantt', params={'from':HORIZON_START.isoformat(), 'to':(HORIZON_START+timedelta(days=7)).isoformat(), 'group_by':'project', 'scenario_id':scenario})
    assert result.status_code == 200, result.text
    data = result.json()
    assert data['plan_version_number'] == 1
    assert data['scenario']['scenario_kind'] == 'simulation'
    assert data['scenario']['status'] == 'ready' and not data['scenario']['stale']
    assert len(data['scenario']['operations']) == 4 and data['scenario']['changed_operations'] == 4
    assert scenario in [o['id'] for o in data['available_scenarios']]
    rows = {o['operation_code']:o for o in data['operations']}
    assert rows['CUT']['operation_name'] == 'Corte Fondos 3 mm'
    assert rows['MUL']['operation_name'] == 'Procesado Múltiple 18 mm'
    assert {p['id'] for p in rows['ARM']['predecessors']} == {rows['CUT']['operation_id'],rows['MUL']['operation_id']}
    assert not rows['CUT']['predecessors'] and not rows['MUL']['predecessors']
    with engine.connect() as c:
        assert c.scalar(text('SELECT to_jsonb(v) FROM planning.plan_versions v WHERE id=:id'), {'id':case.plan_version_id}) == before
        assert c.scalar(text('SELECT status::text FROM planning.scenarios WHERE id=:id'), {'id':UUID(scenario)}) == 'ready'
    missing = api.get('/planning/current/gantt', params={'from':HORIZON_START.isoformat(), 'to':(HORIZON_START+timedelta(days=7)).isoformat(), 'scenario_id':str(uuid4())})
    assert missing.status_code == 404
    assert missing.json()['error']['code'] == 'RESOURCE_NOT_FOUND'
    assert missing.headers['X-Request-Id'] == missing.json()['error']['request_id']
    assert missing.headers['X-Request-Id'] in caplog.text
    assert 'code=RESOURCE_NOT_FOUND' in caplog.text
