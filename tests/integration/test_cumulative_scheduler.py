from __future__ import annotations

from datetime import timedelta
from time import perf_counter
from uuid import uuid4

import pytest
from sqlalchemy import text

from production_besten.application.scheduling_services import GenerateScheduleService
from production_besten.domain.errors import EntityNotFound
from production_besten.domain.scheduling.models import GenerateSchedule
from production_besten.persistence.scheduling_uow import PostgresSchedulingUnitOfWorkFactory
from tests.integration.scheduling_helpers import (
    HORIZON_START, add_employee, add_operation, generate, prepare_basic, solution_segments,
)


def _configure(engine, case, *, capacity=3, demand=1, minutes=120, split="splittable"):
    operation = prepare_basic(engine, case, minutes=minutes, split_policy=split)
    with engine.begin() as connection:
        connection.execute(text("""
            UPDATE capacity.physical_resources
            SET scheduling_mode='cumulative',capacity_units=:capacity
            WHERE organization_id=:org AND id=:resource
        """), {"capacity": capacity, "org": case.organization_id, "resource": case.physical_resource_id})
        connection.execute(text("""
            UPDATE production.operation_physical_requirements SET capacity_units=:demand,quantity=1
            WHERE organization_id=:org AND id=:requirement
        """), {"demand": demand, "org": case.organization_id, "requirement": case.physical_requirement_id})
        connection.execute(text("""
            UPDATE production.required_operations SET code='A',name='A'
            WHERE organization_id=:org AND id=:operation
        """), {"org": case.organization_id, "operation": operation})
    return operation


def _add(connection, case, code, *, minutes=120, demand=1, skill_id=None, split="splittable"):
    return add_operation(
        connection, case, code, minutes=minutes, skill_id=skill_id,
        resource_type_id=case.resource_type_id, capacity_units=demand, split_policy=split,
    )


def _starts(engine, solution_id):
    return [row.start_at for row in solution_segments(engine, solution_id)]


def test_capacity_three_accepts_three_unit_demands(engine, seeded_case):
    _configure(engine, seeded_case)
    with engine.begin() as connection:
        _add(connection, seeded_case, "B")
        _add(connection, seeded_case, "C")
    result = generate(engine, seeded_case)
    assert _starts(engine, result.solution_id) == [HORIZON_START] * 3


def test_fourth_unit_demand_is_displaced(engine, seeded_case):
    _configure(engine, seeded_case)
    with engine.begin() as connection:
        for code in ("B", "C", "D"):
            _add(connection, seeded_case, code)
    starts = _starts(engine, generate(engine, seeded_case).solution_id)
    assert starts.count(HORIZON_START) == 3
    assert starts.count(HORIZON_START + timedelta(hours=2)) == 1


def test_two_plus_one_is_allowed(engine, seeded_case):
    _configure(engine, seeded_case, demand=2)
    with engine.begin() as connection:
        _, phase_b = _add(connection, seeded_case, "B", demand=1)
    result = generate(engine, seeded_case)
    by_phase = {row.required_operation_phase_id: row.start_at for row in solution_segments(engine, result.solution_id)}
    assert by_phase[seeded_case.phase_id] == by_phase[phase_b] == HORIZON_START


def test_two_plus_two_is_incompatible(engine, seeded_case):
    _configure(engine, seeded_case, demand=2)
    with engine.begin() as connection:
        _, phase_b = _add(connection, seeded_case, "B", demand=2)
    result = generate(engine, seeded_case)
    by_phase = {row.required_operation_phase_id: row.start_at for row in solution_segments(engine, result.solution_id)}
    assert by_phase[phase_b] == HORIZON_START + timedelta(hours=2)


def test_capacity_available_but_people_insufficient(engine, seeded_case):
    _configure(engine, seeded_case)
    with engine.begin() as connection:
        connection.execute(text("""
            UPDATE production.operation_labor_requirements SET min_people=2,max_people=2
            WHERE organization_id=:org AND required_operation_phase_id=:phase
        """), {"org": seeded_case.organization_id, "phase": seeded_case.phase_id})
    result = generate(engine, seeded_case)
    assert result.blocked_phases == 1


