from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import Engine, text

from production_besten.application.execution_services import (
    FinishOperationService,
    RegisterExecutionSegmentService,
    StartOperationService,
)
from production_besten.application.update_remaining_estimate import UpdateRemainingEstimateService
from production_besten.domain.errors import (
    EntityNotFound,
    ExecutionAlreadyActive,
    ExecutionAlreadyCompleted,
    GateBlocked,
    InvalidExecutionState,
)
from production_besten.domain.execution import (
    FinishOperation,
    HumanUsage,
    PhysicalOccupation,
    PhysicalUsage,
    RegisterExecutionSegment,
    StartOperation,
)
from production_besten.domain.remaining_estimate import (
    RemainingDimension,
    RemainingResourceInput,
    UpdateRemainingEstimate,
)
from production_besten.persistence.execution_uow import PostgresExecutionUnitOfWorkFactory
from production_besten.persistence.remaining_estimate_uow import PostgresUnitOfWorkFactory

from .conftest import SeededCase, seed_case
from .execution_helpers import UnstartedCase, create_unstarted_case, start_case


def segment_command(
    case: UnstartedCase,
    execution_id,
    *,
    phase_index: int = 0,
    started_offset: int = 0,
    duration: int = 120,
    human_minutes: int | None = None,
    occupations=(),
    command_id=None,
    origin=True,
) -> RegisterExecutionSegment:
    started = case.started_at + timedelta(minutes=started_offset)
    return RegisterExecutionSegment(
        organization_id=case.base.organization_id,
        operation_execution_id=execution_id,
        phase_id=case.phase_ids[phase_index],
        started_at=started,
        ended_at=started + timedelta(minutes=duration),
        work_minutes=duration,
        actor_id=case.base.actor_id,
        command_id=command_id or uuid4(),
        humans=(HumanUsage(case.actual_employee_id, human_minutes if human_minutes is not None else duration),),
        physical_usages=(PhysicalUsage(case.actual_resource_id, duration),),
        occupations=occupations,
        origin_assignment_segment_id=case.assignment_segment_id if origin else None,
    )


def finish_command(case: UnstartedCase, execution_id, *, phase_index: int = 0, at_offset: int = 120, command_id=None) -> FinishOperation:
    return FinishOperation(
        organization_id=case.base.organization_id,
        operation_execution_id=execution_id,
        phase_id=case.phase_ids[phase_index],
        completed_at=case.started_at + timedelta(minutes=at_offset),
        actor_id=case.base.actor_id,
        command_id=command_id or uuid4(),
    )


def test_start_normal_with_plan_preserves_origin(engine: Engine, seeded_case: SeededCase) -> None:
    case = create_unstarted_case(engine, seeded_case, planned=True)

    result = start_case(engine, case)

    with engine.connect() as connection:
        row = connection.execute(text("SELECT status,origin_plan_version_id,origin_operation_plan_result_id,source_event_id,original_estimate_snapshot->>'labor_minutes' FROM execution.operation_executions WHERE organization_id=:org AND id=:id"), {"org": seeded_case.organization_id, "id": result.operation_execution_id}).one()
        head = connection.scalar(text("SELECT current_revision_no FROM planning.planning_state_heads WHERE organization_id=:org AND plant_id=:plant"), {"org": seeded_case.organization_id, "plant": seeded_case.plant_id})
    assert row == ("running", seeded_case.plan_version_id, case.operation_plan_result_id, result.event_id, "480")
    assert head == 2


def test_start_without_planning_and_idempotent_retry(engine: Engine, seeded_case: SeededCase) -> None:
    case = create_unstarted_case(engine, seeded_case)
    command_id = uuid4()

    first = start_case(engine, case, command_id=command_id)
    second = start_case(engine, case, command_id=command_id)

    assert second.operation_execution_id == first.operation_execution_id
    assert second.event_id == first.event_id
    assert second.idempotent_replay is True
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM execution.operation_executions WHERE organization_id=:org AND required_operation_id=:operation"), {"org": seeded_case.organization_id, "operation": case.operation_id}) == 1
        assert connection.scalar(text("SELECT origin_plan_version_id IS NULL FROM execution.operation_executions WHERE organization_id=:org AND id=:execution"), {"org": seeded_case.organization_id, "execution": first.operation_execution_id}) is True


