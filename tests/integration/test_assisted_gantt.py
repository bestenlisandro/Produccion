from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from dataclasses import asdict
import json
from time import perf_counter
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from production_besten.application.replanning_services import (
    MoveScheduledActivityService, ResizeScheduledActivityService,
)
from production_besten.domain.errors import (
    EntityNotFound, IdempotencyConflict, ReplanConflict,
)
from production_besten.domain.replanning import (
    MoveScheduledActivity, ResizeScheduledActivity,
)
from production_besten.persistence.scheduling_uow import (
    PostgresSchedulingUnitOfWorkFactory,
)
from production_besten.api.app import create_app

from .conftest import SeededCase
from .scheduling_helpers import (
    HORIZON_START, add_operation, add_resource, current_state, generate,
    prepare_basic,
)
from .test_replanning import _prepare_benchmark_replan


def _publish_future_plan(engine: Engine, case: SeededCase):
    prepare_basic(engine, case, minutes=120)
    with engine.begin() as connection:
        operation_id, phase_id = add_operation(
            connection, case, f"FUT-{uuid4().hex[:8]}", minutes=120,
            skill_id=case.skill_id, resource_type_id=case.resource_type_id,
        )
    baseline = generate(
        engine, case, start=HORIZON_START,
        end=HORIZON_START + timedelta(days=14),
    )
    plan_id = uuid4()
    with engine.begin() as connection:
        connection.execute(text("""
            UPDATE planning.plan_versions
               SET status='superseded',
                   valid_during=tstzrange(lower(valid_during),:at,'[)')
             WHERE organization_id=:org AND id=:old
        """), {"at": HORIZON_START, "org": case.organization_id,
                 "old": case.plan_version_id})
        connection.execute(text("""
            INSERT INTO planning.plan_versions
              (id,organization_id,plant_id,version_no,schedule_solution_id,
               product_definition_revision_id,planning_state_revision_id,
               previous_version_id,source_scenario_id,status,valid_during,
               confirmed_at,confirmed_by)
            VALUES (:id,:org,:plant,2,:solution,:definition,:state,:previous,
                    :scenario,'published',tstzrange(:at,NULL,'[)'),:at,:actor)
        """), {
            "id": plan_id, "org": case.organization_id, "plant": case.plant_id,
            "solution": baseline.solution_id,
            "definition": case.definition_revision_id,
            "state": current_state(engine, case), "previous": case.plan_version_id,
            "scenario": baseline.scenario_id, "at": HORIZON_START,
            "actor": case.actor_id,
        })
        connection.execute(text("""
            UPDATE core.plants SET current_plan_version_id=:plan
             WHERE organization_id=:org AND id=:plant
        """), {"plan": plan_id, "org": case.organization_id,
                 "plant": case.plant_id})
        row = connection.execute(text("""
            SELECT planned_start_at,planned_end_at
              FROM planning.operation_plan_results
             WHERE organization_id=:org AND schedule_solution_id=:solution
               AND required_operation_id=:operation
        """), {
            "org": case.organization_id, "solution": baseline.solution_id,
            "operation": operation_id,
        }).one()
    return operation_id, phase_id, plan_id, row[0], row[1]


def _move(case, operation_id, phase_id, plan_id, requested_start, *,
          command_id=None, resource_id=None):
    return MoveScheduledActivity(
        case.organization_id, case.plant_id, case.actor_id,
        command_id or uuid4(), operation_id, plan_id,
        case.definition_revision_id, case.initial_state_revision_id,
        requested_start, HORIZON_START,
        HORIZON_START + timedelta(days=14), phase_id, resource_id,
    )


