from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import text

from production_besten.domain.errors import EntityNotFound, SchedulingBaseStale
from production_besten.application.scheduling_services import GenerateScheduleService
from production_besten.domain.scheduling.models import GenerateSchedule
from production_besten.persistence.scheduling_uow import PostgresSchedulingUnitOfWorkFactory
from tests.integration.scheduling_helpers import (
    HORIZON_START, add_employee, add_operation, add_resource, current_state,
    generate, prepare_basic, required_operation_id, solution_segments,
)


def test_creates_ready_scenario_and_solution_without_publishing_plan(engine, seeded_case):
    prepare_basic(engine, seeded_case)
    before = seeded_case.plan_version_id
    result = generate(engine, seeded_case)
    with engine.connect() as connection:
        row = connection.execute(text("SELECT s.status,x.status,x.algorithm_version FROM planning.scenarios s JOIN planning.schedule_solutions x ON x.organization_id=s.organization_id AND x.scenario_id=s.id WHERE s.id=:id"), {"id": result.scenario_id}).one()
        current = connection.scalar(text("SELECT current_plan_version_id FROM core.plants WHERE id=:id"), {"id": seeded_case.plant_id})
    assert result.status == "ready" and result.complete
    assert row == ("ready", "ready", "v1-greedy-4")
    assert current == before


def test_persists_frozen_input_and_hashes(engine, seeded_case):
    prepare_basic(engine, seeded_case)
    result = generate(engine, seeded_case)
    with engine.connect() as connection:
        row = connection.execute(text("SELECT input_snapshot,octet_length(input_sha256),octet_length(solution_sha256) FROM planning.schedule_solutions WHERE id=:id"), {"id": result.solution_id}).one()
    assert row[0]["scheduler_version"] == "v1-greedy-4"
    assert "capacity_and_state" in row[0] and "product_definition" in row[0]
    assert row[1:] == (32, 32)


def test_assigns_person_with_required_skill(engine, seeded_case):
    prepare_basic(engine, seeded_case)
    result = generate(engine, seeded_case)
    with engine.connect() as connection:
        assigned = connection.scalar(text("SELECT employee_id FROM planning.human_segment_assignments WHERE schedule_solution_id=:id LIMIT 1"), {"id": result.solution_id})
    assert assigned == seeded_case.employee_id


def test_reserves_exclusive_physical_resource(engine, seeded_case):
    prepare_basic(engine, seeded_case)
    result = generate(engine, seeded_case)
    with engine.connect() as connection:
        reservation = connection.execute(text("SELECT physical_resource_id,usage_mode FROM planning.physical_resource_reservations WHERE schedule_solution_id=:id LIMIT 1"), {"id": result.solution_id}).one()
    assert reservation == (seeded_case.physical_resource_id, "active_use")


def test_long_phase_splits_only_inside_working_days(engine, seeded_case):
    prepare_basic(engine, seeded_case, minutes=600)
    result = generate(engine, seeded_case)
    segments = solution_segments(engine, result.solution_id)
    assert [(x.start_at, x.end_at, x.work_minutes) for x in segments] == [
        (HORIZON_START, HORIZON_START + timedelta(hours=8), 480),
        (HORIZON_START + timedelta(days=1), HORIZON_START + timedelta(days=1, hours=2), 120),
    ]


def test_physical_occupation_spans_night_without_human_night_work(engine, seeded_case):
    prepare_basic(engine, seeded_case, minutes=600, usage_mode="occupation")
    result = generate(engine, seeded_case)
    with engine.connect() as connection:
        occupation = connection.execute(text("SELECT lower(time_range),upper(time_range) FROM planning.physical_occupations WHERE schedule_solution_id=:id"), {"id": result.solution_id}).one()
        human_minutes = connection.scalar(text("SELECT sum(work_minutes) FROM planning.human_segment_assignments WHERE schedule_solution_id=:id"), {"id": result.solution_id})
    assert occupation == (HORIZON_START, HORIZON_START + timedelta(days=1, hours=2))
    assert human_minutes == 600


