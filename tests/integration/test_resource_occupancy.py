from datetime import date, datetime, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text

from production_besten.api.app import create_app
from tests.integration.test_operational_frontend_api import _headers, _publish_operation


PATH = "/planning/current/resource-occupancy"


def test_two_hour_current_segment_matches_gantt_for_every_assigned_resource(engine, seeded_case):
    case = seeded_case
    operation_id, _ = _publish_operation(engine, case)
    second_employee = uuid4()
    start = datetime.fromisoformat("2026-11-16T08:00:00-03:00")
    end = datetime.fromisoformat("2026-11-16T10:00:00-03:00")
    params = {
        "org": case.organization_id, "plant": case.plant_id, "calendar": case.calendar_id,
        "solution": case.schedule_solution_id, "employee": second_employee,
        "start": start, "end": end,
    }
    with engine.begin() as conn:
        conn.execute(text("UPDATE core.plants SET timezone='America/Argentina/Cordoba' WHERE id=:plant"), params)
        conn.execute(text("UPDATE capacity.calendars SET timezone='America/Argentina/Cordoba' WHERE id=:calendar"), params)
        conn.execute(text("""
            INSERT INTO capacity.calendar_working_intervals
                (organization_id,calendar_id,weekday,local_start,local_end,valid_during)
            VALUES (:org,:calendar,1,'08:00','12:00','[2026-11-16,)'),
                   (:org,:calendar,1,'12:45','17:00','[2026-11-16,)')
        """), params)
        conn.execute(text("""
            INSERT INTO capacity.employees(id,organization_id,plant_id,code,display_name,base_calendar_id)
            VALUES (:employee,:org,:plant,'WORKER-2','Worker 2',:calendar)
        """), params)
        conn.execute(text("""
            UPDATE planning.operation_plan_results
            SET planned_start_at=:start,planned_end_at=:end
            WHERE schedule_solution_id=:solution
        """), params)
        conn.execute(text("""
            UPDATE planning.planned_phase_assignments
            SET planned_start_at=:start,planned_end_at=:end,work_minutes=120
            WHERE schedule_solution_id=:solution
        """), params)
        for table in ("assignment_segments", "human_segment_assignments"):
            conn.execute(text(f"""
                UPDATE planning.{table}
                SET time_range=tstzrange(:start,:end,'[)'),normal_minutes=120,work_minutes=120
                WHERE schedule_solution_id=:solution
            """), params)
        conn.execute(text("""
            UPDATE planning.physical_resource_reservations
            SET time_range=tstzrange(:start,:end,'[)')
            WHERE schedule_solution_id=:solution
        """), params)
        conn.execute(text("""
            INSERT INTO planning.human_segment_assignments
                (organization_id,assignment_segment_id,schedule_solution_id,employee_id,
                 time_range,normal_minutes,overtime_minutes,work_minutes)
            SELECT organization_id,id,schedule_solution_id,:employee,time_range,120,0,120
            FROM planning.assignment_segments WHERE schedule_solution_id=:solution
        """), params)

    clock = lambda: datetime.fromisoformat("2026-11-16T15:00:00-03:00")
    with TestClient(create_app(engine=engine, clock=clock)) as client:
        occupancy = client.get(PATH, headers=_headers(case))
        gantt = client.get("/planning/current/gantt", headers=_headers(case), params={
            "from": "2026-11-16T00:00:00-03:00", "to": "2026-11-17T00:00:00-03:00",
            "group_by": "project",
        })
    assert occupancy.status_code == 200, occupancy.text
    assert gantt.status_code == 200, gantt.text
    operation = next(item for item in gantt.json()["operations"] if item["operation_id"] == str(operation_id))
    segment, = operation["planned_segments"]
    assert datetime.fromisoformat(segment["started_at"]) == start
    assert datetime.fromisoformat(segment["ended_at"]) == end
    assert {item["id"] for item in operation["people"]} == {str(case.employee_id), str(second_employee)}
    assert {item["id"] for item in operation["resources"]} == {str(case.physical_resource_id)}
    report = occupancy.json()
    assert report["plan_version_number"] == gantt.json()["plan_version_number"] == 1
    assert report["dates"][0] == "2026-11-16"
    rows = {row["id"]: row["days"][0] for row in report["resources"]}
    for resource in (case.employee_id, second_employee, case.physical_resource_id):
        day = rows[str(resource)]
        assert day["available_minutes"] == 495
        assert day["occupied_minutes"] == 120
        assert day["free_minutes"] == 375
        assert round(day["percent"], 1) == 24.2
        booking, = day["bookings"]
        assert booking["occupied_minutes"] == 120
        assert booking["alerts"] == []
        for field in ("project_code", "project_name", "operation_name"):
            assert booking[field] == operation[field]
        assert datetime.fromisoformat(booking["start_at"]) == datetime.fromisoformat(segment["started_at"])
        assert datetime.fromisoformat(booking["end_at"]) == datetime.fromisoformat(segment["ended_at"])