def test_move_creates_hypothesis_scenario_and_keeps_current(
    engine: Engine, seeded_case: SeededCase
) -> None:
    operation, phase, plan, start, _ = _publish_future_plan(engine, seeded_case)
    command = _move(
        seeded_case, operation, phase, plan, start + timedelta(days=1),
    )
    result = MoveScheduledActivityService(
        PostgresSchedulingUnitOfWorkFactory(engine)
    ).execute(command)
    with engine.connect() as connection:
        hypothesis = connection.execute(text("""
            SELECT hypothesis_type,target_id,parameters
              FROM planning.simulation_hypotheses
             WHERE organization_id=:org AND scenario_id=:scenario
        """), {
            "org": seeded_case.organization_id, "scenario": result.scenario_id,
        }).mappings().one()
        current = connection.scalar(text("""
            SELECT current_plan_version_id FROM core.plants
             WHERE organization_id=:org AND id=:plant
        """), {"org": seeded_case.organization_id,
                 "plant": seeded_case.plant_id})
    assert result.status == "ready"
    assert result.proposed_start >= command.requested_start
    assert hypothesis["hypothesis_type"] == "MOVE_SCHEDULED_ACTIVITY"
    assert hypothesis["target_id"] == operation
    assert hypothesis["parameters"]["requested_start"] == command.requested_start.isoformat()
    assert current == plan


def test_move_earlier_and_later_use_requested_anchor(
    engine: Engine, seeded_case: SeededCase
) -> None:
    operation, phase, plan, start, _ = _publish_future_plan(engine, seeded_case)
    service = MoveScheduledActivityService(PostgresSchedulingUnitOfWorkFactory(engine))
    earlier = service.execute(_move(
        seeded_case, operation, phase, plan, HORIZON_START,
    ))
    later = service.execute(_move(
        seeded_case, operation, phase, plan, start + timedelta(days=2),
    ))
    assert earlier.proposed_start == HORIZON_START
    assert later.proposed_start >= start + timedelta(days=2)


def test_move_idempotency_and_payload_conflict(
    engine: Engine, seeded_case: SeededCase
) -> None:
    operation, phase, plan, start, _ = _publish_future_plan(engine, seeded_case)
    service = MoveScheduledActivityService(PostgresSchedulingUnitOfWorkFactory(engine))
    command = _move(
        seeded_case, operation, phase, plan, start + timedelta(days=1),
        command_id=uuid4(),
    )
    first = service.execute(command)
    replay = service.execute(command)
    assert replay.scenario_id == first.scenario_id
    assert replay.idempotent_replay
    with pytest.raises(IdempotencyConflict):
        service.execute(replace(
            command, requested_start=command.requested_start + timedelta(hours=1),
        ))


def test_requested_resource_is_used_and_cross_tenant_is_hidden(
    engine: Engine, seeded_case: SeededCase
) -> None:
    operation, phase, plan, start, _ = _publish_future_plan(engine, seeded_case)
    with engine.begin() as connection:
        requested = add_resource(
            connection, seeded_case, f"ALT-{uuid4().hex[:8]}",
            resource_type_id=seeded_case.resource_type_id,
        )
    service = MoveScheduledActivityService(PostgresSchedulingUnitOfWorkFactory(engine))
    result = service.execute(_move(
        seeded_case, operation, phase, plan, start + timedelta(days=1),
        resource_id=requested,
    ))
    with engine.connect() as connection:
        assigned = connection.scalar(text("""
            SELECT EXISTS(
                SELECT 1 FROM planning.physical_resource_reservations
                 WHERE organization_id=:org AND schedule_solution_id=:solution
                   AND physical_resource_id=:resource
            )
        """), {
            "org": seeded_case.organization_id, "solution": result.solution_id,
            "resource": requested,
        })
    assert assigned
    with pytest.raises(EntityNotFound):
        service.execute(replace(
            _move(seeded_case, operation, phase, plan, start + timedelta(days=2)),
            organization_id=seeded_case.other_organization_id,
        ))