def test_operation_precedence_delays_successor(engine, seeded_case):
    predecessor = prepare_basic(engine, seeded_case)
    with engine.begin() as connection:
        successor, successor_phase = add_operation(connection, seeded_case, f"NEXT-{uuid4().hex[:6]}", minutes=60, skill_id=seeded_case.skill_id, resource_type_id=seeded_case.resource_type_id)
        connection.execute(text("INSERT INTO production.operation_precedences(organization_id,predecessor_operation_id,successor_operation_id,lag_minutes,source) VALUES (:org,:pre,:post,30,'test')"), {"org": seeded_case.organization_id, "pre": predecessor, "post": successor})
    result = generate(engine, seeded_case)
    with engine.connect() as connection:
        rows = connection.execute(text("SELECT required_operation_phase_id,(explanation->>'ready_at')::timestamptz FROM planning.phase_plan_results WHERE schedule_solution_id=:id"), {"id": result.solution_id}).all()
        segment = connection.execute(text("SELECT lower(s.time_range) FROM planning.assignment_segments s JOIN planning.planned_phase_assignments a ON a.id=s.planned_phase_assignment_id JOIN planning.phase_plan_results p ON p.id=a.phase_plan_result_id WHERE s.schedule_solution_id=:solution AND p.required_operation_phase_id=:phase"), {"solution": result.solution_id, "phase": successor_phase}).one()
    assert dict(rows)[successor_phase] == HORIZON_START + timedelta(hours=2, minutes=30)
    assert segment[0] == HORIZON_START + timedelta(hours=2, minutes=30)


def test_multiple_phases_preserve_sequence(engine, seeded_case):
    operation = prepare_basic(engine, seeded_case)
    with engine.begin() as connection:
        phase2 = uuid4()
        connection.execute(text("INSERT INTO production.required_operation_phases(id,organization_id,required_operation_id,sequence_no,code,name,estimate_kind,original_estimate_minutes,split_policy,status) VALUES (:id,:org,:op,2,'P2','P2','elapsed',60,'splittable','active')"), {"id": phase2, "org": seeded_case.organization_id, "op": operation})
    result = generate(engine, seeded_case)
    rows = solution_segments(engine, result.solution_id)
    starts = {row.required_operation_phase_id: row.start_at for row in rows}
    assert starts[phase2] == HORIZON_START + timedelta(hours=2)


def test_missing_skill_blocks_phase_explainably(engine, seeded_case):
    prepare_basic(engine, seeded_case)
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM capacity.employee_skills WHERE organization_id=:org AND employee_id=:employee"), {"org": seeded_case.organization_id, "employee": seeded_case.employee_id})
    result = generate(engine, seeded_case)
    with engine.connect() as connection:
        row = connection.execute(text("SELECT result_status,explanation FROM planning.phase_plan_results WHERE schedule_solution_id=:id"), {"id": result.solution_id}).one()
    assert row[0] == "blocked"
    assert "REQUIRED_SKILL_UNAVAILABLE" in row[1]["why_not_earlier"]


def test_two_required_people_wait_until_both_available(engine, seeded_case):
    prepare_basic(engine, seeded_case)
    with engine.begin() as connection:
        second = add_employee(connection, seeded_case, f"EMP2-{uuid4().hex[:6]}", skill_id=seeded_case.skill_id)
        connection.execute(text("UPDATE production.operation_labor_requirements SET min_people=2,max_people=2 WHERE organization_id=:org AND required_operation_phase_id=:phase"), {"org": seeded_case.organization_id, "phase": seeded_case.phase_id})
        connection.execute(text("INSERT INTO capacity.resource_unavailabilities(organization_id,employee_id,time_range,reason_code) VALUES (:org,:employee,tstzrange(:start,:end,'[)'),'test')"), {"org": seeded_case.organization_id, "employee": second, "start": HORIZON_START, "end": HORIZON_START + timedelta(hours=2)})
    result = generate(engine, seeded_case)
    segments = solution_segments(engine, result.solution_id)
    assert segments[0].start_at == HORIZON_START + timedelta(hours=2)
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM planning.human_segment_assignments WHERE schedule_solution_id=:id"), {"id": result.solution_id}) == 2


def test_alternative_resource_uses_lexically_stable_choice(engine, seeded_case):
    prepare_basic(engine, seeded_case)
    with engine.begin() as connection:
        preferred = add_resource(connection, seeded_case, "AAA-BENCH")
    result = generate(engine, seeded_case)
    with engine.connect() as connection:
        chosen = connection.scalar(text("SELECT physical_resource_id FROM planning.physical_resource_reservations WHERE schedule_solution_id=:id"), {"id": result.solution_id})
    assert chosen == preferred


def test_alternative_resource_skips_unavailable_preferred(engine, seeded_case):
    prepare_basic(engine, seeded_case)
    with engine.begin() as connection:
        preferred = add_resource(connection, seeded_case, "AAA-BENCH")
        connection.execute(text("INSERT INTO capacity.resource_unavailabilities(organization_id,physical_resource_id,time_range,reason_code) VALUES (:org,:resource,tstzrange(:start,:end,'[)'),'maintenance')"), {"org": seeded_case.organization_id, "resource": preferred, "start": HORIZON_START, "end": HORIZON_START + timedelta(hours=8)})
    result = generate(engine, seeded_case)
    with engine.connect() as connection:
        chosen = connection.scalar(text("SELECT physical_resource_id FROM planning.physical_resource_reservations WHERE schedule_solution_id=:id"), {"id": result.solution_id})
    assert chosen == seeded_case.physical_resource_id