def test_capacity_available_but_skill_insufficient(engine, seeded_case):
    _configure(engine, seeded_case)
    missing_skill = uuid4()
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO capacity.skills(id,organization_id,code,name) VALUES (:id,:org,:code,'Missing')"), {"id": missing_skill, "org": seeded_case.organization_id, "code": f"MISS-{missing_skill.hex[:6]}"})
        connection.execute(text("UPDATE production.operation_labor_requirements SET skill_id=:skill WHERE organization_id=:org AND required_operation_phase_id=:phase"), {"skill": missing_skill, "org": seeded_case.organization_id, "phase": seeded_case.phase_id})
    result = generate(engine, seeded_case)
    with engine.connect() as connection:
        explanation = connection.scalar(text("SELECT explanation FROM planning.phase_plan_results WHERE schedule_solution_id=:solution"), {"solution": result.solution_id})
    assert "REQUIRED_SKILL_UNAVAILABLE" in explanation["why_not_earlier"]


def test_cumulative_capacity_and_exclusive_resource_both_apply(engine, seeded_case):
    _configure(engine, seeded_case)
    exclusive_type, exclusive = uuid4(), uuid4()
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO capacity.physical_resource_types(id,organization_id,code,name,resource_kind,default_scheduling_mode) VALUES (:id,:org,:code,'Saw','machine','exclusive')"), {"id": exclusive_type, "org": seeded_case.organization_id, "code": f"SAW-{exclusive_type.hex[:6]}"})
        connection.execute(text("INSERT INTO capacity.physical_resources(id,organization_id,plant_id,work_center_id,resource_type_id,code,name,scheduling_mode,capacity_units,base_calendar_id) VALUES (:id,:org,:plant,:center,:type,:code,'Saw','exclusive',1,:calendar)"), {"id": exclusive, "org": seeded_case.organization_id, "plant": seeded_case.plant_id, "center": seeded_case.work_center_id, "type": exclusive_type, "code": f"SAW-{exclusive.hex[:6]}", "calendar": seeded_case.calendar_id})
        _, phase_b = _add(connection, seeded_case, "B")
        for phase in (seeded_case.phase_id, phase_b):
            connection.execute(text("INSERT INTO production.operation_physical_requirements(organization_id,required_operation_phase_id,physical_resource_type_id,quantity,capacity_units,usage_mode) VALUES (:org,:phase,:type,1,1,'active_use')"), {"org": seeded_case.organization_id, "phase": phase, "type": exclusive_type})
    result = generate(engine, seeded_case)
    by_phase = {row.required_operation_phase_id: row.start_at for row in solution_segments(engine, result.solution_id)}
    assert by_phase[phase_b] == HORIZON_START + timedelta(hours=2)


def test_capacity_release_inside_shift_is_detected(engine, seeded_case):
    _configure(engine, seeded_case, demand=2, minutes=240)
    with engine.begin() as connection:
        _add(connection, seeded_case, "B", minutes=120, demand=1)
        _, phase_c = _add(connection, seeded_case, "C", minutes=60, demand=1)
    result = generate(engine, seeded_case)
    by_phase = {row.required_operation_phase_id: row.start_at for row in solution_segments(engine, result.solution_id)}
    assert by_phase[phase_c] == HORIZON_START + timedelta(hours=2)


def test_actual_cumulative_usage_loaded_from_postgresql_delays_new_demand(engine, seeded_case):
    _configure(engine, seeded_case, capacity=3, demand=2, minutes=60)
    segment_id = uuid4()
    with engine.begin() as connection:
        connection.execute(text("""
            INSERT INTO execution.execution_segments
              (id,organization_id,operation_execution_id,required_operation_phase_id,
               segment_no,time_range,segment_kind,work_minutes)
            VALUES (:id,:org,:execution,:phase,2,tstzrange(:start,:finish,'[)'),'work',120)
        """), {"id": segment_id, "org": seeded_case.organization_id,
                "execution": seeded_case.execution_id, "phase": seeded_case.phase_id,
                "start": HORIZON_START, "finish": HORIZON_START + timedelta(hours=2)})
        connection.execute(text("""
            INSERT INTO execution.actual_resource_usages
              (organization_id,execution_segment_id,physical_resource_id,time_range,
               work_minutes,capacity_units,usage_kind)
            VALUES (:org,:segment,:resource,tstzrange(:start,:finish,'[)'),120,2,'active_use')
        """), {"org": seeded_case.organization_id, "segment": segment_id,
                "resource": seeded_case.physical_resource_id, "start": HORIZON_START,
                "finish": HORIZON_START + timedelta(hours=2)})
    result = generate(engine, seeded_case)
    assert solution_segments(engine, result.solution_id)[0].start_at == HORIZON_START + timedelta(hours=2)