def test_resize_is_planned_duration_hypothesis(
    engine: Engine, seeded_case: SeededCase
) -> None:
    operation, phase, plan, _, _ = _publish_future_plan(engine, seeded_case)
    command = ResizeScheduledActivity(
        seeded_case.organization_id, seeded_case.plant_id, seeded_case.actor_id,
        uuid4(), operation, plan, seeded_case.definition_revision_id,
        seeded_case.initial_state_revision_id, 180, HORIZON_START,
        HORIZON_START + timedelta(days=14), phase,
    )
    result = ResizeScheduledActivityService(
        PostgresSchedulingUnitOfWorkFactory(engine)
    ).execute(command)
    with engine.connect() as connection:
        values = connection.execute(text("""
            SELECT h.parameters,p.original_estimate_minutes
              FROM planning.simulation_hypotheses h
              JOIN production.required_operation_phases p
                ON p.organization_id=h.organization_id AND p.id=:phase
             WHERE h.organization_id=:org AND h.scenario_id=:scenario
        """), {
            "phase": phase, "org": seeded_case.organization_id,
            "scenario": result.scenario_id,
        }).one()
    assert result.exact_request_satisfied
    assert values[0]["resize_kind"] == "PLANNED_DURATION_HYPOTHESIS"
    assert values[1] == 120
    replay = ResizeScheduledActivityService(
        PostgresSchedulingUnitOfWorkFactory(engine)
    ).execute(command)
    assert replay.scenario_id == result.scenario_id
    assert replay.idempotent_replay
    with pytest.raises(IdempotencyConflict):
        ResizeScheduledActivityService(
            PostgresSchedulingUnitOfWorkFactory(engine)
        ).execute(replace(command, requested_duration_minutes=181))
    with pytest.raises(EntityNotFound):
        ResizeScheduledActivityService(
            PostgresSchedulingUnitOfWorkFactory(engine)
        ).execute(replace(
            command, organization_id=seeded_case.other_organization_id,
            command_id=uuid4(),
        ))


def test_running_activity_requires_remaining_estimate_flow(
    engine: Engine, seeded_case: SeededCase
) -> None:
    prepare_basic(engine, seeded_case, minutes=120)
    baseline = generate(
        engine, seeded_case, start=HORIZON_START,
        end=HORIZON_START + timedelta(days=14),
    )
    plan = uuid4()
    with engine.connect() as connection:
        operation = connection.scalar(text("""
            SELECT required_operation_id FROM production.required_operation_phases
             WHERE organization_id=:org AND id=:phase
        """), {"org": seeded_case.organization_id, "phase": seeded_case.phase_id})
    with engine.begin() as connection:
        connection.execute(text("""
            UPDATE planning.plan_versions SET status='superseded',
              valid_during=tstzrange(lower(valid_during),:at,'[)')
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
        """), {
            "id": plan, "org": seeded_case.organization_id,
            "plant": seeded_case.plant_id, "solution": baseline.solution_id,
            "definition": seeded_case.definition_revision_id,
            "state": seeded_case.initial_state_revision_id,
            "previous": seeded_case.plan_version_id,
            "scenario": baseline.scenario_id, "at": HORIZON_START,
            "actor": seeded_case.actor_id,
        })
        connection.execute(text("""
            UPDATE core.plants SET current_plan_version_id=:plan
             WHERE organization_id=:org AND id=:plant
        """), {"plan": plan, "org": seeded_case.organization_id,
                 "plant": seeded_case.plant_id})
    with pytest.raises(ReplanConflict, match="UPDATE_REMAINING_ESTIMATE"):
        MoveScheduledActivityService(
            PostgresSchedulingUnitOfWorkFactory(engine)
        ).execute(_move(
            seeded_case, operation, seeded_case.phase_id, plan,
            HORIZON_START + timedelta(days=1),
        ))
    with pytest.raises(ReplanConflict, match="UPDATE_REMAINING_ESTIMATE"):
        ResizeScheduledActivityService(
            PostgresSchedulingUnitOfWorkFactory(engine)
        ).execute(ResizeScheduledActivity(
            seeded_case.organization_id, seeded_case.plant_id,
            seeded_case.actor_id, uuid4(), operation, plan,
            seeded_case.definition_revision_id,
            seeded_case.initial_state_revision_id, 180, HORIZON_START,
            HORIZON_START + timedelta(days=14), seeded_case.phase_id,
        ))


