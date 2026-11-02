from __future__ import annotations

import json
from time import perf_counter
from datetime import timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import event, text

from production_besten.api.app import create_app
from production_besten.persistence.api_queries import PostgresApiQueries


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


def _seed_gantt_scale(engine, case, *, first_project, project_count, operations_per_project=5):
    projects, lots, operations, phases, operation_results, phase_results = [], [], [], [], [], []
    with engine.begin() as connection:
        base = connection.execute(text("""
            SELECT customer_id,priority_id FROM core.projects
             WHERE organization_id=:org AND id=:project
        """), {"org": case.organization_id, "project": case.project_id}).mappings().one()
        for project_number in range(first_project, first_project + project_count):
            project_id, lot_id = uuid4(), uuid4()
            projects.append({"id": project_id, "org": case.organization_id, "plant": case.plant_id,
                             "customer": base["customer_id"], "priority": base["priority_id"],
                             "code": f"GANTT-P-{project_number}", "name": f"Gantt project {project_number}"})
            lots.append({"id": lot_id, "org": case.organization_id, "project": project_id,
                         "code": f"GANTT-L-{project_number}", "name": f"Lot {project_number}"})
            for operation_number in range(operations_per_project):
                operation_id, phase_id, operation_result_id, phase_result_id = (uuid4() for _ in range(4))
                suffix = f"{project_number}-{operation_number}"
                start = case.cutoff_at + timedelta(hours=operation_number * 2)
                finish = start + timedelta(minutes=90)
                operations.append({"id": operation_id, "org": case.organization_id, "project": project_id,
                                   "lot": lot_id, "definition": case.operation_definition_id,
                                   "code": f"GANTT-O-{suffix}", "name": f"Operation {suffix}"})
                phases.append({"id": phase_id, "org": case.organization_id, "operation": operation_id,
                               "code": f"GANTT-PH-{suffix}"})
                operation_results.append({"id": operation_result_id, "org": case.organization_id,
                                          "solution": case.schedule_solution_id, "operation": operation_id,
                                          "start": start, "finish": finish})
                phase_results.append({"id": phase_result_id, "org": case.organization_id,
                                      "operation_result": operation_result_id,
                                      "solution": case.schedule_solution_id, "phase": phase_id})
        connection.execute(text("""
            INSERT INTO core.projects(id,organization_id,plant_id,customer_id,code,name,priority_id,status)
            VALUES (:id,:org,:plant,:customer,:code,:name,:priority,'active')
        """), projects)
        connection.execute(text("""
            INSERT INTO core.project_lots(id,organization_id,project_id,code,name,sequence_no,status,hardware_status)
            VALUES (:id,:org,:project,:code,:name,1,'active','ready')
        """), lots)
        connection.execute(text("""
            INSERT INTO production.required_operations
              (id,organization_id,project_id,project_lot_id,operation_definition_id,code,name,status)
            VALUES (:id,:org,:project,:lot,:definition,:code,:name,'active')
        """), operations)
        connection.execute(text("""
            INSERT INTO production.required_operation_phases
              (id,organization_id,required_operation_id,sequence_no,code,name,estimate_kind,
               original_estimate_minutes,split_policy,status)
            VALUES (:id,:org,:operation,1,:code,'Work','labor',90,'splittable','active')
        """), phases)
        connection.execute(text("""
            INSERT INTO planning.operation_plan_results
              (id,organization_id,schedule_solution_id,required_operation_id,result_status,
               planned_start_at,planned_end_at,remaining_work_minutes,explanation)
            VALUES (:id,:org,:solution,:operation,'planned',:start,:finish,90,'{}')
        """), operation_results)
        connection.execute(text("""
            INSERT INTO planning.phase_plan_results
              (id,organization_id,operation_plan_result_id,schedule_solution_id,
               required_operation_phase_id,result_status,planned_work_minutes,
               remaining_work_minutes,explanation)
            VALUES (:id,:org,:operation_result,:solution,:phase,'planned',90,90,'{}')
        """), phase_results)


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
                 "/operations/{operation_id}/replan", "/scenarios/{scenario_id}/reject",
                 "/planning/current/gantt"):
        assert path in schema["paths"]


