from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import Engine, text

from production_besten.application.update_remaining_estimate import (
    UpdateRemainingEstimateService,
)
from production_besten.domain.errors import EntityNotFound, RevisionConflict
from production_besten.domain.remaining_estimate import (
    RemainingDimension,
    RemainingResourceInput,
    UpdateRemainingEstimate,
)
from production_besten.persistence.remaining_estimate_uow import (
    PostgresUnitOfWorkFactory,
)

from .conftest import SeededCase


def command_for(case: SeededCase, *, expected_revision_no: int = 1, remaining: int = 300) -> UpdateRemainingEstimate:
    return UpdateRemainingEstimate(
        organization_id=case.organization_id,
        operation_execution_id=case.execution_id,
        expected_revision_no=expected_revision_no,
        cutoff_at=case.cutoff_at,
        remaining_labor_minutes=remaining,
        resources=(
            RemainingResourceInput(
                phase_id=case.phase_id,
                dimension=RemainingDimension.LABOR_WORK,
                remaining_minutes=remaining,
                skill_id=case.skill_id,
                min_people=1,
                max_people=2,
            ),
            RemainingResourceInput(
                phase_id=case.phase_id,
                dimension=RemainingDimension.ACTIVE_PHYSICAL_USE,
                remaining_minutes=90,
                physical_requirement_id=case.physical_requirement_id,
                capacity_units=1,
            ),
            RemainingResourceInput(
                phase_id=case.phase_id,
                dimension=RemainingDimension.PHYSICAL_OCCUPATION,
                remaining_minutes=600,
                physical_resource_id=case.physical_resource_id,
                capacity_units=1,
            ),
        ),
        raw_input={"minutes": remaining},
        reason="operator estimate update",
        actor_id=case.actor_id,
    )


def test_normal_update_preserves_original_and_advances_state_once(
    engine: Engine, seeded_case: SeededCase
) -> None:
    before_plan = plan_snapshot(engine, seeded_case)
    service = UpdateRemainingEstimateService(PostgresUnitOfWorkFactory(engine))

    result = service.execute(command_for(seeded_case))

    assert result.original_labor_minutes == 600
    assert result.executed_labor_minutes == 420
    assert result.remaining_labor_minutes == 300
    assert result.updated_total_labor_minutes == 720
    assert result.revision_no == 2
    assert result.planning_state_revision_no == 2
    assert result.current_plan_version_id == seeded_case.plan_version_id
    assert plan_snapshot(engine, seeded_case) == before_plan
    with engine.connect() as connection:
        original = connection.scalar(
            text("SELECT original_estimate_snapshot->>'labor_minutes' FROM execution.operation_executions WHERE organization_id=:org AND id=:id"),
            {"org": seeded_case.organization_id, "id": seeded_case.execution_id},
        )
        event = connection.execute(
            text("SELECT event_type_code,planning_state_revision_id FROM planning.effective_events WHERE organization_id=:org AND id=:id"),
            {"org": seeded_case.organization_id, "id": result.effective_event_id},
        ).one()
        head = connection.execute(
            text("SELECT current_revision_id,current_revision_no FROM planning.planning_state_heads WHERE organization_id=:org AND plant_id=:plant"),
            {"org": seeded_case.organization_id, "plant": seeded_case.plant_id},
        ).one()
    assert original == "600"
    assert event == ("REMAINING_ESTIMATE_UPDATED", result.planning_state_revision_id)
    assert head == (result.planning_state_revision_id, 2)


def test_previous_revision_is_preserved_and_only_successor_is_current(
    engine: Engine, seeded_case: SeededCase
) -> None:
    result = UpdateRemainingEstimateService(PostgresUnitOfWorkFactory(engine)).execute(command_for(seeded_case))

    with engine.connect() as connection:
        rows = connection.execute(
            text("SELECT id,revision_no,previous_revision_id,superseded_at,superseded_by_id FROM execution.remaining_estimate_revisions WHERE organization_id=:org AND operation_execution_id=:execution ORDER BY revision_no"),
            {"org": seeded_case.organization_id, "execution": seeded_case.execution_id},
        ).mappings().all()
    assert len(rows) == 2
    assert rows[0]["id"] == seeded_case.initial_remaining_revision_id
    assert rows[0]["superseded_at"] is not None
    assert rows[0]["superseded_by_id"] == result.revision_id
    assert rows[1]["previous_revision_id"] == seeded_case.initial_remaining_revision_id
    assert rows[1]["superseded_at"] is None