def test_calendar_delays_start_without_creating_fake_work(engine, seeded_case):
    prepare_basic(engine, seeded_case)
    start = HORIZON_START - timedelta(hours=2)
    result = generate(engine, seeded_case, start=start, end=start + timedelta(days=2))
    assert solution_segments(engine, result.solution_id)[0].start_at == HORIZON_START


def test_calendar_exception_removes_holiday(engine, seeded_case):
    prepare_basic(engine, seeded_case)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO capacity.calendar_exceptions(organization_id,calendar_id,exception_date,effect,reason) VALUES (:org,:calendar,:day,'remove','holiday')"), {"org": seeded_case.organization_id, "calendar": seeded_case.calendar_id, "day": HORIZON_START.date()})
    result = generate(engine, seeded_case)
    assert solution_segments(engine, result.solution_id)[0].start_at == HORIZON_START + timedelta(days=1)


def test_out_of_horizon_keeps_valid_partial_segments(engine, seeded_case):
    prepare_basic(engine, seeded_case, minutes=600)
    result = generate(engine, seeded_case, end=HORIZON_START + timedelta(hours=4))
    segments = solution_segments(engine, result.solution_id)
    with engine.connect() as connection:
        phase = connection.execute(text("SELECT result_status,planned_work_minutes,remaining_work_minutes FROM planning.phase_plan_results WHERE schedule_solution_id=:id"), {"id": result.solution_id}).one()
    assert result.complete is False and result.out_of_horizon_phases == 1
    assert phase == ("out_of_horizon", 240, 360)
    assert len(segments) == 1 and segments[0].work_minutes == 240


def test_work_outside_calendar_is_rejected_without_overtime(engine, seeded_case):
    prepare_basic(engine, seeded_case)
    start = HORIZON_START + timedelta(hours=8)
    result = generate(engine, seeded_case, start=start, end=start + timedelta(hours=2))
    assert not result.complete and result.out_of_horizon_phases == 1
    assert solution_segments(engine, result.solution_id) == []


def test_authorized_overtime_is_used_and_traced(engine, seeded_case):
    prepare_basic(engine, seeded_case)
    start = HORIZON_START + timedelta(hours=8)
    authorization = uuid4()
    with engine.begin() as connection:
        connection.execute(text("""
            INSERT INTO capacity.overtime_authorizations
              (id,organization_id,plant_id,project_id,time_range,max_minutes,approved_by,reason)
            VALUES (:id,:org,:plant,:project,tstzrange(:start,:end,'[)'),120,:actor,'urgent')
        """), {"id": authorization, "org": seeded_case.organization_id,
                "plant": seeded_case.plant_id, "project": seeded_case.project_id,
                "start": start, "end": start + timedelta(hours=2), "actor": seeded_case.actor_id})
    result = generate(engine, seeded_case, start=start, end=start + timedelta(hours=2))
    segment = solution_segments(engine, result.solution_id)[0]
    with engine.connect() as connection:
        human = connection.scalar(text("SELECT overtime_authorization_id FROM planning.human_segment_assignments WHERE schedule_solution_id=:id"), {"id": result.solution_id})
        physical = connection.scalar(text("SELECT overtime_authorization_id FROM planning.physical_resource_reservations WHERE schedule_solution_id=:id"), {"id": result.solution_id})
    assert segment.overtime_minutes == 120
    assert human == authorization and physical == authorization


def test_known_material_release_delays_but_does_not_block(engine, seeded_case):
    operation = prepare_basic(engine, seeded_case)
    release = HORIZON_START + timedelta(hours=2)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO production.operation_gates(organization_id,required_operation_id,required_operation_phase_id,timing,gate_type,available_at) VALUES (:org,:op,:phase,'before_start','MATERIAL_READY',:release)"), {"org": seeded_case.organization_id, "op": operation, "phase": seeded_case.phase_id, "release": release})
    result = generate(engine, seeded_case)
    assert solution_segments(engine, result.solution_id)[0].start_at == release
    with engine.connect() as connection:
        explanation = connection.scalar(text("SELECT explanation FROM planning.phase_plan_results WHERE schedule_solution_id=:id"), {"id": result.solution_id})
    assert "MATERIAL_NOT_AVAILABLE" in explanation["why_not_earlier"]


