from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from uuid import UUID, uuid4

from production_besten.api.context import RequestContext
from production_besten.api.dependencies import get_request_context
from tests.integration.test_project_intake import intake, mutate
from tests.integration.test_product_editor import editor, save, action, read
from tests.integration.scheduling_helpers import HORIZON_START


def test_production_execution_detail_commands_history_and_remaining_replay(editor):
    case, api, path, lot = editor
    second = deepcopy(lot['operations'][0]['phases'][0])
    second.update(code='ASSEMBLE', name='Armado')
    lot['operations'][0]['phases'].append(second)
    assert save(api, path, [lot]).status_code == 200
    assert action(api, path, 'freeze').status_code == 200
    op = read(api, path)['lots'][0]['operations'][0]
    url = f"/operations/{op['id']}/execution"
    before = api.get(url)
    assert before.status_code == 200, before.text
    assert before.json()['can_execute'] and not before.json()['segments']
    assert len(before.json()['phases']) == 2
    phase = op['phases'][0]['id']
    start = HORIZON_START
    started = mutate(api, 'POST', f"/operations/{op['id']}/start", {'phase_id': phase, 'started_at': start.isoformat()})
    assert started.status_code == 201, started.text
    execution = started.json()['execution_id']
    end = start + timedelta(minutes=20)
    body = {'phase_id': phase, 'started_at': start.isoformat(), 'ended_at': end.isoformat(), 'work_minutes': 20,
            'humans': [{'employee_id': str(case.employee_id), 'work_minutes': 20}],
            'physical_usages': [{'physical_resource_id': str(case.physical_resource_id), 'work_minutes': 20, 'capacity_units': 1}]}
    key = uuid4()
    segment = mutate(api, 'POST', f'/executions/{execution}/segments', body, key)
    assert segment.status_code == 201, segment.text
    assert mutate(api, 'POST', f'/executions/{execution}/segments', body, key).json()['idempotent_replay']
    detail = api.get(url).json()
    assert len(detail['segments']) == 1
    assert detail['segments'][0]['people'][0]['id'] == str(case.employee_id)
    assert detail['segments'][0]['resources'][0]['id'] == str(case.physical_resource_id)
    assert detail['phases'][0]['started'] and not detail['phases'][1]['started']
    remaining = {'expected_revision_no': detail['remaining_revision_no'], 'cutoff_at': end.isoformat(),
                 'remaining': [{'dimension': 'LABOR_WORK', 'phase_id': phase, 'minutes': 80}], 'reason': 'Demora ficticia'}
    key = uuid4()
    result = mutate(api, 'POST', url+'/remaining-estimate', remaining, key)
    assert result.status_code == 200, result.text
    assert mutate(api, 'POST', url+'/remaining-estimate', remaining, key).json()['idempotent_replay']
    assert mutate(api, 'POST', url+'/remaining-estimate', remaining).status_code == 409
    assert api.get(url).json()['remaining_minutes'] == 80
    early_finish = mutate(api, 'POST', f"/operations/{op['id']}/finish", {'phase_id': phase, 'completed_at': start.isoformat()})
    assert early_finish.status_code == 400
    finished = mutate(api, 'POST', f"/operations/{op['id']}/finish", {'phase_id': phase, 'completed_at': end.isoformat()})
    assert finished.status_code == 200, finished.text
    assert not finished.json()['operation_completed']
    after = api.get(url).json()
    assert after['phases'][0]['completed'] and not after['phases'][1]['completed']
    assert after['segments'] == detail['segments']
    assert mutate(api, 'POST', f'/executions/{execution}/segments', body).status_code == 409
    started = mutate(api, 'POST', f"/operations/{op['id']}/start", {'phase_id': op['phases'][1]['id'], 'started_at': end.isoformat()})
    assert started.status_code == 201, started.text
    assert api.get(url).json()['phases'][1]['started']


def test_read_only_context_and_plant_scope(editor):
    case, api, path, lot = editor
    assert save(api, path, [lot]).status_code == 200
    op = read(api, path)['lots'][0]['operations'][0]
    context = RequestContext(case.actor_id, case.organization_id, case.plant_id)
    api.app.dependency_overrides[get_request_context] = lambda: context
    try:
        detail = api.get(f"/operations/{op['id']}/execution")
        assert detail.status_code == 200, detail.text
        assert not detail.json()['can_execute'] and detail.json()['blockers']
        assert mutate(api, 'POST', f"/operations/{op['id']}/start", {'phase_id': op['phases'][0]['id'], 'started_at': HORIZON_START.isoformat()}).status_code == 403
        context = replace(context, plant_id=uuid4())
        assert api.get(f"/operations/{op['id']}/execution").status_code == 404
    finally:
        api.app.dependency_overrides.pop(get_request_context, None)