def _prepare_gantt_calendar(engine, case):
    with engine.begin() as connection:
        connection.execute(text("""
            UPDATE core.plants SET timezone='America/Argentina/Buenos_Aires'
             WHERE organization_id=:org AND id=:plant
        """), {"org": case.organization_id, "plant": case.plant_id})
        connection.execute(text("""
            UPDATE capacity.calendars SET timezone='America/Argentina/Buenos_Aires'
             WHERE organization_id=:org AND id=:calendar
        """), {"org": case.organization_id, "calendar": case.calendar_id})
        connection.execute(text("""
            INSERT INTO capacity.calendar_working_intervals
              (id,organization_id,calendar_id,weekday,local_start,local_end,
               shift_code,capacity_factor,valid_during)
            VALUES (:id,:org,:calendar,:weekday,'08:30','16:00','DAY',1,
                    daterange('2026-01-01','2027-01-01','[)'))
        """), {"id": uuid4(), "org": case.organization_id,
                 "calendar": case.calendar_id,
                 "weekday": case.cutoff_at.date().isoweekday()})


def test_gantt_current_plan_timezone_groups_execution_and_occupation(engine, seeded_case):
    operation_id, start = _publish_operation(engine, seeded_case)
    _prepare_gantt_calendar(engine, seeded_case)
    occupation_id = uuid4()
    with engine.begin() as connection:
        connection.execute(text("""
            UPDATE capacity.work_centers SET aggregate_capacity=3
             WHERE organization_id=:org AND id=:center
        """), {"org": seeded_case.organization_id, "center": seeded_case.work_center_id})
        connection.execute(text("""
            INSERT INTO planning.physical_occupations
              (id,organization_id,operation_execution_id,project_lot_id,
               required_operation_phase_id,physical_resource_id,source_kind,time_range)
            VALUES (:id,:org,:execution,:lot,:phase,:resource,'actual',
                    tstzrange(:start,:finish,'[)'))
        """), {
            "id": occupation_id, "org": seeded_case.organization_id,
            "execution": seeded_case.execution_id, "lot": seeded_case.project_lot_id,
            "phase": seeded_case.phase_id, "resource": seeded_case.physical_resource_id,
            "start": start, "finish": start + timedelta(hours=18),
        })
    params = {
        "from": (start - timedelta(hours=1)).isoformat(),
        "to": (start + timedelta(days=1)).isoformat(),
        "group_by": "center",
    }
    response = _client(engine).get(
        "/planning/current/gantt", params=params, headers=_headers(seeded_case))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["timezone"] == "America/Argentina/Buenos_Aires"
    assert body["operations"][0]["operation_id"] == str(operation_id)
    assert body["operations"][0]["actual_segments"]
    assert body["operations"][0]["remaining_minutes"] == 600
    assert body["groups"][0]["capacity"] == 3
    assert body["working_windows"]
    assert body["occupations"][0]["id"] == str(occupation_id)
    assert body["occupations"][0]["source_kind"] == "actual"

    for grouping, expected in (
        ("resource", "Bench"), ("person", "Worker"), ("project", "Project"),
    ):
        grouped = _client(engine).get(
            "/planning/current/gantt",
            params=params | {"group_by": grouping},
            headers=_headers(seeded_case),
        )
        assert grouped.status_code == 200
        assert grouped.json()["groups"][0]["label"] == expected


