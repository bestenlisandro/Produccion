from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from time import perf_counter
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from production_besten.api.app import create_app
from production_besten.application.replanning_services import (
    AcceptReplanService, RejectReplanService, ReplanService,
)
from production_besten.domain.errors import (
    EntityNotFound, IdempotencyConflict, ReplanConflict, SchedulingBaseStale,
)
from production_besten.domain.replanning import AcceptReplan, RejectReplan
from production_besten.persistence.scheduling_uow import PostgresSchedulingUnitOfWorkFactory

from .conftest import SeededCase, seed_case
from .test_replanning import ReplannedCase, _prepare, _prepare_benchmark_replan


@dataclass(frozen=True)
class PromotedCase:
    replanned: ReplannedCase
    command: AcceptReplan
    result: object


def _accept(engine: Engine, value: ReplannedCase, *, command_id=None,
            failpoint=None, expected_lock=1, reason="planner approved"):
    command = AcceptReplan(
        value.case.organization_id, value.case.plant_id, value.case.actor_id,
        command_id or uuid4(), value.result.scenario_id, expected_lock, reason,
    )
    result = AcceptReplanService(
        PostgresSchedulingUnitOfWorkFactory(engine, failpoint=failpoint)
    ).execute(command)
    return command, result


@pytest.fixture(scope="module")
def promoted(engine: Engine) -> PromotedCase:
    case = seed_case(engine)
    with engine.begin() as connection:
        connection.execute(text("UPDATE core.plants SET communication_threshold_business_days=0 WHERE organization_id=:org AND id=:plant"), {"org": case.organization_id, "plant": case.plant_id})
        connection.execute(text("""
            INSERT INTO portal.communicated_dates
              (organization_id,project_id,date_kind,communicated_date,approved_by,communicated_at)
            VALUES (:org,:project,'delivery',:date,:actor,:at)
        """), {"org": case.organization_id, "project": case.project_id,
                "date": case.cutoff_at.date(), "actor": case.actor_id,
                "at": case.cutoff_at})
    replanned = _prepare(engine, case)
    command, result = _accept(engine, replanned)
    return PromotedCase(replanned, command, result)


PROMOTION_INVARIANTS = (
    "new_pointer", "new_version_number", "new_published", "new_open_range",
    "old_superseded", "old_closed_range", "previous_link", "solution_reference",
    "scenario_reference", "state_reference", "definition_reference",
    "scenario_confirmed", "scenario_parameter_link", "lock_incremented",
    "single_current", "no_validity_overlap", "audit_once", "audit_actor",
    "audit_command", "outbox_once", "outbox_pending", "outbox_payload",
    "execution_unchanged", "remaining_unchanged", "communicated_date_unchanged",
    "communication_recommended", "segments_preserved", "assignments_preserved",
    "reservations_preserved", "scheduler_version_unchanged",
)