def test_register_real_segment_and_usages(engine: Engine, seeded_case: SeededCase) -> None:
    case = create_unstarted_case(engine, seeded_case, planned=True)
    started = start_case(engine, case)

    result = RegisterExecutionSegmentService(PostgresExecutionUnitOfWorkFactory(engine)).execute(segment_command(case, started.operation_execution_id))

    with engine.connect() as connection:
        segment = connection.execute(text("SELECT segment_no,origin_assignment_segment_id,work_minutes,source_event_id FROM execution.execution_segments WHERE organization_id=:org AND id=:id"), {"org": seeded_case.organization_id, "id": result.segment_id}).one()
        usages = connection.execute(text("SELECT employee_id,physical_resource_id,usage_kind FROM execution.actual_resource_usages WHERE organization_id=:org AND execution_segment_id=:segment ORDER BY usage_kind"), {"org": seeded_case.organization_id, "segment": result.segment_id}).all()
    assert segment == (1, case.assignment_segment_id, 120, result.event_id)
    assert usages == [(None, case.actual_resource_id, "active_use"), (case.actual_employee_id, None, "labor")]


def test_multiple_real_workdays_remain_separate(engine: Engine, seeded_case: SeededCase) -> None:
    case = create_unstarted_case(engine, seeded_case)
    execution = start_case(engine, case).operation_execution_id
    service = RegisterExecutionSegmentService(PostgresExecutionUnitOfWorkFactory(engine))
    service.execute(segment_command(case, execution, started_offset=0, duration=210))
    service.execute(segment_command(case, execution, started_offset=270, duration=180))
    service.execute(segment_command(case, execution, started_offset=1440, duration=90))

    with engine.connect() as connection:
        rows = connection.execute(text("SELECT segment_no,lower(time_range),upper(time_range),work_minutes FROM execution.execution_segments WHERE organization_id=:org AND operation_execution_id=:execution ORDER BY segment_no"), {"org": seeded_case.organization_id, "execution": execution}).all()
    assert [row.segment_no for row in rows] == [1, 2, 3]
    assert [row.work_minutes for row in rows] == [210, 180, 90]
    assert rows[0][2] < rows[1][1] < rows[2][1]


def test_actual_people_can_differ_from_planned_people(engine: Engine, seeded_case: SeededCase) -> None:
    case = create_unstarted_case(engine, seeded_case, planned=True)
    execution = start_case(engine, case).operation_execution_id
    result = RegisterExecutionSegmentService(PostgresExecutionUnitOfWorkFactory(engine)).execute(segment_command(case, execution))

    with engine.connect() as connection:
        planned = connection.scalar(text("SELECT employee_id FROM planning.human_segment_assignments WHERE organization_id=:org AND assignment_segment_id=:segment"), {"org": seeded_case.organization_id, "segment": case.assignment_segment_id})
        actual = connection.scalar(text("SELECT employee_id FROM execution.actual_resource_usages WHERE organization_id=:org AND execution_segment_id=:segment AND employee_id IS NOT NULL"), {"org": seeded_case.organization_id, "segment": result.segment_id})
    assert planned == case.planned_employee_id
    assert actual == case.actual_employee_id
    assert actual != planned


