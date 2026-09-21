from __future__ import annotations

from dataclasses import dataclass, replace
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from time import perf_counter
from uuid import uuid4

import pytest
from sqlalchemy import Engine, text

from production_besten.application.replanning_services import ReplanService, RejectReplanService
from production_besten.application.update_remaining_estimate import UpdateRemainingEstimateService
from production_besten.domain.errors import (
    EntityNotFound, IdempotencyConflict, RevisionConflict, SchedulingBaseStale,
)
from production_besten.domain.remaining_estimate import (
    RemainingDimension, RemainingResourceInput, UpdateRemainingEstimate,
)
from production_besten.domain.replanning import RejectReplan, ReplanRequest
from production_besten.persistence.remaining_estimate_uow import PostgresUnitOfWorkFactory
from production_besten.persistence.scheduling_uow import PostgresSchedulingUnitOfWorkFactory

from .conftest import SeededCase, seed_case
from .scheduling_helpers import HORIZON_START, add_operation, generate, prepare_basic


@dataclass(frozen=True)
class ReplannedCase:
    case: SeededCase
    request: ReplanRequest
    result: object
    remaining_revision_id: object


def _prepare(engine: Engine, case: SeededCase) -> ReplannedCase:
    operation_id = prepare_basic(engine, case, minutes=600)
    estimate = UpdateRemainingEstimateService(PostgresUnitOfWorkFactory(engine)).execute(
        UpdateRemainingEstimate(
            case.organization_id, case.execution_id, 1, case.cutoff_at, 180,
            (RemainingResourceInput(
                case.phase_id, RemainingDimension.LABOR_WORK, remaining_minutes=180,
                skill_id=case.skill_id, min_people=1, max_people=1,
            ),),
            reason="real deviation", actor_id=case.actor_id,
        )
    )
    request = ReplanRequest(
        case.organization_id, case.plant_id, case.actor_id, uuid4().hex,
        f"RP-{uuid4().hex}", "Deviation simulation", case.cutoff_at,
        case.cutoff_at + timedelta(days=7), case.definition_revision_id,
        estimate.planning_state_revision_id, case.plan_version_id,
        trigger_operation_id=operation_id,
    )
    result = ReplanService(PostgresSchedulingUnitOfWorkFactory(engine)).execute(request)
    return ReplannedCase(case, request, result, estimate.revision_id)


@pytest.fixture(scope="module")
def replanned(engine: Engine) -> ReplannedCase:
    return _prepare(engine, seed_case(engine))


INVARIANTS = (
    "scenario_kind", "scenario_ready", "scenario_has_base_plan", "scenario_has_state",
    "scenario_has_definition", "scenario_has_cutoff", "scenario_has_idempotency",
    "solution_ready", "solution_has_baseline", "solution_has_comparison",
    "solution_has_impact_summary", "solution_hash_present", "one_operation_result",
    "one_phase_result", "remaining_revision_linked", "remaining_minutes_used",
    "segments_after_cutoff", "current_plan_unchanged", "no_new_plan_version",
    "actual_revision_still_current",
)