@pytest.mark.parametrize("gate_kind", ["hardware", "drawing", "material"])
def test_unknown_gate_blocks_with_specific_reason(engine, seeded_case, gate_kind):
    operation = prepare_basic(engine, seeded_case)
    expected = {"hardware": "HARDWARE_NOT_AVAILABLE", "drawing": "DRAWINGS_NOT_AVAILABLE", "material": "MATERIAL_NOT_AVAILABLE"}[gate_kind]
    with engine.begin() as connection:
        if gate_kind == "hardware":
            connection.execute(text("UPDATE core.project_lots SET hardware_status='pending',hardware_available_at=NULL WHERE organization_id=:org AND id=:lot"), {"org": seeded_case.organization_id, "lot": seeded_case.project_lot_id})
            column, target = "hardware_project_lot_id", seeded_case.project_lot_id
        elif gate_kind == "drawing":
            target = uuid4(); column = "drawing_package_id"
            connection.execute(text("INSERT INTO production.drawing_packages(id,organization_id,project_lot_id,code,name,status) VALUES (:id,:org,:lot,:code,'Drawing','active')"), {"id": target, "org": seeded_case.organization_id, "lot": seeded_case.project_lot_id, "code": f"DR-{target.hex[:6]}"})
        else:
            target = uuid4(); column = "material_requirement_id"
            connection.execute(text("INSERT INTO production.material_requirements(id,organization_id,project_lot_id,code,description,required_quantity,unit) VALUES (:id,:org,:lot,:code,'Material',1,'unit')"), {"id": target, "org": seeded_case.organization_id, "lot": seeded_case.project_lot_id, "code": f"MAT-{target.hex[:6]}"})
        connection.execute(text(f"INSERT INTO production.operation_gates(organization_id,required_operation_id,required_operation_phase_id,timing,gate_type,{column}) VALUES (:org,:op,:phase,'before_start',:kind,:target)"), {"org": seeded_case.organization_id, "op": operation, "phase": seeded_case.phase_id, "kind": gate_kind.upper(), "target": target})
    result = generate(engine, seeded_case)
    with engine.connect() as connection:
        row = connection.execute(text("SELECT result_status,explanation FROM planning.phase_plan_results WHERE schedule_solution_id=:id"), {"id": result.solution_id}).one()
    assert row[0] == "blocked" and expected in row[1]["why_not_earlier"]


def test_two_projects_share_capacity_by_priority(engine, seeded_case):
    prepare_basic(engine, seeded_case)
    with engine.begin() as connection:
        customer = connection.scalar(text("SELECT customer_id FROM core.projects WHERE organization_id=:org AND id=:project"), {"org": seeded_case.organization_id, "project": seeded_case.project_id})
        high_priority, project, lot = uuid4(), uuid4(), uuid4()
        connection.execute(text("INSERT INTO core.project_priorities(id,organization_id,code,name,rank) VALUES (:id,:org,'HIGH','High',2)"), {"id": high_priority, "org": seeded_case.organization_id})
        connection.execute(text("INSERT INTO core.projects(id,organization_id,plant_id,customer_id,code,name,priority_id,status) VALUES (:id,:org,:plant,:customer,:code,'High',:priority,'active')"), {"id": project, "org": seeded_case.organization_id, "plant": seeded_case.plant_id, "customer": customer, "code": f"HIGH-{project.hex[:6]}", "priority": high_priority})
        connection.execute(text("INSERT INTO core.project_lots(id,organization_id,project_id,code,name,sequence_no,status,hardware_status) VALUES (:id,:org,:project,:code,'Lot',1,'active','ready')"), {"id": lot, "org": seeded_case.organization_id, "project": project, "code": f"LOT-{lot.hex[:6]}"})
        _, high_phase = add_operation(connection, seeded_case, f"HIGH-OP-{uuid4().hex[:6]}", project_id=project, lot_id=lot, skill_id=seeded_case.skill_id, resource_type_id=seeded_case.resource_type_id)
    result = generate(engine, seeded_case, project_ids=(seeded_case.project_id, project))
    starts = {row.required_operation_phase_id: row.start_at for row in solution_segments(engine, result.solution_id)}
    assert starts[high_phase] == HORIZON_START
    assert starts[seeded_case.phase_id] == HORIZON_START + timedelta(hours=2)