def test_actual_resource_can_differ_from_planned_resource(engine: Engine, seeded_case: SeededCase) -> None:
    case = create_unstarted_case(engine, seeded_case, planned=True)
    execution = start_case(engine, case).operation_execution_id
    result = RegisterExecutionSegmentService(PostgresExecutionUnitOfWorkFactory(engine)).execute(segment_command(case, execution))

    with engine.connect() as connection:
        planned = connection.scalar(text("SELECT physical_resource_id FROM planning.physical_resource_reservations WHERE organization_id=:org AND assignment_segment_id=:segment"), {"org": seeded_case.organization_id, "segment": case.assignment_segment_id})
        actual = connection.scalar(text("SELECT physical_resource_id FROM execution.actual_resource_usages WHERE organization_id=:org AND execution_segment_id=:segment AND physical_resource_id IS NOT NULL"), {"org": seeded_case.organization_id, "segment": result.segment_id})
    assert planned == case.planned_resource_id
    assert actual == case.actual_resource_id
    assert actual != planned


def test_overnight_occupation_does_not_create_human_work(engine: Engine, seeded_case: SeededCase) -> None:
    case = create_unstarted_case(engine, seeded_case)
    execution = start_case(engine, case).operation_execution_id
    released = case.started_at + timedelta(days=3, hours=1, minutes=30)
    occupation = PhysicalOccupation(case.actual_resource_id, case.started_at, released)
    RegisterExecutionSegmentService(PostgresExecutionUnitOfWorkFactory(engine)).execute(
        segment_command(case, execution, duration=120, occupations=(occupation,))
    )

    with engine.connect() as connection:
        occupied = connection.execute(text("SELECT lower(time_range),upper(time_range) FROM planning.physical_occupations WHERE organization_id=:org AND operation_execution_id=:execution AND source_kind='actual'"), {"org": seeded_case.organization_id, "execution": execution}).one()
        labor = connection.scalar(text("SELECT sum(aru.work_minutes) FROM execution.actual_resource_usages aru JOIN execution.execution_segments s ON s.organization_id=aru.organization_id AND s.id=aru.execution_segment_id WHERE s.organization_id=:org AND s.operation_execution_id=:execution AND aru.employee_id IS NOT NULL"), {"org": seeded_case.organization_id, "execution": execution})
    assert occupied == (case.started_at, released)
    assert labor == 120


def test_finish_normal_is_idempotent_and_keeps_original(engine: Engine, seeded_case: SeededCase) -> None:
    case = create_unstarted_case(engine, seeded_case)
    execution = start_case(engine, case).operation_execution_id
    RegisterExecutionSegmentService(PostgresExecutionUnitOfWorkFactory(engine)).execute(segment_command(case, execution))
    command_id = uuid4()
    command = finish_command(case, execution, command_id=command_id)
    service = FinishOperationService(PostgresExecutionUnitOfWorkFactory(engine))

    first = service.execute(command)
    replay = service.execute(command)

    assert first.operation_completed is True
    assert first.actual_labor_minutes == 120
    assert first.original_labor_minutes == 480
    assert first.variance_labor_minutes == -360
    assert replay.event_id == first.event_id and replay.idempotent_replay
    with engine.connect() as connection:
        row = connection.execute(text("SELECT status,completed_at,original_estimate_snapshot->>'labor_minutes' FROM execution.operation_executions WHERE organization_id=:org AND id=:execution"), {"org": seeded_case.organization_id, "execution": execution}).one()
    assert row == ("completed", command.completed_at, "480")


def test_finish_is_blocked_by_generic_hardware_gate(engine: Engine, seeded_case: SeededCase) -> None:
    case = create_unstarted_case(engine, seeded_case)
    with engine.begin() as connection:
        connection.execute(text("UPDATE core.project_lots SET hardware_status='pending',hardware_available_at=NULL WHERE organization_id=:org AND id=:lot"), {"org": seeded_case.organization_id, "lot": seeded_case.project_lot_id})
        connection.execute(text("INSERT INTO production.operation_gates(organization_id,required_operation_id,required_operation_phase_id,timing,gate_type,hardware_project_lot_id) VALUES (:org,:operation,:phase,'before_finish','HARDWARE_READY',:lot)"), {"org": seeded_case.organization_id, "operation": case.operation_id, "phase": case.phase_ids[0], "lot": seeded_case.project_lot_id})
    execution = start_case(engine, case).operation_execution_id
    RegisterExecutionSegmentService(PostgresExecutionUnitOfWorkFactory(engine)).execute(segment_command(case, execution))

    with pytest.raises(GateBlocked, match="HARDWARE_READY"):
        FinishOperationService(PostgresExecutionUnitOfWorkFactory(engine)).execute(finish_command(case, execution))
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT status::text FROM execution.operation_executions WHERE organization_id=:org AND id=:execution"), {"org": seeded_case.organization_id, "execution": execution}) == "running"