def test_cumulative_operation_splits_between_workdays(engine, seeded_case):
    _configure(engine, seeded_case, demand=3, minutes=300)
    with engine.begin() as connection:
        _, phase_b = _add(connection, seeded_case, "B", minutes=480, demand=1)
    result = generate(engine, seeded_case)
    rows = [row for row in solution_segments(engine, result.solution_id) if row.required_operation_phase_id == phase_b]
    assert [(row.start_at, row.work_minutes) for row in rows] == [
        (HORIZON_START + timedelta(hours=5), 180), (HORIZON_START + timedelta(days=1), 300)
    ]


def test_high_priority_wins_cumulative_capacity(engine, seeded_case):
    _configure(engine, seeded_case, capacity=1)
    high_priority, customer, project, lot = uuid4(), uuid4(), uuid4(), uuid4()
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO core.project_priorities(id,organization_id,code,name,rank) VALUES (:id,:org,'HIGH','High',1)"), {"id": high_priority, "org": seeded_case.organization_id})
        connection.execute(text("INSERT INTO core.customers(id,organization_id,code,display_name) VALUES (:id,:org,:code,'Customer')"), {"id": customer, "org": seeded_case.organization_id, "code": f"CU-{customer.hex[:6]}"})
        connection.execute(text("INSERT INTO core.projects(id,organization_id,plant_id,customer_id,code,name,priority_id,status) VALUES (:id,:org,:plant,:customer,:code,'High',:priority,'active')"), {"id": project, "org": seeded_case.organization_id, "plant": seeded_case.plant_id, "customer": customer, "code": f"HIGH-{project.hex[:6]}", "priority": high_priority})
        connection.execute(text("INSERT INTO core.project_lots(id,organization_id,project_id,code,name,sequence_no,status,hardware_status) VALUES (:id,:org,:project,:code,'Lot',1,'active','ready')"), {"id": lot, "org": seeded_case.organization_id, "project": project, "code": f"LOT-{lot.hex[:6]}"})
        _, high_phase = add_operation(connection, seeded_case, "HIGH-WORK", project_id=project, lot_id=lot, resource_type_id=seeded_case.resource_type_id)
    result = generate(engine, seeded_case, project_ids=(seeded_case.project_id, project))
    by_phase = {row.required_operation_phase_id: row.start_at for row in solution_segments(engine, result.solution_id)}
    assert by_phase[high_phase] == HORIZON_START
    assert by_phase[seeded_case.phase_id] == HORIZON_START + timedelta(hours=2)


def test_equal_priority_tie_is_deterministic(engine, seeded_case):
    _configure(engine, seeded_case, capacity=1)
    with engine.begin() as connection:
        _add(connection, seeded_case, "B")
    first, second = generate(engine, seeded_case), generate(engine, seeded_case)
    assert first.solution_sha256 == second.solution_sha256


def test_phases_can_have_different_capacity_demands(engine, seeded_case):
    operation = _configure(engine, seeded_case, demand=2)
    second = uuid4()
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO production.required_operation_phases(id,organization_id,required_operation_id,sequence_no,code,name,estimate_kind,original_estimate_minutes,split_policy,status) VALUES (:id,:org,:operation,2,'FINISH','Finish','labor',60,'splittable','active')"), {"id": second, "org": seeded_case.organization_id, "operation": operation})
        connection.execute(text("INSERT INTO production.operation_physical_requirements(organization_id,required_operation_phase_id,physical_resource_type_id,quantity,capacity_units,usage_mode) VALUES (:org,:phase,:type,1,1,'active_use')"), {"org": seeded_case.organization_id, "phase": second, "type": seeded_case.resource_type_id})
    result = generate(engine, seeded_case)
    with engine.connect() as connection:
        demands = connection.execute(text("SELECT capacity_units FROM planning.physical_resource_reservations WHERE schedule_solution_id=:solution ORDER BY lower(time_range)"), {"solution": result.solution_id}).scalars().all()
    assert demands == [2, 1]