@pytest.mark.parametrize("invariant", PROMOTION_INVARIANTS)
def test_accept_replan_postgresql_invariants(engine: Engine, promoted: PromotedCase,
                                             invariant: str) -> None:
    value, result = promoted.replanned, promoted.result
    case = value.case
    with engine.connect() as connection:
        plant = connection.execute(text("SELECT current_plan_version_id,promotion_lock_version FROM core.plants WHERE organization_id=:org AND id=:plant"), {"org": case.organization_id, "plant": case.plant_id}).mappings().one()
        new = connection.execute(text("SELECT *,lower(valid_during) AS starts,upper(valid_during) AS ends FROM planning.plan_versions WHERE organization_id=:org AND id=:id"), {"org": case.organization_id, "id": result.plan_version_id}).mappings().one()
        old = connection.execute(text("SELECT *,lower(valid_during) AS starts,upper(valid_during) AS ends FROM planning.plan_versions WHERE organization_id=:org AND id=:id"), {"org": case.organization_id, "id": case.plan_version_id}).mappings().one()
        scenario = connection.execute(text("SELECT status,parameters FROM planning.scenarios WHERE organization_id=:org AND id=:id"), {"org": case.organization_id, "id": result.scenario_id}).mappings().one()
        current_count = connection.scalar(text("SELECT count(*) FROM planning.plan_versions WHERE organization_id=:org AND plant_id=:plant AND status='published' AND upper_inf(valid_during)"), {"org": case.organization_id, "plant": case.plant_id})
        overlap_count = connection.scalar(text("SELECT count(*) FROM planning.plan_versions a JOIN planning.plan_versions b ON b.organization_id=a.organization_id AND b.plant_id=a.plant_id AND b.id>a.id AND b.valid_during && a.valid_during WHERE a.organization_id=:org AND a.plant_id=:plant"), {"org": case.organization_id, "plant": case.plant_id})
        audit = connection.execute(text("SELECT * FROM audit.audit_entries WHERE organization_id=:org AND request_id=:request"), {"org": case.organization_id, "request": promoted.command.command_id}).mappings().all()
        outbox = connection.execute(text("SELECT * FROM integration.outbox_messages WHERE organization_id=:org AND logical_key=:key"), {"org": case.organization_id, "key": f"plan-version-promoted:{promoted.command.command_id}"}).mappings().all()
        execution = connection.execute(text("SELECT status,started_at,completed_at FROM execution.operation_executions WHERE organization_id=:org AND id=:id"), {"org": case.organization_id, "id": case.execution_id}).one()
        remaining = connection.scalar(text("SELECT id FROM execution.remaining_estimate_revisions WHERE organization_id=:org AND operation_execution_id=:execution AND superseded_at IS NULL"), {"org": case.organization_id, "execution": case.execution_id})
        communicated = connection.scalar(text("SELECT communicated_date FROM portal.communicated_dates WHERE organization_id=:org AND project_id=:project ORDER BY communicated_at DESC LIMIT 1"), {"org": case.organization_id, "project": case.project_id})
        counts = connection.execute(text("SELECT (SELECT count(*) FROM planning.assignment_segments WHERE organization_id=:org AND schedule_solution_id=:solution),(SELECT count(*) FROM planning.human_segment_assignments WHERE organization_id=:org AND schedule_solution_id=:solution),(SELECT count(*) FROM planning.physical_resource_reservations WHERE organization_id=:org AND schedule_solution_id=:solution)"), {"org": case.organization_id, "solution": result.schedule_solution_id}).one()
        algorithm = connection.scalar(text("SELECT algorithm_version FROM planning.schedule_solutions WHERE organization_id=:org AND id=:solution"), {"org": case.organization_id, "solution": result.schedule_solution_id})
    checks = {
        "new_pointer": plant["current_plan_version_id"] == result.plan_version_id,
        "new_version_number": new["version_no"] == 2,
        "new_published": new["status"] == "published",
        "new_open_range": new["ends"] is None,
        "old_superseded": old["status"] == "superseded",
        "old_closed_range": old["ends"] == new["starts"],
        "previous_link": new["previous_version_id"] == old["id"],
        "solution_reference": new["schedule_solution_id"] == value.result.solution_id,
        "scenario_reference": new["source_scenario_id"] == value.result.scenario_id,
        "state_reference": new["planning_state_revision_id"] == value.request.planning_state_revision_id,
        "definition_reference": new["product_definition_revision_id"] == case.definition_revision_id,
        "scenario_confirmed": scenario["status"] == "confirmed",
        "scenario_parameter_link": scenario["parameters"]["promoted_plan_version_id"] == str(result.plan_version_id),
        "lock_incremented": plant["promotion_lock_version"] == 2,
        "single_current": current_count == 1,
        "no_validity_overlap": overlap_count == 0,
        "audit_once": len(audit) == 1,
        "audit_actor": audit[0]["actor_user_id"] == case.actor_id,
        "audit_command": audit[0]["metadata"]["command"] == "ACCEPT_REPLAN",
        "outbox_once": len(outbox) == 1,
        "outbox_pending": outbox[0]["status"] == "pending",
        "outbox_payload": outbox[0]["payload"]["plan_version_id"] == str(result.plan_version_id),
        "execution_unchanged": execution[0] == "running" and execution[2] is None,
        "remaining_unchanged": remaining == value.remaining_revision_id,
        "communicated_date_unchanged": communicated == case.cutoff_at.date(),
        "communication_recommended": result.communication_recommended,
        "segments_preserved": counts[0] > 0,
        "assignments_preserved": counts[1] > 0,
        "reservations_preserved": counts[2] > 0,
        "scheduler_version_unchanged": algorithm == "v1-greedy-4",
    }
    assert checks[invariant]