def test_multiphase_completion_keeps_wait_separate(engine: Engine, seeded_case: SeededCase) -> None:
    case = create_unstarted_case(engine, seeded_case, phase_minutes=(120, 120))
    execution = start_case(engine, case).operation_execution_id
    segments = RegisterExecutionSegmentService(PostgresExecutionUnitOfWorkFactory(engine))
    finish = FinishOperationService(PostgresExecutionUnitOfWorkFactory(engine))
    segments.execute(segment_command(case, execution, duration=120))
    first = finish.execute(finish_command(case, execution, phase_index=0, at_offset=120))
    phase_two_start = StartOperationService(PostgresExecutionUnitOfWorkFactory(engine)).execute(
        StartOperation(
            seeded_case.organization_id, case.operation_id, case.phase_ids[1],
            case.started_at + timedelta(minutes=240), seeded_case.actor_id, uuid4()
        )
    )
    segments.execute(segment_command(case, execution, phase_index=1, started_offset=240, duration=120, origin=False))
    second = finish.execute(finish_command(case, execution, phase_index=1, at_offset=360))

    assert first.operation_completed is False
    assert phase_two_start.operation_execution_id == execution
    assert second.operation_completed is True
    with engine.connect() as connection:
        status = connection.scalar(text("SELECT status::text FROM execution.operation_executions WHERE organization_id=:org AND id=:execution"), {"org": seeded_case.organization_id, "execution": execution})
        ranges = connection.execute(text("SELECT lower(time_range),upper(time_range) FROM execution.execution_segments WHERE organization_id=:org AND operation_execution_id=:execution ORDER BY segment_no"), {"org": seeded_case.organization_id, "execution": execution}).all()
    assert status == "completed"
    assert ranges[0][1] < ranges[1][0]


def test_finishes_earlier_than_original_without_rewriting_estimate(engine: Engine, seeded_case: SeededCase) -> None:
    case = create_unstarted_case(engine, seeded_case, phase_minutes=(480,))
    execution = start_case(engine, case).operation_execution_id
    RegisterExecutionSegmentService(PostgresExecutionUnitOfWorkFactory(engine)).execute(segment_command(case, execution, duration=300, human_minutes=300))
    result = FinishOperationService(PostgresExecutionUnitOfWorkFactory(engine)).execute(finish_command(case, execution, at_offset=300))
    assert (result.original_labor_minutes, result.actual_labor_minutes, result.variance_labor_minutes) == (480, 300, -180)


def test_finishes_later_than_original_without_rewriting_history(engine: Engine, seeded_case: SeededCase) -> None:
    case = create_unstarted_case(engine, seeded_case, phase_minutes=(480,))
    execution = start_case(engine, case).operation_execution_id
    RegisterExecutionSegmentService(PostgresExecutionUnitOfWorkFactory(engine)).execute(segment_command(case, execution, duration=660, human_minutes=660))
    result = FinishOperationService(PostgresExecutionUnitOfWorkFactory(engine)).execute(finish_command(case, execution, at_offset=660))
    assert (result.original_labor_minutes, result.actual_labor_minutes, result.variance_labor_minutes) == (480, 660, 180)
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM execution.remaining_estimate_revisions WHERE organization_id=:org AND operation_execution_id=:execution"), {"org": seeded_case.organization_id, "execution": execution}) == 1