def test_different_people_and_resources_allow_simultaneous_work(engine, seeded_case):
    prepare_basic(engine, seeded_case)
    with engine.begin() as connection:
        # Two independent stations also require two units of center capacity.
        connection.execute(text("UPDATE capacity.work_centers SET aggregate_capacity=2 WHERE organization_id=:org AND id=:id"),
                           {"org": seeded_case.organization_id, "id": seeded_case.work_center_id})
        skill2, type2 = uuid4(), uuid4()
        connection.execute(text("INSERT INTO capacity.skills(id,organization_id,code,name) VALUES (:id,:org,:code,'Skill 2')"), {"id": skill2, "org": seeded_case.organization_id, "code": f"SK2-{skill2.hex[:6]}"})
        add_employee(connection, seeded_case, f"ZZ-EMP-{uuid4().hex[:6]}", skill_id=skill2)
        connection.execute(text("INSERT INTO capacity.physical_resource_types(id,organization_id,code,name,resource_kind,default_scheduling_mode,default_capacity_unit) VALUES (:id,:org,:code,'Machine','machine','exclusive','unit')"), {"id": type2, "org": seeded_case.organization_id, "code": f"RT2-{type2.hex[:6]}"})
        add_resource(connection, seeded_case, f"ZZ-RES-{uuid4().hex[:6]}", resource_type_id=type2)
        _, phase2 = add_operation(connection, seeded_case, f"INDEP-{uuid4().hex[:6]}", skill_id=skill2, resource_type_id=type2)
    result = generate(engine, seeded_case)
    starts = {row.required_operation_phase_id: row.start_at for row in solution_segments(engine, result.solution_id)}
    assert starts[seeded_case.phase_id] == starts[phase2] == HORIZON_START


def test_same_input_and_version_produce_same_semantic_solution(engine, seeded_case):
    prepare_basic(engine, seeded_case, minutes=600)
    first = generate(engine, seeded_case)
    second = generate(engine, seeded_case)
    assert first.solution_sha256 == second.solution_sha256
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT input_sha256=(SELECT input_sha256 FROM planning.schedule_solutions WHERE id=:second) FROM planning.schedule_solutions WHERE id=:first"), {"first": first.solution_id, "second": second.solution_id}) is True


def test_precedence_cycle_fails_atomically_without_partial_results(engine, seeded_case):
    first = prepare_basic(engine, seeded_case)
    with engine.begin() as connection:
        second, _ = add_operation(connection, seeded_case, f"CYCLE-{uuid4().hex[:6]}", skill_id=seeded_case.skill_id)
        for predecessor, successor in ((first, second), (second, first)):
            connection.execute(text("INSERT INTO production.operation_precedences(organization_id,predecessor_operation_id,successor_operation_id,source) VALUES (:org,:pre,:post,'test')"), {"org": seeded_case.organization_id, "pre": predecessor, "post": successor})
    result = generate(engine, seeded_case)
    with engine.connect() as connection:
        count = connection.scalar(text("SELECT count(*) FROM planning.operation_plan_results WHERE schedule_solution_id=:id"), {"id": result.solution_id})
    assert result.status == "failed" and result.failed_reason.startswith("PRECEDENCE_CYCLE")
    assert count == 0


def test_stale_planning_base_is_rejected_before_scenario_creation(engine, seeded_case):
    prepare_basic(engine, seeded_case)
    old_state = current_state(engine, seeded_case)
    with engine.begin() as connection:
        number = connection.scalar(text("SELECT current_revision_no+1 FROM planning.planning_state_heads WHERE organization_id=:org AND plant_id=:plant FOR UPDATE"), {"org": seeded_case.organization_id, "plant": seeded_case.plant_id})
        new_state = uuid4()
        connection.execute(text("INSERT INTO planning.planning_state_revisions(id,organization_id,plant_id,revision_no,reason,transaction_key,created_by) VALUES (:id,:org,:plant,:number,'changed',:key,:actor)"), {"id": new_state, "org": seeded_case.organization_id, "plant": seeded_case.plant_id, "number": number, "key": uuid4(), "actor": seeded_case.actor_id})
        connection.execute(text("UPDATE planning.planning_state_heads SET current_revision_id=:id,current_revision_no=:number WHERE organization_id=:org AND plant_id=:plant"), {"id": new_state, "number": number, "org": seeded_case.organization_id, "plant": seeded_case.plant_id})
    with pytest.raises(SchedulingBaseStale):
        generate(engine, seeded_case, state_id=old_state)


def test_cross_organization_is_indistinguishable_from_missing_plant(engine, seeded_case):
    prepare_basic(engine, seeded_case)
    command = GenerateSchedule(seeded_case.other_organization_id, seeded_case.plant_id,
        seeded_case.actor_id, f"X-{uuid4().hex}", "Cross tenant", HORIZON_START,
        HORIZON_START + timedelta(days=1), seeded_case.definition_revision_id,
        seeded_case.initial_state_revision_id, (seeded_case.project_id,))
    service = GenerateScheduleService(PostgresSchedulingUnitOfWorkFactory(engine))
    with pytest.raises(EntityNotFound):
        service.execute(command)