def test_accept_replay_returns_same_plan(engine: Engine, seeded_case: SeededCase) -> None:
    value = _prepare(engine, seeded_case)
    command, first = _accept(engine, value)
    second = AcceptReplanService(PostgresSchedulingUnitOfWorkFactory(engine)).execute(command)
    assert second.plan_version_id == first.plan_version_id
    assert second.idempotent_replay


def test_double_click_does_not_create_v7(engine: Engine, seeded_case: SeededCase) -> None:
    value = _prepare(engine, seeded_case)
    command, _ = _accept(engine, value)
    AcceptReplanService(PostgresSchedulingUnitOfWorkFactory(engine)).execute(command)
    with engine.connect() as connection:
        count = connection.scalar(text("SELECT count(*) FROM planning.plan_versions WHERE organization_id=:org AND plant_id=:plant"), {"org": seeded_case.organization_id, "plant": seeded_case.plant_id})
    assert count == 2


def test_accept_idempotency_conflict(engine: Engine, seeded_case: SeededCase) -> None:
    value = _prepare(engine, seeded_case)
    command, _ = _accept(engine, value)
    with pytest.raises(IdempotencyConflict):
        AcceptReplanService(PostgresSchedulingUnitOfWorkFactory(engine)).execute(
            replace(command, reason="different payload")
        )


@pytest.mark.parametrize("status", ["stale", "rejected"])
def test_non_promotable_scenario_status(engine: Engine, seeded_case: SeededCase,
                                        status: str) -> None:
    value = _prepare(engine, seeded_case)
    with engine.begin() as connection:
        connection.execute(text("UPDATE planning.scenarios SET status=:status WHERE organization_id=:org AND id=:id"), {"status": status, "org": seeded_case.organization_id, "id": value.result.scenario_id})
    error = SchedulingBaseStale if status == "stale" else ReplanConflict
    with pytest.raises(error):
        _accept(engine, value)


def test_planning_state_revision_mismatch(engine: Engine, seeded_case: SeededCase) -> None:
    value = _prepare(engine, seeded_case)
    with engine.begin() as connection:
        number = connection.scalar(text("SELECT current_revision_no FROM planning.planning_state_heads WHERE organization_id=:org AND plant_id=:plant"), {"org": seeded_case.organization_id, "plant": seeded_case.plant_id})
        revision = uuid4()
        connection.execute(text("INSERT INTO planning.planning_state_revisions(id,organization_id,plant_id,revision_no,reason,transaction_key,change_summary,created_by) VALUES (:id,:org,:plant,:number,'new reality',:key,'{}',:actor)"), {"id": revision, "org": seeded_case.organization_id, "plant": seeded_case.plant_id, "number": number + 1, "key": uuid4(), "actor": seeded_case.actor_id})
        connection.execute(text("UPDATE planning.planning_state_heads SET current_revision_id=:id,current_revision_no=:number WHERE organization_id=:org AND plant_id=:plant"), {"id": revision, "number": number + 1, "org": seeded_case.organization_id, "plant": seeded_case.plant_id})
    with pytest.raises(SchedulingBaseStale):
        _accept(engine, value)


def test_product_definition_revision_mismatch(engine: Engine, seeded_case: SeededCase) -> None:
    value = _prepare(engine, seeded_case)
    revision = uuid4()
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO production.product_definition_revisions(id,organization_id,plant_id,revision_no,snapshot_schema_version,canonicalization_version,canonical_snapshot,snapshot_sha256,reason,created_by) VALUES (:id,:org,:plant,2,1,1,'{}',digest(:value,'sha256'),'changed',:actor)"), {"id": revision, "org": seeded_case.organization_id, "plant": seeded_case.plant_id, "value": revision.hex, "actor": seeded_case.actor_id})
        connection.execute(text("UPDATE core.plants SET current_product_definition_revision_id=:id WHERE organization_id=:org AND id=:plant"), {"id": revision, "org": seeded_case.organization_id, "plant": seeded_case.plant_id})
    with pytest.raises(SchedulingBaseStale):
        _accept(engine, value)