def test_cross_tenant_rejected_for_start_segment_people_resource_and_finish(engine: Engine, seeded_case: SeededCase) -> None:
    base_b = seed_case(engine)
    case_b = create_unstarted_case(engine, base_b)
    start_service = StartOperationService(PostgresExecutionUnitOfWorkFactory(engine))
    wrong_start = StartOperation(
        seeded_case.organization_id, case_b.operation_id, case_b.phase_ids[0],
        case_b.started_at, seeded_case.actor_id, uuid4()
    )
    with pytest.raises(EntityNotFound):
        start_service.execute(wrong_start)
    execution_b = start_case(engine, case_b).operation_execution_id
    segment_service = RegisterExecutionSegmentService(PostgresExecutionUnitOfWorkFactory(engine))
    with pytest.raises(EntityNotFound):
        segment_service.execute(replace(segment_command(case_b, execution_b), organization_id=seeded_case.organization_id, actor_id=seeded_case.actor_id))
    with pytest.raises(EntityNotFound):
        segment_service.execute(replace(segment_command(case_b, execution_b), humans=(HumanUsage(seeded_case.employee_id, 120),)))
    with pytest.raises(EntityNotFound):
        segment_service.execute(replace(segment_command(case_b, execution_b), physical_usages=(PhysicalUsage(seeded_case.physical_resource_id, 120),)))
    with pytest.raises(EntityNotFound):
        FinishOperationService(PostgresExecutionUnitOfWorkFactory(engine)).execute(replace(finish_command(case_b, execution_b), organization_id=seeded_case.organization_id, actor_id=seeded_case.actor_id))


def test_two_concurrent_starts_create_one_active_execution(engine: Engine, seeded_case: SeededCase) -> None:
    case = create_unstarted_case(engine, seeded_case)

    def run():
        try:
            return start_case(engine, case)
        except Exception as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = [future.result() for future in (executor.submit(run), executor.submit(run))]
    assert sum(not isinstance(value, Exception) for value in outcomes) == 1
    assert sum(isinstance(value, ExecutionAlreadyActive) for value in outcomes) == 1
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM execution.operation_executions WHERE organization_id=:org AND required_operation_id=:operation AND status IN ('running','paused')"), {"org": seeded_case.organization_id, "operation": case.operation_id}) == 1
        assert connection.scalar(text("SELECT count(*) FROM planning.effective_events WHERE organization_id=:org AND event_type_code='OPERATION_STARTED' AND payload->>'required_operation_id'=:operation"), {"org": seeded_case.organization_id, "operation": str(case.operation_id)}) == 1


def test_two_concurrent_finishes_create_one_completion(engine: Engine, seeded_case: SeededCase) -> None:
    case = create_unstarted_case(engine, seeded_case)
    execution = start_case(engine, case).operation_execution_id
    RegisterExecutionSegmentService(PostgresExecutionUnitOfWorkFactory(engine)).execute(segment_command(case, execution))

    def run():
        try:
            return FinishOperationService(PostgresExecutionUnitOfWorkFactory(engine)).execute(finish_command(case, execution))
        except Exception as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = [future.result() for future in (executor.submit(run), executor.submit(run))]
    assert sum(not isinstance(value, Exception) for value in outcomes) == 1
    assert sum(isinstance(value, ExecutionAlreadyCompleted) for value in outcomes) == 1
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM planning.effective_events WHERE organization_id=:org AND event_type_code='OPERATION_COMPLETED' AND payload->>'operation_execution_id'=:execution"), {"org": seeded_case.organization_id, "execution": str(execution)}) == 1