def test_persistence_failure_rolls_back_scenario_solution_and_results(engine, seeded_case):
    prepare_basic(engine, seeded_case)
    with engine.connect() as connection:
        before = connection.scalar(text("SELECT count(*) FROM planning.scenarios WHERE organization_id=:org"), {"org": seeded_case.organization_id})
    with pytest.raises(RuntimeError, match="injected persistence failure"):
        generate(engine, seeded_case, failpoint="after_solution")
    with engine.connect() as connection:
        after = connection.scalar(text("SELECT count(*) FROM planning.scenarios WHERE organization_id=:org"), {"org": seeded_case.organization_id})
    assert after == before


def test_cumulative_resource_is_supported_and_persisted_nonexclusive(engine, seeded_case):
    prepare_basic(engine, seeded_case)
    with engine.begin() as connection:
        connection.execute(text("UPDATE capacity.physical_resources SET scheduling_mode='cumulative',capacity_units=3 WHERE organization_id=:org AND id=:resource"), {"org": seeded_case.organization_id, "resource": seeded_case.physical_resource_id})
    result = generate(engine, seeded_case)
    with engine.connect() as connection:
        reservation = connection.execute(text("SELECT capacity_units,exclusive_guard FROM planning.physical_resource_reservations WHERE schedule_solution_id=:id"), {"id": result.solution_id}).one()
    assert result.complete and reservation == (1, False)


def test_ninety_day_horizon_uses_event_windows_with_basic_performance(engine, seeded_case):
    prepare_basic(engine, seeded_case, minutes=600)
    result = generate(engine, seeded_case, end=HORIZON_START + timedelta(days=90))
    assert result.complete and result.elapsed_ms < 5000


def test_specific_resource_group_waits_instead_of_using_unrelated_alternative(engine, seeded_case):
    prepare_basic(engine, seeded_case)
    with engine.begin() as connection:
        add_resource(connection, seeded_case, "AAA-UNRELATED")
        group = uuid4()
        connection.execute(text("INSERT INTO capacity.physical_resource_groups(id,organization_id,plant_id,code,name,selection_policy) VALUES (:id,:org,:plant,:code,'Only bench 1','first_available')"), {"id": group, "org": seeded_case.organization_id, "plant": seeded_case.plant_id, "code": f"G-{group.hex[:6]}"})
        connection.execute(text("INSERT INTO capacity.physical_resource_group_members(organization_id,group_id,physical_resource_id,valid_during) VALUES (:org,:group,:resource,daterange('2026-01-01','2027-01-01','[)'))"), {"org": seeded_case.organization_id, "group": group, "resource": seeded_case.physical_resource_id})
        connection.execute(text("UPDATE production.operation_physical_requirements SET physical_resource_type_id=NULL,physical_resource_group_id=:group WHERE organization_id=:org AND id=:id"), {"group": group, "org": seeded_case.organization_id, "id": seeded_case.physical_requirement_id})
        connection.execute(text("INSERT INTO capacity.resource_unavailabilities(organization_id,physical_resource_id,time_range,reason_code) VALUES (:org,:resource,tstzrange(:start,:end,'[)'),'occupied')"), {"org": seeded_case.organization_id, "resource": seeded_case.physical_resource_id, "start": HORIZON_START, "end": HORIZON_START + timedelta(hours=2)})
    result = generate(engine, seeded_case)
    segment = solution_segments(engine, result.solution_id)[0]
    with engine.connect() as connection:
        chosen = connection.scalar(text("SELECT physical_resource_id FROM planning.physical_resource_reservations WHERE schedule_solution_id=:id"), {"id": result.solution_id})
    assert chosen == seeded_case.physical_resource_id
    assert segment.start_at == HORIZON_START + timedelta(hours=2)


def test_future_supplier_delivery_releases_material_gate(engine, seeded_case):
    operation = prepare_basic(engine, seeded_case)
    release = HORIZON_START + timedelta(hours=3)
    ids = {name: uuid4() for name in ("requirement", "supplier", "delivery", "line", "allocation")}
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO production.material_requirements(id,organization_id,project_lot_id,code,description,required_quantity,unit) VALUES (:id,:org,:lot,:code,'Panel',2,'unit')"), {"id": ids["requirement"], "org": seeded_case.organization_id, "lot": seeded_case.project_lot_id, "code": f"MAT-{ids['requirement'].hex[:6]}"})
        connection.execute(text("INSERT INTO production.suppliers(id,organization_id,code,name) VALUES (:id,:org,:code,'Supplier')"), {"id": ids["supplier"], "org": seeded_case.organization_id, "code": f"SUP-{ids['supplier'].hex[:6]}"})
        connection.execute(text("INSERT INTO production.supplier_deliveries(id,organization_id,supplier_id,delivered_at,delivery_kind,source_system) VALUES (:id,:org,:supplier,:at,'receipt','test')"), {"id": ids["delivery"], "org": seeded_case.organization_id, "supplier": ids["supplier"], "at": release})
        connection.execute(text("INSERT INTO production.supplier_delivery_lines(id,organization_id,supplier_delivery_id,line_no,material_code,quantity,unit,movement_sign) VALUES (:id,:org,:delivery,1,'PANEL',2,'unit',1)"), {"id": ids["line"], "org": seeded_case.organization_id, "delivery": ids["delivery"]})
        connection.execute(text("INSERT INTO production.material_allocations(id,organization_id,supplier_delivery_line_id,material_requirement_id,quantity,unit,movement_sign) VALUES (:id,:org,:line,:requirement,2,'unit',1)"), {"id": ids["allocation"], "org": seeded_case.organization_id, "line": ids["line"], "requirement": ids["requirement"]})
        connection.execute(text("INSERT INTO production.operation_gates(organization_id,required_operation_id,required_operation_phase_id,timing,gate_type,material_requirement_id) VALUES (:org,:op,:phase,'before_start','MATERIAL_READY',:requirement)"), {"org": seeded_case.organization_id, "op": operation, "phase": seeded_case.phase_id, "requirement": ids["requirement"]})
    result = generate(engine, seeded_case)
    assert solution_segments(engine, result.solution_id)[0].start_at == release