def test_cross_tenant_accept_is_hidden(engine: Engine, seeded_case: SeededCase) -> None:
    value = _prepare(engine, seeded_case)
    with pytest.raises(EntityNotFound):
        AcceptReplanService(PostgresSchedulingUnitOfWorkFactory(engine)).execute(AcceptReplan(
            seeded_case.other_organization_id, seeded_case.plant_id, seeded_case.actor_id,
            uuid4(), value.result.scenario_id, 1,
        ))


def test_two_parallel_scenarios_have_one_winner(engine: Engine,
                                                seeded_case: SeededCase) -> None:
    first = _prepare(engine, seeded_case)
    second_request = replace(first.request, idempotency_key=uuid4().hex,
                             code=f"RP-{uuid4().hex}")
    second_result = ReplanService(PostgresSchedulingUnitOfWorkFactory(engine)).execute(second_request)
    commands = [
        AcceptReplan(seeded_case.organization_id, seeded_case.plant_id,
                     seeded_case.actor_id, uuid4(), scenario, 1)
        for scenario in (first.result.scenario_id, second_result.scenario_id)
    ]
    def run(command):
        try:
            return AcceptReplanService(PostgresSchedulingUnitOfWorkFactory(engine)).execute(command)
        except Exception as exc:
            return exc
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [future.result() for future in [pool.submit(run, item) for item in commands]]
    assert sum(not isinstance(item, Exception) for item in results) == 1
    assert sum(isinstance(item, (ReplanConflict, SchedulingBaseStale)) for item in results) == 1
    with engine.connect() as connection:
        statuses = connection.execute(text("SELECT status FROM planning.scenarios WHERE organization_id=:org AND id=ANY(:ids) ORDER BY status"), {"org": seeded_case.organization_id, "ids": [item.scenario_id for item in commands]}).scalars().all()
    assert statuses == ["confirmed", "stale"]


@pytest.mark.parametrize("failpoint", [
    "after_close_previous", "after_new_plan", "during_materialization",
    "after_current_pointer", "during_audit", "during_outbox",
])
def test_accept_failpoints_roll_back_everything(engine: Engine,
                                                seeded_case: SeededCase,
                                                failpoint: str) -> None:
    value = _prepare(engine, seeded_case)
    with pytest.raises(RuntimeError):
        _accept(engine, value, failpoint=failpoint)
    with engine.connect() as connection:
        plant = connection.execute(text("SELECT current_plan_version_id,promotion_lock_version FROM core.plants WHERE organization_id=:org AND id=:plant"), {"org": seeded_case.organization_id, "plant": seeded_case.plant_id}).one()
        scenario = connection.scalar(text("SELECT status FROM planning.scenarios WHERE organization_id=:org AND id=:scenario"), {"org": seeded_case.organization_id, "scenario": value.result.scenario_id})
        plans = connection.scalar(text("SELECT count(*) FROM planning.plan_versions WHERE organization_id=:org AND plant_id=:plant"), {"org": seeded_case.organization_id, "plant": seeded_case.plant_id})
        audit = connection.scalar(text("SELECT count(*) FROM audit.audit_entries WHERE organization_id=:org AND action_code='SCENARIO_PROMOTED'"), {"org": seeded_case.organization_id})
        outbox = connection.scalar(text("SELECT count(*) FROM integration.outbox_messages WHERE organization_id=:org AND event_type='PLAN_VERSION_PROMOTED'"), {"org": seeded_case.organization_id})
    assert plant == (seeded_case.plan_version_id, 1)
    assert scenario == "ready"
    assert plans == 1 and audit == 0 and outbox == 0


def _headers(case, *, organization_id=None, key=None):
    return {
        "X-Dev-User-Id": str(case.actor_id),
        "X-Dev-Organization-Id": str(organization_id or case.organization_id),
        "X-Dev-Plant-Id": str(case.plant_id),
        "Idempotency-Key": str(key or uuid4()),
    }