def test_remaining_estimate_concurrent_with_finish_is_serialized(engine: Engine, seeded_case: SeededCase) -> None:
    case = create_unstarted_case(engine, seeded_case)
    execution = start_case(engine, case).operation_execution_id
    RegisterExecutionSegmentService(PostgresExecutionUnitOfWorkFactory(engine)).execute(segment_command(case, execution))
    update = UpdateRemainingEstimate(
        organization_id=seeded_case.organization_id,
        operation_execution_id=execution,
        expected_revision_no=1,
        cutoff_at=case.started_at + timedelta(minutes=120),
        remaining_labor_minutes=60,
        resources=(RemainingResourceInput(
            phase_id=case.phase_ids[0], dimension=RemainingDimension.LABOR_WORK,
            remaining_minutes=60, skill_id=seeded_case.skill_id, min_people=1, max_people=2,
        ),),
        actor_id=seeded_case.actor_id,
    )

    def update_run():
        try:
            return UpdateRemainingEstimateService(PostgresUnitOfWorkFactory(engine)).execute(update)
        except Exception as error:
            return error

    def finish_run():
        try:
            return FinishOperationService(PostgresExecutionUnitOfWorkFactory(engine)).execute(finish_command(case, execution))
        except Exception as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = [future.result() for future in (executor.submit(update_run), executor.submit(finish_run))]
    finish_success = any(getattr(value, "operation_completed", False) for value in outcomes)
    update_success = any(hasattr(value, "updated_total_labor_minutes") for value in outcomes)
    assert finish_success
    assert update_success or any(isinstance(value, InvalidExecutionState) for value in outcomes)
    with engine.connect() as connection:
        head_no = connection.scalar(text("SELECT current_revision_no FROM planning.planning_state_heads WHERE organization_id=:org AND plant_id=:plant"), {"org": seeded_case.organization_id, "plant": seeded_case.plant_id})
        event_count = connection.scalar(text("SELECT count(*) FROM planning.effective_events WHERE organization_id=:org AND planning_state_revision_id IS NOT NULL"), {"org": seeded_case.organization_id})
        revision_count = connection.scalar(text("SELECT count(*) FROM planning.planning_state_revisions WHERE organization_id=:org AND plant_id=:plant"), {"org": seeded_case.organization_id, "plant": seeded_case.plant_id})
    assert head_no == revision_count
    assert event_count == revision_count


def test_start_rollback_leaves_no_partial_execution_or_revision(engine: Engine, seeded_case: SeededCase) -> None:
    case = create_unstarted_case(engine, seeded_case)
    with engine.connect() as connection:
        before = connection.scalar(text("SELECT current_revision_no FROM planning.planning_state_heads WHERE organization_id=:org AND plant_id=:plant"), {"org": seeded_case.organization_id, "plant": seeded_case.plant_id})
    command = StartOperation(seeded_case.organization_id, case.operation_id, case.phase_ids[0], case.started_at, seeded_case.actor_id, uuid4())
    with pytest.raises(RuntimeError, match="injected failure"):
        StartOperationService(PostgresExecutionUnitOfWorkFactory(engine, failpoint="start_after_execution")).execute(command)
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM execution.operation_executions WHERE organization_id=:org AND required_operation_id=:operation"), {"org": seeded_case.organization_id, "operation": case.operation_id}) == 0
        assert connection.scalar(text("SELECT current_revision_no FROM planning.planning_state_heads WHERE organization_id=:org AND plant_id=:plant"), {"org": seeded_case.organization_id, "plant": seeded_case.plant_id}) == before


def test_segment_rollback_leaves_no_segment_usage_or_event(engine: Engine, seeded_case: SeededCase) -> None:
    case = create_unstarted_case(engine, seeded_case)
    execution = start_case(engine, case).operation_execution_id
    with engine.connect() as connection:
        before = connection.scalar(text("SELECT current_revision_no FROM planning.planning_state_heads WHERE organization_id=:org AND plant_id=:plant"), {"org": seeded_case.organization_id, "plant": seeded_case.plant_id})
    with pytest.raises(RuntimeError, match="injected failure"):
        RegisterExecutionSegmentService(PostgresExecutionUnitOfWorkFactory(engine, failpoint="segment_after_segment")).execute(segment_command(case, execution))
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM execution.execution_segments WHERE organization_id=:org AND operation_execution_id=:execution"), {"org": seeded_case.organization_id, "execution": execution}) == 0
        assert connection.scalar(text("SELECT count(*) FROM planning.effective_events WHERE organization_id=:org AND event_type_code='EXECUTION_SEGMENT_REGISTERED' AND entity_id=:execution"), {"org": seeded_case.organization_id, "execution": execution}) == 0
        assert connection.scalar(text("SELECT current_revision_no FROM planning.planning_state_heads WHERE organization_id=:org AND plant_id=:plant"), {"org": seeded_case.organization_id, "plant": seeded_case.plant_id}) == before