def test_existing_scenario_becomes_detectably_stale_without_recalculation(engine, seeded_case):
    prepare_basic(engine, seeded_case)
    result = generate(engine, seeded_case)
    with engine.begin() as connection:
        number = connection.scalar(text("SELECT current_revision_no+1 FROM planning.planning_state_heads WHERE organization_id=:org AND plant_id=:plant FOR UPDATE"), {"org": seeded_case.organization_id, "plant": seeded_case.plant_id})
        revision = uuid4()
        connection.execute(text("INSERT INTO planning.planning_state_revisions(id,organization_id,plant_id,revision_no,reason,transaction_key,created_by) VALUES (:id,:org,:plant,:number,'later change',:key,:actor)"), {"id": revision, "org": seeded_case.organization_id, "plant": seeded_case.plant_id, "number": number, "key": uuid4(), "actor": seeded_case.actor_id})
        connection.execute(text("UPDATE planning.planning_state_heads SET current_revision_id=:revision,current_revision_no=:number WHERE organization_id=:org AND plant_id=:plant"), {"revision": revision, "number": number, "org": seeded_case.organization_id, "plant": seeded_case.plant_id})
    with engine.connect() as connection:
        stale, status, segments = connection.execute(text("SELECT s.base_state_revision_id<>h.current_revision_id,s.status,(SELECT count(*) FROM planning.assignment_segments x WHERE x.schedule_solution_id=:solution) FROM planning.scenarios s JOIN planning.planning_state_heads h ON h.organization_id=s.organization_id AND h.plant_id=s.plant_id WHERE s.id=:scenario"), {"solution": result.solution_id, "scenario": result.scenario_id}).one()
    assert stale is True and status == "ready" and segments > 0


def test_main_furniture_route_is_feasible_and_explainable(engine, seeded_case):
    cut = prepare_basic(engine, seeded_case, minutes=120)
    with engine.begin() as connection:
        second = add_employee(connection, seeded_case, "CUT-EMP-2", skill_id=seeded_case.skill_id)
        connection.execute(text("UPDATE production.operation_labor_requirements SET min_people=2,max_people=2 WHERE organization_id=:org AND required_operation_phase_id=:phase"), {"org": seeded_case.organization_id, "phase": seeded_case.phase_id})
        edge, drill = add_operation(connection, seeded_case, "EDGE", minutes=60, skill_id=seeded_case.skill_id, resource_type_id=seeded_case.resource_type_id)
        bore, bore_phase = add_operation(connection, seeded_case, "BORE", minutes=60, skill_id=seeded_case.skill_id, resource_type_id=seeded_case.resource_type_id)
        assembly, preassembly = add_operation(connection, seeded_case, "ASSEMBLY", minutes=180, skill_id=seeded_case.skill_id, resource_type_id=seeded_case.resource_type_id)
        finish = uuid4()
        connection.execute(text("INSERT INTO production.required_operation_phases(id,organization_id,required_operation_id,sequence_no,code,name,estimate_kind,original_estimate_minutes,split_policy,status) VALUES (:id,:org,:op,2,'FINISH','Finish','labor',60,'splittable','active')"), {"id": finish, "org": seeded_case.organization_id, "op": assembly})
        connection.execute(text("INSERT INTO production.operation_labor_requirements(organization_id,required_operation_phase_id,skill_id,min_people,max_people,work_minutes) VALUES (:org,:phase,:skill,1,1,60)"), {"org": seeded_case.organization_id, "phase": finish, "skill": seeded_case.skill_id})
        connection.execute(text("INSERT INTO production.operation_physical_requirements(organization_id,required_operation_phase_id,physical_resource_type_id,quantity,capacity_units,usage_mode) VALUES (:org,:phase,:type,1,1,'active_use')"), {"org": seeded_case.organization_id, "phase": finish, "type": seeded_case.resource_type_id})
        for predecessor, successor in ((cut, edge), (edge, bore), (bore, assembly)):
            connection.execute(text("INSERT INTO production.operation_precedences(organization_id,predecessor_operation_id,successor_operation_id,source) VALUES (:org,:pre,:post,'route')"), {"org": seeded_case.organization_id, "pre": predecessor, "post": successor})
        connection.execute(text("INSERT INTO production.operation_gates(organization_id,required_operation_id,required_operation_phase_id,timing,gate_type,hardware_project_lot_id) VALUES (:org,:op,:phase,'before_start','HARDWARE_READY',:lot)"), {"org": seeded_case.organization_id, "op": assembly, "phase": finish, "lot": seeded_case.project_lot_id})
    result = generate(engine, seeded_case)
    segments = solution_segments(engine, result.solution_id)
    starts = {row.required_operation_phase_id: row.start_at for row in segments}
    assert result.complete and result.planned_phases == 5
    assert starts[seeded_case.phase_id] < starts[drill] < starts[bore_phase] < starts[preassembly] < starts[finish]
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM planning.phase_plan_results WHERE schedule_solution_id=:id AND jsonb_typeof(explanation)='object'"), {"id": result.solution_id}) == 5