def _client(engine):
    return TestClient(create_app(engine=engine), raise_server_exceptions=False)


def test_accept_endpoint_success_and_scenario_read(engine: Engine,
                                                   seeded_case: SeededCase) -> None:
    value = _prepare(engine, seeded_case)
    response = _client(engine).post(f"/scenarios/{value.result.scenario_id}/accept",
        headers=_headers(seeded_case), json={"expected_promotion_lock_version": 1})
    assert response.status_code == 201
    read = _client(engine).get(f"/scenarios/{value.result.scenario_id}",
                               headers={k: v for k, v in _headers(seeded_case).items()
                                        if k != "Idempotency-Key"})
    assert read.status_code == 200
    assert read.json()["promoted"] is True
    assert read.json()["promoted_plan_version_id"] == response.json()["plan_version_id"]


def test_accept_endpoint_replay(engine: Engine, seeded_case: SeededCase) -> None:
    value = _prepare(engine, seeded_case)
    key = uuid4()
    client = _client(engine)
    first = client.post(f"/scenarios/{value.result.scenario_id}/accept",
        headers=_headers(seeded_case, key=key), json={"expected_promotion_lock_version": 1})
    replay = client.post(f"/scenarios/{value.result.scenario_id}/accept",
        headers=_headers(seeded_case, key=key), json={"expected_promotion_lock_version": 1})
    assert first.status_code == 201 and replay.status_code == 200
    assert replay.json()["plan_version_id"] == first.json()["plan_version_id"]
    assert replay.json()["idempotent_replay"] is True


def test_accept_endpoint_stale_is_409(engine: Engine, seeded_case: SeededCase) -> None:
    value = _prepare(engine, seeded_case)
    with engine.begin() as connection:
        connection.execute(text("UPDATE planning.scenarios SET status='stale' WHERE organization_id=:org AND id=:id"), {"org": seeded_case.organization_id, "id": value.result.scenario_id})
    response = _client(engine).post(f"/scenarios/{value.result.scenario_id}/accept",
        headers=_headers(seeded_case), json={"expected_promotion_lock_version": 1})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "SCHEDULING_BASE_STALE"


def test_accept_endpoint_cross_tenant_is_404(engine: Engine,
                                             seeded_case: SeededCase) -> None:
    value = _prepare(engine, seeded_case)
    response = _client(engine).post(f"/scenarios/{value.result.scenario_id}/accept",
        headers=_headers(seeded_case, organization_id=seeded_case.other_organization_id),
        json={"expected_promotion_lock_version": 1})
    assert response.status_code == 404


def test_accept_openapi_contract(engine: Engine) -> None:
    document = _client(engine).get("/openapi.json").json()
    operation = document["paths"]["/scenarios/{scenario_id}/accept"]["post"]
    assert operation["responses"]["201"]
    assert any(item["name"] == "Idempotency-Key" for item in operation["parameters"])


def test_accept_transaction_benchmark(engine: Engine, seeded_case: SeededCase,
                                      capsys) -> None:
    value, _ = _prepare_benchmark_replan(engine, seeded_case)
    started = perf_counter()
    _, result = _accept(engine, value)
    elapsed_ms = (perf_counter() - started) * 1000
    with engine.connect() as connection:
        counts = connection.execute(text("SELECT (SELECT count(*) FROM planning.assignment_segments WHERE schedule_solution_id=:solution),(SELECT count(*) FROM planning.human_segment_assignments WHERE schedule_solution_id=:solution),(SELECT count(*) FROM planning.physical_resource_reservations WHERE schedule_solution_id=:solution)"), {"solution": result.schedule_solution_id}).one()
    print(f"accept_replan_postgresql projects={len(value.result.frontier_project_ids)} operations={len(value.result.frontier_operation_ids)} elapsed_ms={elapsed_ms:.2f} segments={counts[0]} humans={counts[1]} reservations={counts[2]} audit=1 outbox=1")
    assert len(value.result.frontier_project_ids) == 10
    assert len(value.result.frontier_operation_ids) == 50
    assert elapsed_ms < 5000
