from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from uuid import UUID, uuid4
from sqlalchemy import text

from production_besten.api.context import RequestContext
from production_besten.api.dependencies import get_request_context
from tests.integration.test_project_intake import intake, mutate
from tests.integration.test_product_editor import editor, save, action, read
from tests.integration.scheduling_helpers import HORIZON_START


def test_production_execution_detail_commands_history_and_remaining_replay(editor, engine):
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
    unplanned = api.get(f"/operations/{op['id']}")
    assert unplanned.status_code == 200, unplanned.text
    assert unplanned.json()['planned_start'] is None
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
    finished = mutate(api, 'POST', f"/operations/{op['id']}/finish", {'phase_id': op['phases'][1]['id'], 'completed_at': end.isoformat()})
    assert finished.status_code == 200, finished.text
    summary = api.get(f"/operations/{op['id']}")
    assert summary.status_code == 200, summary.text
    assert summary.json()['operational_status'] == 'FINALIZADO'
    assert summary.json()['executed_minutes'] == 20 and summary.json()['remaining_minutes'] == 0
    assert summary.json()['progress_percent'] == 100
    assert api.get(url).json()['segments'] == detail['segments']
    for grouping in ('person', 'resource', 'center', 'project'):
        gantt = api.get('/planning/current/gantt', params={'from': start.isoformat(), 'to': (start+timedelta(days=1)).isoformat(), 'group_by': grouping})
        assert gantt.status_code == 200, gantt.text
        historical = next(o for o in gantt.json()['operations'] if o['operation_id'] == op['id'])
        assert historical['planned_start'] is None and historical['planned_segments'] == []
        assert historical['operational_status'] == 'FINALIZADO' and historical['remaining_minutes'] == 0
        assert historical['actual_segments'][0]['id'] == segment.json()['segment_id']
        assert historical['people'][0]['id'] == str(case.employee_id)
        assert historical['resources'][0]['id'] == str(case.physical_resource_id)
        assert historical['group_ids']
    # A later published state already incorporates an older remaining estimate.
    assert summary.json()['plan_requires_reconciliation']
    with engine.begin() as conn:
        conn.execute(text('''UPDATE planning.plan_versions pv SET planning_state_revision_id=h.current_revision_id
            FROM planning.planning_state_heads h WHERE pv.organization_id=h.organization_id
              AND pv.plant_id=h.plant_id AND pv.id=:plan'''), {'plan': case.plan_version_id})
    assert not api.get(f"/operations/{op['id']}").json()['plan_requires_reconciliation']


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


def test_warning_tracks_real_execution_estimate_and_publication_cycle(engine, seeded_case, fixed_acceptance_clock):
    from tests.integration.test_replanning import _prepare
    from tests.integration.test_operational_frontend_api import _client, _headers

    case = seeded_case
    value = _prepare(engine, case)
    operation_id = str(value.request.trigger_operation_id)
    client = _client(engine)
    client.app.state.container.clock = fixed_acceptance_clock
    url = f'/operations/{operation_id}'
    headers = _headers(case)

    def needs_review():
        result = client.get(url, headers=headers)
        assert result.status_code == 200, result.text
        return result.json()['plan_requires_reconciliation']

    def publish(cutoff):
        proposal = client.post(url+'/replan', headers=_headers(case, key=True), json={
            'cutoff_at': cutoff.isoformat(), 'horizon_end': (cutoff+timedelta(days=7)).isoformat(),
            'reason': 'Disposable reconciliation lifecycle',
        })
        assert proposal.status_code == 201, proposal.text
        scenario_id = proposal.json()['scenario_id']
        scenario = client.get(f'/scenarios/{scenario_id}', headers=headers).json()
        accepted = client.post(f'/scenarios/{scenario_id}/accept', headers=_headers(case, key=True), json={
            'expected_promotion_lock_version': scenario['promotion_lock_version'],
        })
        assert accepted.status_code == 201, accepted.text

    # The estimate is newer than CURRENT. A later segment makes the estimate
    # strictly older than the next published state: the original regression.
    assert needs_review()
    end = case.cutoff_at+timedelta(minutes=10)
    segment = client.post(f'/executions/{case.execution_id}/segments', headers=_headers(case, key=True), json={
        'phase_id': str(case.phase_id), 'started_at': case.cutoff_at.isoformat(),
        'ended_at': end.isoformat(), 'work_minutes': 10,
        'humans': [{'employee_id': str(case.employee_id), 'work_minutes': 10}],
        'physical_usages': [{'physical_resource_id': str(case.physical_resource_id), 'work_minutes': 10, 'capacity_units': 1}],
    })
    assert segment.status_code == 201, segment.text
    publish(end)
    assert not needs_review()
    history = client.get(url+'/execution', headers=headers).json()['segments']

    updated = client.post(url+'/execution/remaining-estimate', headers=_headers(case, key=True), json={
        'expected_revision_no': 2, 'cutoff_at': end.isoformat(),
        'remaining': [{'dimension': 'LABOR_WORK', 'phase_id': str(case.phase_id), 'minutes': 240}],
        'reason': 'A later estimate must require another publication',
    })
    assert updated.status_code == 200, updated.text
    assert needs_review()
    publish(end)
    assert not needs_review()
    assert client.get(url+'/execution', headers=headers).json()['segments'] == history

    # A finish event also changes planning even without a newer estimate.
    finished = client.post(url+'/finish', headers=_headers(case, key=True), json={
        'phase_id': str(case.phase_id), 'completed_at': end.isoformat(),
    })
    assert finished.status_code == 200, finished.text
    assert needs_review()
    publish(end)
    assert not needs_review()
    assert client.get(url+'/execution', headers=headers).json()['segments'] == history