def test_resource_dimensions_coexist_with_independent_values(
    engine: Engine, seeded_case: SeededCase
) -> None:
    result = UpdateRemainingEstimateService(PostgresUnitOfWorkFactory(engine)).execute(command_for(seeded_case, remaining=120))

    with engine.connect() as connection:
        rows = connection.execute(
            text("SELECT dimension::text,remaining_minutes FROM execution.remaining_resource_estimates WHERE organization_id=:org AND remaining_estimate_revision_id=:revision ORDER BY dimension::text"),
            {"org": seeded_case.organization_id, "revision": result.revision_id},
        ).all()
    assert dict(rows) == {
        "ACTIVE_PHYSICAL_USE": 90,
        "LABOR_WORK": 120,
        "PHYSICAL_OCCUPATION": 600,
    }


def test_second_update_builds_r1_r2_r3_history(
    engine: Engine, seeded_case: SeededCase
) -> None:
    service = UpdateRemainingEstimateService(PostgresUnitOfWorkFactory(engine))
    second = service.execute(command_for(seeded_case, remaining=300))
    add_actual_labor(engine, seeded_case, minutes=120)
    third_command = replace(
        command_for(seeded_case, expected_revision_no=2, remaining=240),
        cutoff_at=seeded_case.cutoff_at + timedelta(minutes=120),
    )

    third = service.execute(third_command)

    assert second.revision_no == 2
    assert third.revision_no == 3
    assert third.executed_labor_minutes == 540
    assert third.updated_total_labor_minutes == 780
    assert third.planning_state_revision_no == 3
    with engine.connect() as connection:
        rows = connection.execute(
            text("SELECT id,revision_no,previous_revision_id,superseded_at FROM execution.remaining_estimate_revisions WHERE organization_id=:org AND operation_execution_id=:execution ORDER BY revision_no"),
            {"org": seeded_case.organization_id, "execution": seeded_case.execution_id},
        ).all()
    assert [row.revision_no for row in rows] == [1, 2, 3]
    assert rows[1].previous_revision_id == rows[0].id
    assert rows[2].previous_revision_id == rows[1].id
    assert [row.superseded_at is None for row in rows] == [False, False, True]


def test_cross_tenant_lookup_is_rejected(engine: Engine, seeded_case: SeededCase) -> None:
    service = UpdateRemainingEstimateService(PostgresUnitOfWorkFactory(engine))

    with pytest.raises(EntityNotFound):
        service.execute(replace(command_for(seeded_case), organization_id=seeded_case.other_organization_id))

    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM execution.remaining_estimate_revisions WHERE organization_id=:org AND operation_execution_id=:execution"), {"org": seeded_case.organization_id, "execution": seeded_case.execution_id}) == 1


def test_failure_rolls_back_every_write(engine: Engine, seeded_case: SeededCase) -> None:
    before = transactional_snapshot(engine, seeded_case)
    service = UpdateRemainingEstimateService(
        PostgresUnitOfWorkFactory(engine, failpoint="after_supersede")
    )

    with pytest.raises(RuntimeError, match="injected failure"):
        service.execute(command_for(seeded_case))

    assert transactional_snapshot(engine, seeded_case) == before


def test_concurrent_updates_do_not_create_two_current_revisions(
    engine: Engine, seeded_case: SeededCase
) -> None:
    command = command_for(seeded_case)

    def execute() -> object:
        try:
            return UpdateRemainingEstimateService(PostgresUnitOfWorkFactory(engine)).execute(command)
        except Exception as error:  # returned so both futures can be inspected
            return error

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = [future.result() for future in (executor.submit(execute), executor.submit(execute))]

    assert sum(not isinstance(value, Exception) for value in outcomes) == 1
    assert sum(isinstance(value, RevisionConflict) for value in outcomes) == 1
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM execution.remaining_estimate_revisions WHERE organization_id=:org AND operation_execution_id=:execution AND superseded_at IS NULL"), {"org": seeded_case.organization_id, "execution": seeded_case.execution_id}) == 1
        assert connection.scalar(text("SELECT current_revision_no FROM planning.planning_state_heads WHERE organization_id=:org AND plant_id=:plant"), {"org": seeded_case.organization_id, "plant": seeded_case.plant_id}) == 2
        assert connection.scalar(text("SELECT count(*) FROM planning.effective_events WHERE organization_id=:org AND entity_id=:execution AND event_type_code='REMAINING_ESTIMATE_UPDATED'"), {"org": seeded_case.organization_id, "execution": seeded_case.execution_id}) == 1