def test_finish_rollback_restores_running_status_event_and_revision(engine: Engine, seeded_case: SeededCase) -> None:
    case = create_unstarted_case(engine, seeded_case)
    execution = start_case(engine, case).operation_execution_id
    RegisterExecutionSegmentService(PostgresExecutionUnitOfWorkFactory(engine)).execute(segment_command(case, execution))
    with engine.connect() as connection:
        before = connection.scalar(text("SELECT current_revision_no FROM planning.planning_state_heads WHERE organization_id=:org AND plant_id=:plant"), {"org": seeded_case.organization_id, "plant": seeded_case.plant_id})
    with pytest.raises(RuntimeError, match="injected failure"):
        FinishOperationService(PostgresExecutionUnitOfWorkFactory(engine, failpoint="finish_after_status")).execute(finish_command(case, execution))
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT status::text FROM execution.operation_executions WHERE organization_id=:org AND id=:execution"), {"org": seeded_case.organization_id, "execution": execution}) == "running"
        assert connection.scalar(text("SELECT count(*) FROM planning.effective_events WHERE organization_id=:org AND event_type_code='OPERATION_COMPLETED' AND payload->>'operation_execution_id'=:execution"), {"org": seeded_case.organization_id, "execution": str(execution)}) == 0
        assert connection.scalar(text("SELECT current_revision_no FROM planning.planning_state_heads WHERE organization_id=:org AND plant_id=:plant"), {"org": seeded_case.organization_id, "plant": seeded_case.plant_id}) == before


def test_published_plan_and_planned_assignments_remain_unchanged(engine: Engine, seeded_case: SeededCase) -> None:
    case = create_unstarted_case(engine, seeded_case, planned=True)
    with engine.connect() as connection:
        before = connection.execute(text("SELECT p.current_plan_version_id,p.promotion_lock_version,hs.employee_id,pr.physical_resource_id,s.time_range FROM core.plants p JOIN planning.assignment_segments s ON s.organization_id=p.organization_id AND s.id=:segment JOIN planning.human_segment_assignments hs ON hs.organization_id=s.organization_id AND hs.assignment_segment_id=s.id JOIN planning.physical_resource_reservations pr ON pr.organization_id=s.organization_id AND pr.assignment_segment_id=s.id WHERE p.organization_id=:org AND p.id=:plant"), {"segment": case.assignment_segment_id, "org": seeded_case.organization_id, "plant": seeded_case.plant_id}).one()
    execution = start_case(engine, case).operation_execution_id
    RegisterExecutionSegmentService(PostgresExecutionUnitOfWorkFactory(engine)).execute(segment_command(case, execution))
    FinishOperationService(PostgresExecutionUnitOfWorkFactory(engine)).execute(finish_command(case, execution))
    with engine.connect() as connection:
        after = connection.execute(text("SELECT p.current_plan_version_id,p.promotion_lock_version,hs.employee_id,pr.physical_resource_id,s.time_range FROM core.plants p JOIN planning.assignment_segments s ON s.organization_id=p.organization_id AND s.id=:segment JOIN planning.human_segment_assignments hs ON hs.organization_id=s.organization_id AND hs.assignment_segment_id=s.id JOIN planning.physical_resource_reservations pr ON pr.organization_id=s.organization_id AND pr.assignment_segment_id=s.id WHERE p.organization_id=:org AND p.id=:plant"), {"segment": case.assignment_segment_id, "org": seeded_case.organization_id, "plant": seeded_case.plant_id}).one()
    assert after == before