def test_alternative_scenarios_keep_capacity_reservations_isolated(engine, seeded_case):
    _configure(engine, seeded_case)
    first, second = generate(engine, seeded_case), generate(engine, seeded_case)
    with engine.connect() as connection:
        starts = connection.execute(text("SELECT schedule_solution_id,lower(time_range) FROM planning.physical_resource_reservations WHERE schedule_solution_id=ANY(:ids) ORDER BY schedule_solution_id"), {"ids": [first.solution_id, second.solution_id]}).all()
    assert len(starts) == 2 and {row[1] for row in starts} == {HORIZON_START}


def test_current_plan_remains_unchanged(engine, seeded_case):
    _configure(engine, seeded_case)
    generate(engine, seeded_case)
    with engine.connect() as connection:
        current = connection.scalar(text("SELECT current_plan_version_id FROM core.plants WHERE organization_id=:org AND id=:plant"), {"org": seeded_case.organization_id, "plant": seeded_case.plant_id})
    assert current == seeded_case.plan_version_id


def test_cross_tenant_cannot_consume_capacity(engine, seeded_case):
    _configure(engine, seeded_case)
    command = GenerateSchedule(
        seeded_case.other_organization_id, seeded_case.plant_id, seeded_case.actor_id,
        f"X-{uuid4().hex}", "Cross tenant", HORIZON_START, HORIZON_START + timedelta(days=1),
        seeded_case.definition_revision_id, seeded_case.initial_state_revision_id, (seeded_case.project_id,),
    )
    with pytest.raises(EntityNotFound):
        GenerateScheduleService(PostgresSchedulingUnitOfWorkFactory(engine)).execute(command)


def test_persistence_failure_rolls_back_cumulative_solution(engine, seeded_case):
    _configure(engine, seeded_case)
    with engine.connect() as connection:
        before = connection.scalar(text("SELECT count(*) FROM planning.scenarios WHERE organization_id=:org"), {"org": seeded_case.organization_id})
    with pytest.raises(RuntimeError, match="injected persistence failure"):
        generate(engine, seeded_case, failpoint="after_solution")
    with engine.connect() as connection:
        after = connection.scalar(text("SELECT count(*) FROM planning.scenarios WHERE organization_id=:org"), {"org": seeded_case.organization_id})
    assert after == before


def test_out_of_horizon_when_cumulative_capacity_never_frees(engine, seeded_case):
    _configure(engine, seeded_case, capacity=1)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO capacity.resource_unavailabilities(organization_id,physical_resource_id,time_range,reason_code) VALUES (:org,:resource,tstzrange(:start,:end,'[)'),'maintenance')"), {"org": seeded_case.organization_id, "resource": seeded_case.physical_resource_id, "start": HORIZON_START, "end": HORIZON_START + timedelta(days=1)})
    result = generate(engine, seeded_case, end=HORIZON_START + timedelta(hours=8))
    assert result.out_of_horizon_phases == 1


def test_capacity_blocker_is_explainable_with_release_time(engine, seeded_case):
    _configure(engine, seeded_case, demand=3)
    with engine.begin() as connection:
        _, phase_b = _add(connection, seeded_case, "B", minutes=60, demand=1)
    result = generate(engine, seeded_case)
    with engine.connect() as connection:
        explanation = connection.scalar(text("SELECT explanation FROM planning.phase_plan_results WHERE schedule_solution_id=:solution AND required_operation_phase_id=:phase"), {"solution": result.solution_id, "phase": phase_b})
    blockers = explanation["why_not_earlier"]
    assert "CUMULATIVE_CAPACITY_EXHAUSTED" in blockers
    assert any(item.startswith("CUMULATIVE_CAPACITY_EXHAUSTED:") and "available_at=" in item for item in blockers)


def test_simple_installation_can_span_workdays_and_compete_for_people(engine, seeded_case):
    _configure(engine, seeded_case, minutes=600)
    result = generate(engine, seeded_case)
    rows = solution_segments(engine, result.solution_id)
    assert [row.work_minutes for row in rows] == [480, 120]
    assert rows[1].start_at == HORIZON_START + timedelta(days=1)


def test_same_inputs_keep_same_cumulative_assignments(engine, seeded_case):
    _configure(engine, seeded_case, demand=2, minutes=240)
    with engine.begin() as connection:
        _add(connection, seeded_case, "B", demand=1)
        _add(connection, seeded_case, "C", demand=1)
    first, second = generate(engine, seeded_case), generate(engine, seeded_case)
    assert first.solution_sha256 == second.solution_sha256