def add_actual_labor(engine: Engine, case: SeededCase, *, minutes: int) -> None:
    segment_id, employee_id = uuid4(), uuid4()
    end = case.cutoff_at + timedelta(minutes=minutes)
    with engine.begin() as connection:
        calendar_id = connection.scalar(text("SELECT base_calendar_id FROM core.plants WHERE organization_id=:org AND id=:plant"), {"org": case.organization_id, "plant": case.plant_id})
        connection.execute(text("INSERT INTO capacity.employees(id,organization_id,plant_id,code,display_name,base_calendar_id) VALUES (:id,:org,:plant,:code,'Worker 2',:calendar)"), {"id": employee_id, "org": case.organization_id, "plant": case.plant_id, "code": f"EMP-{employee_id.hex[:12]}", "calendar": calendar_id})
        connection.execute(text("INSERT INTO execution.execution_segments(id,organization_id,operation_execution_id,required_operation_phase_id,segment_no,time_range,segment_kind,work_minutes) VALUES (:id,:org,:execution,:phase,2,tstzrange(:start,:finish,'[)'),'work',:minutes)"), {"id": segment_id, "org": case.organization_id, "execution": case.execution_id, "phase": case.phase_id, "start": case.cutoff_at, "finish": end, "minutes": minutes})
        connection.execute(text("INSERT INTO execution.actual_resource_usages(organization_id,execution_segment_id,employee_id,time_range,work_minutes,usage_kind) VALUES (:org,:segment,:employee,tstzrange(:start,:finish,'[)'),:minutes,'labor')"), {"org": case.organization_id, "segment": segment_id, "employee": employee_id, "start": case.cutoff_at, "finish": end, "minutes": minutes})


def plan_snapshot(engine: Engine, case: SeededCase) -> tuple[object, ...]:
    with engine.connect() as connection:
        return connection.execute(
            text("SELECT p.current_plan_version_id,p.promotion_lock_version,pv.id,pv.status,pv.planning_state_revision_id,(SELECT count(*) FROM planning.plan_versions WHERE organization_id=:org AND plant_id=:plant) FROM core.plants p JOIN planning.plan_versions pv ON pv.organization_id=p.organization_id AND pv.id=p.current_plan_version_id WHERE p.organization_id=:org AND p.id=:plant"),
            {"org": case.organization_id, "plant": case.plant_id},
        ).one()


def transactional_snapshot(engine: Engine, case: SeededCase) -> tuple[object, ...]:
    with engine.connect() as connection:
        return connection.execute(
            text("SELECT (SELECT count(*) FROM execution.remaining_estimate_revisions WHERE organization_id=:org AND operation_execution_id=:execution),(SELECT count(*) FROM execution.remaining_resource_estimates r JOIN execution.remaining_estimate_revisions e ON e.organization_id=r.organization_id AND e.id=r.remaining_estimate_revision_id WHERE e.organization_id=:org AND e.operation_execution_id=:execution),(SELECT count(*) FROM planning.effective_events WHERE organization_id=:org AND entity_id=:execution AND event_type_code='REMAINING_ESTIMATE_UPDATED'),(SELECT count(*) FROM planning.planning_state_revisions WHERE organization_id=:org AND plant_id=:plant),(SELECT current_revision_id FROM planning.planning_state_heads WHERE organization_id=:org AND plant_id=:plant),(SELECT current_revision_no FROM planning.planning_state_heads WHERE organization_id=:org AND plant_id=:plant),(SELECT superseded_at FROM execution.remaining_estimate_revisions WHERE organization_id=:org AND id=:remaining)"),
            {"org": case.organization_id, "execution": case.execution_id, "plant": case.plant_id, "remaining": case.initial_remaining_revision_id},
        ).one()