def test_move_resize_http_contract_and_openapi(
    engine: Engine, seeded_case: SeededCase
) -> None:
    operation, phase, plan, start, _ = _publish_future_plan(engine, seeded_case)
    client = TestClient(
        create_app(engine=engine, enable_dev_context=True),
        raise_server_exceptions=False,
    )
    headers = {
        "X-Dev-Organization-Id": str(seeded_case.organization_id),
        "X-Dev-Plant-Id": str(seeded_case.plant_id),
        "X-Dev-User-Id": str(seeded_case.actor_id),
        "Idempotency-Key": str(uuid4()),
    }
    move = client.post(
        f"/planning/activities/{operation}/move", headers=headers,
        json={
            "base_plan_version_id": str(plan),
            "requested_start": (start + timedelta(days=1)).isoformat(),
            "cutoff_at": HORIZON_START.isoformat(),
            "horizon_end": (HORIZON_START + timedelta(days=14)).isoformat(),
            "phase_id": str(phase),
        },
    )
    assert move.status_code == 201
    assert set(("requested_start", "proposed_start",
                "exact_request_satisfied", "scenario_id")) <= move.json().keys()
    invalid_resize = client.post(
        f"/planning/activities/{operation}/resize",
        headers={**headers, "Idempotency-Key": str(uuid4())},
        json={
            "base_plan_version_id": str(plan),
            "requested_duration_minutes": 180,
            "cutoff_at": HORIZON_START.isoformat(),
            "horizon_end": (HORIZON_START + timedelta(days=14)).isoformat(),
            "phase_id": str(phase),
            "resize_kind": "REMAINING_ESTIMATE_UPDATE",
        },
    )
    assert invalid_resize.status_code == 422
    paths = client.get("/openapi.json").json()["paths"]
    assert f"/planning/activities/{{operation_id}}/move" in paths
    assert f"/planning/activities/{{operation_id}}/resize" in paths


def test_move_benchmark_ten_projects_fifty_operations(
    engine: Engine, seeded_case: SeededCase, capsys
) -> None:
    benchmark, _ = _prepare_benchmark_replan(engine, seeded_case)
    case, request = benchmark.case, benchmark.request
    with engine.connect() as connection:
        row = connection.execute(text("""
            SELECT opr.required_operation_id,ph.id,opr.planned_start_at
              FROM planning.operation_plan_results opr
              JOIN production.required_operation_phases ph
                ON ph.organization_id=opr.organization_id
               AND ph.required_operation_id=opr.required_operation_id
             WHERE opr.organization_id=:org
               AND opr.schedule_solution_id=(
                   SELECT schedule_solution_id FROM planning.plan_versions
                    WHERE organization_id=:org AND id=:plan
               )
               AND NOT EXISTS(
                   SELECT 1 FROM execution.operation_executions oe
                    WHERE oe.organization_id=opr.organization_id
                      AND oe.required_operation_id=opr.required_operation_id
               )
             ORDER BY opr.planned_start_at,opr.required_operation_id
             LIMIT 1
        """), {"org": case.organization_id,
                 "plan": request.base_plan_version_id}).one()
    command = _move(
        case, row[0], row[1], request.base_plan_version_id,
        row[2] + timedelta(days=1),
    )
    started = perf_counter()
    result = MoveScheduledActivityService(
        PostgresSchedulingUnitOfWorkFactory(engine)
    ).execute(command)
    elapsed_ms = (perf_counter() - started) * 1000
    payload_bytes = len(json.dumps(asdict(result), default=str).encode("utf-8"))
    print(
        f"assisted_move_postgresql projects={result.affected_projects} "
        f"operations={result.changed_operations} elapsed_ms={elapsed_ms:.2f} "
        f"payload_bytes={payload_bytes}"
    )
    assert result.status == "ready"
    assert elapsed_ms < 5000
    assert payload_bytes < 65536