def test_cumulative_reservation_records_demand_and_nonexclusive_guard(engine, seeded_case):
    _configure(engine, seeded_case, demand=2)
    result = generate(engine, seeded_case)
    with engine.connect() as connection:
        row = connection.execute(text("SELECT capacity_units,exclusive_guard FROM planning.physical_resource_reservations WHERE schedule_solution_id=:solution"), {"solution": result.solution_id}).one()
    assert row == (2, False)


@pytest.mark.parametrize(
    ("label", "project_count", "operation_count", "reservation_count"),
    (("small", 3, 12, 2), ("moderate", 20, 100, 20)),
)
def test_postgresql_cumulative_benchmark(
    engine, seeded_case, label, project_count, operation_count, reservation_count, capsys
):
    _configure(engine, seeded_case, capacity=3, minutes=60)
    projects = [(seeded_case.project_id, seeded_case.project_lot_id)]
    with engine.begin() as connection:
        customer, priority = connection.execute(text("""
            SELECT customer_id,priority_id FROM core.projects
            WHERE organization_id=:org AND id=:project
        """), {"org": seeded_case.organization_id, "project": seeded_case.project_id}).one()
        for number in range(1, project_count):
            project_id, lot_id = uuid4(), uuid4()
            connection.execute(text("""
                INSERT INTO core.projects
                  (id,organization_id,plant_id,customer_id,code,name,priority_id,status)
                VALUES (:id,:org,:plant,:customer,:code,:code,:priority,'active')
            """), {"id": project_id, "org": seeded_case.organization_id,
                    "plant": seeded_case.plant_id, "customer": customer,
                    "code": f"BENCH-P-{number:03d}-{project_id.hex[:6]}", "priority": priority})
            connection.execute(text("""
                INSERT INTO core.project_lots
                  (id,organization_id,project_id,code,name,sequence_no,status,hardware_status)
                VALUES (:id,:org,:project,:code,:code,1,'active','ready')
            """), {"id": lot_id, "org": seeded_case.organization_id,
                    "project": project_id, "code": f"BENCH-L-{number:03d}-{lot_id.hex[:6]}"})
            projects.append((project_id, lot_id))
        for number in range(1, operation_count):
            project_id, lot_id = projects[number % project_count]
            add_operation(
                connection, seeded_case, f"BENCH-OP-{number:04d}", project_id=project_id,
                lot_id=lot_id, minutes=60 + (number % 4) * 15,
                resource_type_id=seeded_case.resource_type_id,
            )
        for number in range(reservation_count):
            segment_id = uuid4()
            start = HORIZON_START + timedelta(hours=number)
            finish = start + timedelta(hours=1)
            connection.execute(text("""
                INSERT INTO execution.execution_segments
                  (id,organization_id,operation_execution_id,required_operation_phase_id,
                   segment_no,time_range,segment_kind,work_minutes)
                VALUES (:id,:org,:execution,:phase,:number,tstzrange(:start,:finish,'[)'),'work',60)
            """), {"id": segment_id, "org": seeded_case.organization_id,
                    "execution": seeded_case.execution_id, "phase": seeded_case.phase_id,
                    "number": number + 2, "start": start, "finish": finish})
            connection.execute(text("""
                INSERT INTO execution.actual_resource_usages
                  (organization_id,execution_segment_id,physical_resource_id,time_range,
                   work_minutes,capacity_units,usage_kind)
                VALUES (:org,:segment,:resource,tstzrange(:start,:finish,'[)'),60,1,'active_use')
            """), {"org": seeded_case.organization_id, "segment": segment_id,
                    "resource": seeded_case.physical_resource_id,
                    "start": start, "finish": finish})
    started = perf_counter()
    result = generate(
        engine, seeded_case, project_ids=tuple(project for project, _ in projects),
        end=HORIZON_START + timedelta(days=60),
    )
    elapsed_ms = (perf_counter() - started) * 1000
    print(
        f"postgres_benchmark={label} projects={project_count} operations={operation_count} "
        f"resources=1 people=1 reservations={reservation_count} elapsed_ms={elapsed_ms:.2f}"
    )
    assert result.complete
    assert elapsed_ms < 5000