@pytest.mark.parametrize("invariant", INVARIANTS)
def test_replan_persistence_invariants(engine: Engine, replanned: ReplannedCase,
                                       invariant: str) -> None:
    case, request, result = replanned.case, replanned.request, replanned.result
    with engine.connect() as connection:
        scenario = connection.execute(text("""
            SELECT scenario_kind,status,base_plan_version_id,base_state_revision_id,
                   base_product_definition_revision_id,parameters
              FROM planning.scenarios WHERE organization_id=:org AND id=:id
        """), {"org": case.organization_id, "id": result.scenario_id}).mappings().one()
        solution = connection.execute(text("""
            SELECT status,baseline_solution_id,comparison,impact_summary,solution_sha256
              FROM planning.schedule_solutions WHERE organization_id=:org AND id=:id
        """), {"org": case.organization_id, "id": result.solution_id}).mappings().one()
        operation_count = connection.scalar(text("SELECT count(*) FROM planning.operation_plan_results WHERE organization_id=:org AND schedule_solution_id=:id"), {"org": case.organization_id, "id": result.solution_id})
        phase_rows = connection.execute(text("SELECT remaining_estimate_revision_id,planned_work_minutes FROM planning.phase_plan_results WHERE organization_id=:org AND schedule_solution_id=:id"), {"org": case.organization_id, "id": result.solution_id}).mappings().all()
        phase = phase_rows[0]
        first_start = connection.scalar(text("SELECT min(lower(time_range)) FROM planning.assignment_segments WHERE organization_id=:org AND schedule_solution_id=:id"), {"org": case.organization_id, "id": result.solution_id})
        current_plan = connection.scalar(text("SELECT current_plan_version_id FROM core.plants WHERE organization_id=:org AND id=:plant"), {"org": case.organization_id, "plant": case.plant_id})
        plan_count = connection.scalar(text("SELECT count(*) FROM planning.plan_versions WHERE organization_id=:org AND plant_id=:plant"), {"org": case.organization_id, "plant": case.plant_id})
        remaining_current = connection.scalar(text("SELECT id FROM execution.remaining_estimate_revisions WHERE organization_id=:org AND operation_execution_id=:execution AND superseded_at IS NULL"), {"org": case.organization_id, "execution": case.execution_id})
    checks = {
        "scenario_kind": scenario["scenario_kind"] == "replan",
        "scenario_ready": scenario["status"] == "ready",
        "scenario_has_base_plan": scenario["base_plan_version_id"] == case.plan_version_id,
        "scenario_has_state": scenario["base_state_revision_id"] == request.planning_state_revision_id,
        "scenario_has_definition": scenario["base_product_definition_revision_id"] == case.definition_revision_id,
        "scenario_has_cutoff": scenario["parameters"]["replan"]["cutoff_at"] == request.cutoff_at.isoformat(),
        "scenario_has_idempotency": scenario["parameters"]["idempotency_key"] == request.idempotency_key,
        "solution_ready": solution["status"] == "ready",
        "solution_has_baseline": solution["baseline_solution_id"] == case.schedule_solution_id,
        "solution_has_comparison": solution["comparison"]["current_plan_modified"] is False if "current_plan_modified" in solution["comparison"] else solution["comparison"]["impact_summary"]["current_plan_modified"] is False,
        "solution_has_impact_summary": solution["impact_summary"]["current_plan_modified"] is False,
        "solution_hash_present": solution["solution_sha256"] is not None,
        "one_operation_result": operation_count == 1,
        "one_phase_result": len(phase_rows) == 1,
        "remaining_revision_linked": phase["remaining_estimate_revision_id"] == replanned.remaining_revision_id,
        "remaining_minutes_used": phase["planned_work_minutes"] == 180,
        "segments_after_cutoff": first_start >= request.cutoff_at,
        "current_plan_unchanged": current_plan == case.plan_version_id,
        "no_new_plan_version": plan_count == 1,
        "actual_revision_still_current": remaining_current == replanned.remaining_revision_id,
    }
    assert checks[invariant]


def test_replan_from_operation_reports_frontier(engine: Engine, seeded_case: SeededCase) -> None:
    value = _prepare(engine, seeded_case)
    assert value.result.frontier_project_ids == (seeded_case.project_id,)
    assert len(value.result.frontier_operation_ids) == 1


def test_replan_idempotent_replay(engine: Engine, seeded_case: SeededCase) -> None:
    value = _prepare(engine, seeded_case)
    replay = ReplanService(PostgresSchedulingUnitOfWorkFactory(engine)).execute(value.request)
    assert replay.scenario_id == value.result.scenario_id
    assert replay.solution_id == value.result.solution_id
    assert replay.idempotent_replay


def test_replan_project_command(engine: Engine, seeded_case: SeededCase) -> None:
    value = _prepare(engine, seeded_case)
    request = replace(
        value.request, idempotency_key=uuid4().hex, code=f"RP-{uuid4().hex}",
        trigger_operation_id=None, project_id=seeded_case.project_id,
    )
    result = ReplanService(PostgresSchedulingUnitOfWorkFactory(engine)).execute(request)
    assert result.frontier_project_ids == (seeded_case.project_id,)