def test_scalable_labor_shortens_duration_only_when_configured(engine, seeded_case):
    operation = prepare_basic(engine, seeded_case, minutes=120)
    with engine.begin() as connection:
        add_employee(connection, seeded_case, "SCALE-EMP-2", skill_id=seeded_case.skill_id)
        connection.execute(text("UPDATE production.operation_labor_requirements SET min_people=1,max_people=2 WHERE organization_id=:org AND required_operation_phase_id=:phase"), {"org": seeded_case.organization_id, "phase": seeded_case.phase_id})
        connection.execute(text("UPDATE production.required_operations SET settings=CAST(:settings AS jsonb) WHERE organization_id=:org AND id=:operation"), {"settings": '{"scalable_labor":true}', "org": seeded_case.organization_id, "operation": operation})
    result = generate(engine, seeded_case)
    segment = solution_segments(engine, result.solution_id)[0]
    with engine.connect() as connection:
        people = connection.scalar(text("SELECT count(*) FROM planning.human_segment_assignments WHERE schedule_solution_id=:id"), {"id": result.solution_id})
    assert segment.work_minutes == 60 and people == 2


def test_employee_calendar_is_intersected_with_plant_and_resource(engine, seeded_case):
    prepare_basic(engine, seeded_case)
    calendar = uuid4()
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO capacity.calendars(id,organization_id,code,name,timezone,calendar_kind) VALUES (:id,:org,:code,'Late shift','UTC','employee')"), {"id": calendar, "org": seeded_case.organization_id, "code": f"LATE-{calendar.hex[:6]}"})
        for weekday in range(1, 6):
            connection.execute(text("INSERT INTO capacity.calendar_working_intervals(organization_id,calendar_id,weekday,local_start,local_end,valid_during) VALUES (:org,:calendar,:weekday,'10:00','16:00',daterange('2026-01-01','2027-01-01','[)'))"), {"org": seeded_case.organization_id, "calendar": calendar, "weekday": weekday})
        connection.execute(text("UPDATE capacity.employees SET base_calendar_id=:calendar WHERE organization_id=:org AND id=:employee"), {"calendar": calendar, "org": seeded_case.organization_id, "employee": seeded_case.employee_id})
    result = generate(engine, seeded_case)
    assert solution_segments(engine, result.solution_id)[0].start_at == HORIZON_START + timedelta(hours=2)


def test_overtime_max_minutes_caps_authorized_window(engine, seeded_case):
    prepare_basic(engine, seeded_case, minutes=120)
    start = HORIZON_START + timedelta(hours=8)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO capacity.overtime_authorizations(organization_id,plant_id,project_id,time_range,max_minutes,approved_by,reason) VALUES (:org,:plant,:project,tstzrange(:start,:end,'[)'),60,:actor,'limited')"), {"org": seeded_case.organization_id, "plant": seeded_case.plant_id, "project": seeded_case.project_id, "start": start, "end": start + timedelta(hours=2), "actor": seeded_case.actor_id})
    result = generate(engine, seeded_case, start=start, end=start + timedelta(hours=2))
    assert result.complete is False
    segments = solution_segments(engine, result.solution_id)
    assert len(segments) == 1 and segments[0].work_minutes == 60