def test_gantt_is_tenant_safe_validates_range_and_has_fixed_query_count(engine, seeded_case):
    _, start = _publish_operation(engine, seeded_case)
    params = {
        "from": (start - timedelta(hours=1)).isoformat(),
        "to": (start + timedelta(days=1)).isoformat(),
        "group_by": "center",
    }
    client = _client(engine)
    assert client.get(
        "/planning/current/gantt", params=params,
        headers=_headers(seeded_case, other=True),
    ).status_code == 404
    assert client.get(
        "/planning/current/gantt",
        params=params | {"group_by": "invalid"},
        headers=_headers(seeded_case),
    ).status_code == 422
    assert client.get(
        "/planning/current/gantt",
        params=params | {"to": (start + timedelta(days=32)).isoformat()},
        headers=_headers(seeded_case),
    ).status_code == 400

    statements = []
    def record(*args):
        statements.append(args[2])
    event.listen(engine, "before_cursor_execute", record)
    try:
        PostgresApiQueries(engine).gantt(
            seeded_case.organization_id, seeded_case.plant_id,
            start - timedelta(hours=1), start + timedelta(days=1), "center",
        )
    finally:
        event.remove(engine, "before_cursor_execute", record)
    assert len(statements) == 7


def test_gantt_compares_ready_scenario_semantically(engine, seeded_case):
    operation_id, start = _publish_operation(engine, seeded_case)
    cutoff = seeded_case.cutoff_at
    client = _client(engine)
    created = client.post(
        f"/operations/{operation_id}/replan",
        headers=_headers(seeded_case, key=True),
        json={
            "cutoff_at": cutoff.isoformat(),
            "horizon_end": (cutoff + timedelta(days=7)).isoformat(),
            "reason": "Gantt comparison",
        },
    )
    assert created.status_code == 201, created.text
    scenario_id = created.json()["scenario_id"]
    response = client.get(
        "/planning/current/gantt",
        params={
            "from": (start - timedelta(hours=1)).isoformat(),
            "to": (cutoff + timedelta(days=7)).isoformat(),
            "group_by": "project",
            "scenario_id": scenario_id,
        },
        headers=_headers(seeded_case),
    )
    assert response.status_code == 200, response.text
    scenario = response.json()["scenario"]
    assert scenario["id"] == scenario_id
    assert scenario["operations"]
    assert scenario["operations"][0]["difference"] in {
        "UNCHANGED", "SHIFTED", "ADVANCED", "DELAYED",
        "OUT_OF_HORIZON", "NEWLY_PLANNED",
    }
    assert response.json()["available_scenarios"][0]["id"] == scenario_id


def test_gantt_postgresql_benchmark_10_50_and_50_250(engine, seeded_case):
    query = PostgresApiQueries(engine)
    range_from = seeded_case.cutoff_at - timedelta(hours=1)
    range_to = seeded_case.cutoff_at + timedelta(days=14)

    _seed_gantt_scale(engine, seeded_case, first_project=0, project_count=10)
    started = perf_counter()
    small = query.gantt(
        seeded_case.organization_id, seeded_case.plant_id,
        range_from, range_to, "project",
    )
    small_ms = (perf_counter() - started) * 1000
    small_bytes = len(json.dumps(small, default=str, separators=(",", ":")).encode())
    assert len(small["operations"]) == 50

    _seed_gantt_scale(engine, seeded_case, first_project=10, project_count=40)
    started = perf_counter()
    moderate = query.gantt(
        seeded_case.organization_id, seeded_case.plant_id,
        range_from, range_to, "project",
    )
    moderate_ms = (perf_counter() - started) * 1000
    moderate_bytes = len(json.dumps(moderate, default=str, separators=(",", ":")).encode())
    assert len(moderate["operations"]) == 250

    print(
        f"GANTT_BENCHMARK 10/50={small_ms:.2f}ms/{small_bytes / 1024:.1f}KiB "
        f"50/250={moderate_ms:.2f}ms/{moderate_bytes / 1024:.1f}KiB"
    )
    assert small_ms < 2000
    assert moderate_ms < 3000
    assert small_bytes < 512 * 1024
    assert moderate_bytes < 2 * 1024 * 1024