def test_replan_idempotency_key_rejects_different_target(engine: Engine,
                                                         seeded_case: SeededCase) -> None:
    value = _prepare(engine, seeded_case)
    with pytest.raises(IdempotencyConflict):
        ReplanService(PostgresSchedulingUnitOfWorkFactory(engine)).execute(
            replace(value.request, cutoff_at=value.request.cutoff_at + timedelta(minutes=1))
        )


def test_concurrent_replan_retry_materializes_once(engine: Engine,
                                                   seeded_case: SeededCase) -> None:
    value = _prepare(engine, seeded_case)
    command = replace(value.request, idempotency_key=uuid4().hex,
                      code=f"RP-{uuid4().hex}")
    def run():
        return ReplanService(PostgresSchedulingUnitOfWorkFactory(engine)).execute(command)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = [future.result() for future in (pool.submit(run), pool.submit(run))]
    assert first.scenario_id == second.scenario_id
    assert first.solution_id == second.solution_id
    assert first.idempotent_replay != second.idempotent_replay


def test_parallel_scenarios_are_independent(engine: Engine,
                                            seeded_case: SeededCase) -> None:
    value = _prepare(engine, seeded_case)
    requests = [replace(value.request, idempotency_key=uuid4().hex,
                        code=f"RP-{uuid4().hex}") for _ in range(2)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [future.result() for future in [
            pool.submit(ReplanService(PostgresSchedulingUnitOfWorkFactory(engine)).execute, item)
            for item in requests
        ]]
    assert results[0].scenario_id != results[1].scenario_id
    assert all(result.status == "ready" for result in results)


def test_reject_replan_preserves_reality_and_plan(engine: Engine, seeded_case: SeededCase) -> None:
    value = _prepare(engine, seeded_case)
    rejected = RejectReplanService(PostgresSchedulingUnitOfWorkFactory(engine)).execute(
        RejectReplan(seeded_case.organization_id, seeded_case.plant_id, seeded_case.actor_id,
                     value.result.scenario_id, 2, "not useful")
    )
    with engine.connect() as connection:
        current_plan = connection.scalar(text("SELECT current_plan_version_id FROM core.plants WHERE id=:id"), {"id": seeded_case.plant_id})
        revision = connection.scalar(text("SELECT id FROM execution.remaining_estimate_revisions WHERE organization_id=:org AND operation_execution_id=:execution AND superseded_at IS NULL"), {"org": seeded_case.organization_id, "execution": seeded_case.execution_id})
    assert rejected.status == "rejected"
    assert current_plan == seeded_case.plan_version_id
    assert revision == value.remaining_revision_id


def test_reject_is_idempotent(engine: Engine, seeded_case: SeededCase) -> None:
    value = _prepare(engine, seeded_case)
    service = RejectReplanService(PostgresSchedulingUnitOfWorkFactory(engine))
    command = RejectReplan(seeded_case.organization_id, seeded_case.plant_id, seeded_case.actor_id,
                           value.result.scenario_id, 2, "reject")
    service.execute(command)
    replay = service.execute(command)
    assert replay.idempotent_replay


def test_reject_detects_row_version_conflict(engine: Engine, seeded_case: SeededCase) -> None:
    value = _prepare(engine, seeded_case)
    with pytest.raises(RevisionConflict):
        RejectReplanService(PostgresSchedulingUnitOfWorkFactory(engine)).execute(
            RejectReplan(seeded_case.organization_id, seeded_case.plant_id, seeded_case.actor_id,
                         value.result.scenario_id, 99, "stale client")
        )


def test_replan_rejects_stale_state(engine: Engine, seeded_case: SeededCase) -> None:
    value = _prepare(engine, seeded_case)
    with pytest.raises(SchedulingBaseStale):
        ReplanService(PostgresSchedulingUnitOfWorkFactory(engine)).execute(
            replace(value.request, idempotency_key=uuid4().hex,
                    code=f"RP-{uuid4().hex}", planning_state_revision_id=seeded_case.initial_state_revision_id)
        )


def test_replan_is_tenant_scoped(engine: Engine, seeded_case: SeededCase) -> None:
    value = _prepare(engine, seeded_case)
    with pytest.raises(EntityNotFound):
        ReplanService(PostgresSchedulingUnitOfWorkFactory(engine)).execute(
            replace(value.request, organization_id=seeded_case.other_organization_id,
                    idempotency_key=uuid4().hex, code=f"RP-{uuid4().hex}")
        )


def test_replan_rolls_back_on_persistence_failure(engine: Engine, seeded_case: SeededCase) -> None:
    operation_id = prepare_basic(engine, seeded_case, minutes=600)
    request = ReplanRequest(
        seeded_case.organization_id, seeded_case.plant_id, seeded_case.actor_id, uuid4().hex,
        f"RP-{uuid4().hex}", "rollback", seeded_case.cutoff_at,
        seeded_case.cutoff_at + timedelta(days=2), seeded_case.definition_revision_id,
        seeded_case.initial_state_revision_id, seeded_case.plan_version_id,
        trigger_operation_id=operation_id,
    )
    with pytest.raises(RuntimeError):
        ReplanService(PostgresSchedulingUnitOfWorkFactory(engine, failpoint="after_solution")).execute(request)
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM planning.scenarios WHERE organization_id=:org AND code=:code"), {"org": seeded_case.organization_id, "code": request.code}) == 0


def test_completed_operation_is_not_rescheduled(engine: Engine, seeded_case: SeededCase) -> None:
    operation_id = prepare_basic(engine, seeded_case, minutes=600)
    with engine.begin() as connection:
        connection.execute(text("UPDATE execution.operation_executions SET status='completed',completed_at=:at WHERE organization_id=:org AND id=:id"), {"at": seeded_case.cutoff_at, "org": seeded_case.organization_id, "id": seeded_case.execution_id})
    request = ReplanRequest(
        seeded_case.organization_id, seeded_case.plant_id, seeded_case.actor_id, uuid4().hex,
        f"RP-{uuid4().hex}", "completed", seeded_case.cutoff_at,
        seeded_case.cutoff_at + timedelta(days=2), seeded_case.definition_revision_id,
        seeded_case.initial_state_revision_id, seeded_case.plan_version_id,
        trigger_operation_id=operation_id,
    )
    result = ReplanService(PostgresSchedulingUnitOfWorkFactory(engine)).execute(request)
    with engine.connect() as connection:
        count = connection.scalar(text("SELECT count(*) FROM planning.operation_plan_results WHERE schedule_solution_id=:solution"), {"solution": result.solution_id})
    assert count == 0


def test_customer_communicated_date_generates_alert(engine: Engine, seeded_case: SeededCase) -> None:
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO portal.communicated_dates(organization_id,project_id,date_kind,communicated_date,approved_by,communicated_at) VALUES (:org,:project,'delivery',:date,:actor,:at)"), {"org": seeded_case.organization_id, "project": seeded_case.project_id, "date": seeded_case.cutoff_at.date(), "actor": seeded_case.actor_id, "at": seeded_case.cutoff_at})
    value = _prepare(engine, seeded_case)
    assert value.result.customer_date_alerts == 1


def test_replan_benchmark_ten_projects_fifty_operations(
    engine: Engine, seeded_case: SeededCase, capsys
) -> None:
    prepare_basic(engine, seeded_case, minutes=60)
    project_ids = [seeded_case.project_id]
    with engine.begin() as connection:
        customer_id, priority_id = connection.execute(text("""
            SELECT customer_id,priority_id FROM core.projects
             WHERE organization_id=:org AND id=:project
        """), {"org": seeded_case.organization_id,
                 "project": seeded_case.project_id}).one()
        for project_number in range(1, 10):
            project_id, lot_id = uuid4(), uuid4()
            project_ids.append(project_id)
            connection.execute(text("""
                INSERT INTO core.projects
                  (id,organization_id,plant_id,customer_id,code,name,priority_id,status)
                VALUES (:id,:org,:plant,:customer,:code,:code,:priority,'active')
            """), {"id": project_id, "org": seeded_case.organization_id,
                    "plant": seeded_case.plant_id, "customer": customer_id,
                    "code": f"BENCH-P{project_number:02d}-{project_id.hex[:6]}",
                    "priority": priority_id})
            connection.execute(text("""
                INSERT INTO core.project_lots
                  (id,organization_id,project_id,code,name,sequence_no,status,hardware_status)
                VALUES (:id,:org,:project,:code,:code,1,'active','ready')
            """), {"id": lot_id, "org": seeded_case.organization_id,
                    "project": project_id, "code": f"LOT-{project_id.hex[:8]}"})
            for operation_number in range(5):
                add_operation(
                    connection, seeded_case,
                    f"B{project_number:02d}-O{operation_number:02d}",
                    project_id=project_id, lot_id=lot_id, minutes=60,
                    skill_id=seeded_case.skill_id,
                    resource_type_id=seeded_case.resource_type_id,
                )
        for operation_number in range(4):
            add_operation(
                connection, seeded_case, f"B00-O{operation_number + 1:02d}",
                minutes=60, skill_id=seeded_case.skill_id,
                resource_type_id=seeded_case.resource_type_id,
            )
    baseline = generate(
        engine, seeded_case, project_ids=project_ids, start=HORIZON_START,
        end=HORIZON_START + timedelta(days=30),
    )
    plan_id = uuid4()
    with engine.begin() as connection:
        connection.execute(text("""
            UPDATE planning.plan_versions
               SET status='superseded',valid_during=tstzrange(lower(valid_during),:at,'[)')
             WHERE organization_id=:org AND id=:old
        """), {"at": HORIZON_START, "org": seeded_case.organization_id,
                 "old": seeded_case.plan_version_id})
        connection.execute(text("""
            INSERT INTO planning.plan_versions
              (id,organization_id,plant_id,version_no,schedule_solution_id,
               product_definition_revision_id,planning_state_revision_id,
               previous_version_id,source_scenario_id,status,valid_during,
               confirmed_at,confirmed_by)
            VALUES (:id,:org,:plant,2,:solution,:definition,:state,:previous,
                    :scenario,'published',tstzrange(:at,NULL,'[)'),:at,:actor)
        """), {"id": plan_id, "org": seeded_case.organization_id,
                "plant": seeded_case.plant_id, "solution": baseline.solution_id,
                "definition": seeded_case.definition_revision_id,
                "state": seeded_case.initial_state_revision_id,
                "previous": seeded_case.plan_version_id,
                "scenario": baseline.scenario_id, "at": HORIZON_START,
                "actor": seeded_case.actor_id})
        connection.execute(text("""
            UPDATE core.plants SET current_plan_version_id=:plan
             WHERE organization_id=:org AND id=:plant
        """), {"plan": plan_id, "org": seeded_case.organization_id,
                 "plant": seeded_case.plant_id})
    request = ReplanRequest(
        seeded_case.organization_id, seeded_case.plant_id, seeded_case.actor_id,
        uuid4().hex, f"RP-{uuid4().hex}", "10x50 benchmark", HORIZON_START,
        HORIZON_START + timedelta(days=30), seeded_case.definition_revision_id,
        seeded_case.initial_state_revision_id, plan_id,
        project_id=seeded_case.project_id,
    )
    started = perf_counter()
    result = ReplanService(PostgresSchedulingUnitOfWorkFactory(engine)).execute(request)
    elapsed_ms = (perf_counter() - started) * 1000
    print(f"replan_postgresql projects={len(result.frontier_project_ids)} "
          f"operations={len(result.frontier_operation_ids)} elapsed_ms={elapsed_ms:.2f}")
    assert len(result.frontier_project_ids) == 10
    assert len(result.frontier_operation_ids) == 50
    assert result.status == "ready"
    assert elapsed_ms < 5000
