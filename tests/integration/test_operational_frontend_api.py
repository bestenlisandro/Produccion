from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text

from production_besten.api.app import create_app


def _headers(case, *, other=False, key=False):
    result = {
        "X-Dev-User-Id": str(case.actor_id),
        "X-Dev-Organization-Id": str(case.other_organization_id if other else case.organization_id),
        "X-Dev-Plant-Id": str(case.plant_id),
    }
    if key:
        result["Idempotency-Key"] = str(uuid4())
    return result


def _client(engine):
    return TestClient(create_app(engine=engine, enable_dev_context=True), raise_server_exceptions=False)


def _publish_operation(engine, case):
    operation_result, phase_result, assignment, segment = (uuid4() for _ in range(4))
    start = case.cutoff_at - timedelta(hours=7)
    finish = case.cutoff_at + timedelta(hours=3)
    with engine.begin() as connection:
        operation_id = connection.scalar(text("""
            SELECT required_operation_id FROM execution.operation_executions
             WHERE organization_id=:org AND id=:execution
        """), {"org": case.organization_id, "execution": case.execution_id})
        connection.execute(text("""
            INSERT INTO planning.operation_plan_results
              (id,organization_id,schedule_solution_id,required_operation_id,result_status,
               planned_start_at,planned_end_at,remaining_work_minutes,explanation)
            VALUES (:id,:org,:solution,:operation,'planned',:start,:finish,180,'{}')
        """), {"id": operation_result, "org": case.organization_id,
                 "solution": case.schedule_solution_id, "operation": operation_id,
                 "start": start, "finish": finish})
        connection.execute(text("""
            INSERT INTO planning.phase_plan_results
              (id,organization_id,operation_plan_result_id,schedule_solution_id,
               required_operation_phase_id,result_status,remaining_estimate_revision_id,
               planned_work_minutes,remaining_work_minutes,explanation)
            VALUES (:id,:org,:operation_result,:solution,:phase,'planned',:remaining,600,180,'{}')
        """), {"id": phase_result, "org": case.organization_id,
                 "operation_result": operation_result, "solution": case.schedule_solution_id,
                 "phase": case.phase_id, "remaining": case.initial_remaining_revision_id})
        connection.execute(text("""
            INSERT INTO planning.planned_phase_assignments
              (id,organization_id,phase_plan_result_id,schedule_solution_id,assignment_kind,
               planned_start_at,planned_end_at,work_minutes)
            VALUES (:id,:org,:phase_result,:solution,'operation',:start,:finish,600)
        """), {"id": assignment, "org": case.organization_id, "phase_result": phase_result,
                 "solution": case.schedule_solution_id, "start": start, "finish": finish})
        connection.execute(text("""
            INSERT INTO planning.assignment_segments
              (id,organization_id,planned_phase_assignment_id,schedule_solution_id,
               segment_no,time_range,normal_minutes,overtime_minutes,work_minutes)
            VALUES (:id,:org,:assignment,:solution,1,tstzrange(:start,:finish,'[)'),600,0,600)
        """), {"id": segment, "org": case.organization_id, "assignment": assignment,
                 "solution": case.schedule_solution_id, "start": start, "finish": finish})
        connection.execute(text("""
            INSERT INTO planning.human_segment_assignments
              (organization_id,assignment_segment_id,schedule_solution_id,employee_id,
               time_range,normal_minutes,overtime_minutes,work_minutes)
            VALUES (:org,:segment,:solution,:employee,tstzrange(:start,:finish,'[)'),600,0,600)
        """), {"org": case.organization_id, "segment": segment,
                 "solution": case.schedule_solution_id, "employee": case.employee_id,
                 "start": start, "finish": finish})
        connection.execute(text("""
            INSERT INTO planning.physical_resource_reservations
              (organization_id,assignment_segment_id,schedule_solution_id,physical_resource_id,
               time_range,capacity_units,exclusive_guard,usage_mode)
            VALUES (:org,:segment,:solution,:resource,tstzrange(:start,:finish,'[)'),1,true,'active_use')
        """), {"org": case.organization_id, "segment": segment,
                 "solution": case.schedule_solution_id, "resource": case.physical_resource_id,
                 "start": start, "finish": finish})
    return operation_id, start


def test_daily_board_and_operation_detail_use_current_plan(engine, seeded_case):
    operation_id, start = _publish_operation(engine, seeded_case)
    client = _client(engine)
    board = client.get(f"/planning/current/day?date={start.date()}", headers=_headers(seeded_case))
    assert board.status_code == 200
    item = board.json()["operations"][0]
    assert item["operation_id"] == str(operation_id)
    assert item["project_name"] == "Project"
    assert item["operational_status"] == "EN_CURSO"
    assert item["people"][0]["name"] == "Worker"
    assert item["physical_resource"] == "Bench"

    detail = client.get(f"/operations/{operation_id}", headers=_headers(seeded_case))
    assert detail.status_code == 200
    assert detail.json()["original_estimate_minutes"] == 600
    assert detail.json()["remaining_minutes"] == 600
    assert detail.json()["plan_requires_reconciliation"] is False


def test_operational_reads_are_tenant_safe_and_validate_input(engine, seeded_case):
    operation_id, start = _publish_operation(engine, seeded_case)
    client = _client(engine)
    assert client.get(f"/operations/{operation_id}", headers=_headers(seeded_case, other=True)).status_code == 404
    assert client.get("/planning/current/day?date=not-a-date", headers=_headers(seeded_case)).status_code == 422
    assert client.get(f"/planning/current/day?date={start.date()}", headers={}).status_code == 422


def test_replan_and_reject_http_preserve_domain_lifecycle(engine, seeded_case):
    operation_id, _ = _publish_operation(engine, seeded_case)
    client = _client(engine)
    cutoff = seeded_case.cutoff_at
    response = client.post(f"/operations/{operation_id}/replan", headers=_headers(seeded_case, key=True), json={
        "cutoff_at": cutoff.isoformat(),
        "horizon_end": (cutoff + timedelta(days=7)).isoformat(),
        "reason": "API board test",
    })
    assert response.status_code == 201, response.text
    scenario_id = response.json()["scenario_id"]
    scenario = client.get(f"/scenarios/{scenario_id}", headers=_headers(seeded_case)).json()
    rejected = client.post(f"/scenarios/{scenario_id}/reject", headers=_headers(seeded_case, key=True), json={
        "expected_row_version": scenario["row_version"], "reason": "Operator cancelled",
    })
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    assert client.get(f"/scenarios/{scenario_id}", headers=_headers(seeded_case)).json()["rejected"] is True


def test_openapi_includes_operational_contracts(engine):
    schema = _client(engine).get("/openapi.json").json()
    for path in ("/planning/current/day", "/operations/{operation_id}",
                 "/operations/{operation_id}/replan", "/scenarios/{scenario_id}/reject"):
        assert path in schema["paths"]