def test_resource_occupancy_counts_effective_minutes_and_continuous_holds(engine, seeded_case):
    case = seeded_case
    _publish_operation(engine, case)
    free, blocked, missing, missing_calendar = (uuid4() for _ in range(4))
    params = {
        "org": case.organization_id, "plant": case.plant_id, "calendar": case.calendar_id,
        "solution": case.schedule_solution_id, "phase": case.phase_id, "lot": case.project_lot_id,
        "bank": case.physical_resource_id, "employee": case.employee_id, "actor": case.actor_id,
        "execution": case.execution_id, "missing_calendar": missing_calendar, "project": case.project_id,
    }
    with engine.begin() as conn:
        conn.execute(text("UPDATE core.plants SET timezone='America/Argentina/Cordoba' WHERE id=:plant"), params)
        conn.execute(text("UPDATE capacity.calendars SET timezone='America/Argentina/Cordoba' WHERE id=:calendar"), params)
        conn.execute(text("""
            INSERT INTO capacity.calendars(id,organization_id,code,name,timezone,calendar_kind,status)
            VALUES (:missing_calendar,:org,'INACTIVE','Inactive','America/Argentina/Cordoba','production','inactive')
        """), params)
        conn.execute(text("""
            INSERT INTO capacity.calendar_working_intervals(organization_id,calendar_id,weekday,local_start,local_end,valid_during)
            SELECT :org,:calendar,day,start_at,end_at,daterange(DATE '2026-11-16',NULL,'[)')
            FROM generate_series(1,5) day CROSS JOIN (VALUES
                  (TIME '08:00',TIME '12:00'),(TIME '12:45',TIME '17:00')) AS shift(start_at,end_at)
        """), params)
        conn.execute(text("""
            INSERT INTO capacity.calendar_exceptions(organization_id,calendar_id,exception_date,effect)
            VALUES (:org,:calendar,DATE '2026-11-17','remove')
        """), params)
        conn.execute(text("""
            INSERT INTO capacity.employees(id,organization_id,plant_id,code,display_name,base_calendar_id)
            VALUES (:owner,:org,:plant,:label,:label,:owner_calendar)
        """), [
            {**params, "owner": free, "label": "Free", "owner_calendar": case.calendar_id},
            {**params, "owner": blocked, "label": "Blocked", "owner_calendar": case.calendar_id},
            {**params, "owner": missing, "label": "Missing", "owner_calendar": missing_calendar},
        ])
        conn.execute(text("""
            INSERT INTO capacity.resource_unavailabilities(organization_id,employee_id,time_range,reason_code)
            VALUES (:org,:employee,'[2026-11-16 08:00-03,2026-11-16 10:00-03)','ABSENCE'),
                   (:org,:blocked,'[2026-11-16 00:00-03,2026-11-17 00:00-03)','ABSENCE')
        """), {**params, "blocked": blocked})
        conn.execute(text("""
            INSERT INTO capacity.overtime_authorizations(organization_id,plant_id,employee_id,project_id,time_range,max_minutes,approved_by,reason)
            VALUES (:org,:plant,:employee,:project,'[2026-11-16 17:00-03,2026-11-16 18:00-03)',30,:actor,'Test')
        """), params)
        conn.execute(text("""
            UPDATE planning.human_segment_assignments
            SET time_range='[2026-11-16 11:30-03,2026-11-16 13:15-03)'
            WHERE schedule_solution_id=:solution
        """), params)
        conn.execute(text("""
            WITH extra AS (
                INSERT INTO planning.assignment_segments
                    (organization_id,planned_phase_assignment_id,schedule_solution_id,segment_no,time_range,
                     normal_minutes,overtime_minutes,work_minutes)
                SELECT organization_id,planned_phase_assignment_id,schedule_solution_id,2,
                       '[2026-11-16 11:45-03,2026-11-16 12:00-03)',15,0,15
                FROM planning.assignment_segments WHERE schedule_solution_id=:solution
                RETURNING id,organization_id,schedule_solution_id,time_range
            )
            INSERT INTO planning.human_segment_assignments
                (organization_id,assignment_segment_id,schedule_solution_id,employee_id,time_range,
                 normal_minutes,overtime_minutes,work_minutes,exclusive_guard)
            SELECT organization_id,id,schedule_solution_id,:employee,time_range,15,0,15,false
            FROM extra
        """), params)
        conn.execute(text("""
            UPDATE planning.physical_resource_reservations
            SET usage_mode='occupation',time_range='[2026-11-16 16:30-03,2026-11-16 17:00-03)'
            WHERE schedule_solution_id=:solution
        """), params)
        conn.execute(text("""
            INSERT INTO planning.physical_occupations
                (organization_id,schedule_solution_id,project_lot_id,required_operation_phase_id,
                 physical_resource_id,source_kind,time_range,planned_release_at)
            VALUES (:org,:solution,:lot,:phase,:bank,'planned',
                    '[2026-11-16 16:30-03,2026-11-18 08:45-03)','2026-11-18 08:45-03')
        """), params)
        conn.execute(text("""
            WITH other_solution AS (
                INSERT INTO planning.schedule_solutions
                    (organization_id,scenario_id,run_no,status,algorithm_version,
                     input_product_definition_revision_id,base_state_revision_id,input_snapshot,
                     input_sha256,started_at,horizon_range,solution_sha256,ready_at)
                SELECT organization_id,scenario_id,run_no+1,'ready',algorithm_version,
                       input_product_definition_revision_id,base_state_revision_id,input_snapshot,
                       input_sha256,started_at,horizon_range,solution_sha256,ready_at
                FROM planning.schedule_solutions WHERE id=:solution
                RETURNING id
            )
            INSERT INTO planning.physical_occupations
                (organization_id,schedule_solution_id,project_lot_id,required_operation_phase_id,
                 physical_resource_id,source_kind,time_range)
            SELECT :org,id,:lot,:phase,:bank,'planned',
                   '[2026-11-18 13:00-03,2026-11-18 17:00-03)'
            FROM other_solution
        """), params)
        conn.execute(text("""
            INSERT INTO planning.physical_occupations
                (organization_id,operation_execution_id,project_lot_id,required_operation_phase_id,
                 physical_resource_id,source_kind,time_range,planned_release_at)
            VALUES (:org,:execution,:lot,:phase,:bank,'actual',
                    '[2026-11-19 16:30-03,)','2026-11-20 08:45-03')
        """), params)

    app = create_app(engine=engine, clock=lambda: datetime(2026, 11, 17, 1, tzinfo=timezone.utc))
    with TestClient(app) as client:
        response = client.get(PATH, headers=_headers(case))
        assert response.status_code == 200, response.text
        report = response.json()
        assert report["plan_version_number"] == 1
        assert len(report["dates"]) == 30
        assert report["dates"][0] == "2026-11-16"
        assert report["dates"][-1] == "2026-12-15"
        rows = {row["id"]: row["days"] for row in report["resources"]}
        worker = rows[str(case.employee_id)][0]
        assert worker["available_minutes"] == 405  # 495 - 120 absence + 30 approved overtime.
        assert worker["occupied_minutes"] == 60  # Lunch excluded and overlap counted once.
        assert worker["free_minutes"] == 345
        assert worker["percent"] == 100 * 60 / 405
        assert worker["bookings"][0]["alerts"] == ["outside_availability", "overlap"]
        assert worker["bookings"][1]["alerts"] == ["overlap"]
        assert rows[str(free)][0]["percent"] == 0
        assert rows[str(free)][0]["available_minutes"] == 495  # Employee overtime is scoped.
        assert rows[str(blocked)][0]["status"] == "unavailable"
        assert rows[str(missing)][0]["status"] == "missing_calendar"

        bank = rows[str(case.physical_resource_id)]
        assert bank[0]["occupied_minutes"] == 30
        assert len(bank[0]["bookings"]) == 1  # Hold and component segment are not double counted.
        assert bank[1]["status"] == "no_shift"
        assert bank[1]["bookings"][0]["minutes_in_day"] == 1440
        assert bank[1]["bookings"][0]["alerts"] == []
        assert bank[2]["occupied_minutes"] == 45
        assert bank[4]["occupied_minutes"] == 495
        assert bank[4]["bookings"][0]["end_at"] is None
        assert bank[5]["status"] == "no_shift" and bank[5]["bookings"][0]["end_at"] is None
        assert client.get(PATH, headers=_headers(case, other=True)).status_code == 404

        with engine.begin() as conn:
            state = conn.scalar(text("SELECT current_plan_version_id FROM core.plants WHERE id=:plant"), params)
            assert state == case.plan_version_id
            conn.execute(text("UPDATE core.plants SET current_plan_version_id=NULL WHERE id=:plant"), params)
        empty = client.get(PATH, headers=_headers(case)).json()
        assert empty["plan_version_number"] is None
        assert empty["resources"] == []
