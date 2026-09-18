from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import text

from production_besten.application.product_definition_services import (
    CreateProductDefinitionRevisionService,
    CreateProductionBatchService,
    CreateProjectService,
    CreateRequiredOperationPhaseService,
    CreateRequiredOperationService,
    DefineBatchRouteService,
)
from production_besten.domain.errors import (
    EntityNotFound,
    InvalidProductDefinition,
    PrecedenceCycle,
    ProductDefinitionConflict,
)
from production_besten.domain.product_definition import (
    CreateProductDefinitionRevision,
    CreateProductionBatch,
    CreateProject,
    CreateRequiredOperation,
    CreateRequiredOperationPhase,
    DefineBatchRoute,
    LaborRequirement,
    OperationGate,
    PhysicalRequirement,
)
from production_besten.persistence.product_definition_uow import (
    PostgresProductDefinitionUnitOfWork,
    PostgresProductDefinitionUnitOfWorkFactory,
    canonical_json,
)


def _factory(engine, failpoint=None):
    return PostgresProductDefinitionUnitOfWorkFactory(engine, failpoint=failpoint)


def _references(engine, case):
    with engine.connect() as conn:
        return conn.execute(text("""
            SELECT customer_id,priority_id FROM core.projects
             WHERE organization_id=:org AND id=:project
        """), {"org": case.organization_id, "project": case.project_id}).mappings().one()


def _project_command(engine, case, *, organization_id=None, plant_id=None, code=None):
    refs = _references(engine, case)
    return CreateProject(organization_id or case.organization_id, plant_id or case.plant_id,
        refs["customer_id"], refs["priority_id"], code or f"P-{uuid4().hex[:10]}", "New project",
        case.actor_id, committed_date=datetime(2026, 10, 1, tzinfo=timezone.utc).date())


def _batch(case, *, project_id=None, organization_id=None, code=None, command_id=None):
    return CreateProductionBatch(organization_id or case.organization_id, project_id or case.project_id,
        code or f"L-{uuid4().hex[:10]}", "New lot", case.actor_id, command_id or uuid4(), quantity=2, unit="unit")


def _operation(case, *, project_id=None, lot_id=None, code=None, command_id=None,
               predecessors=(), successors=(), route_step_id=None, organization_id=None):
    return CreateRequiredOperation(organization_id or case.organization_id, project_id or case.project_id,
        case.operation_definition_id, code or f"O-{uuid4().hex[:10]}", "Cut", case.actor_id,
        command_id or uuid4(), project_lot_id=case.project_lot_id if lot_id is None else lot_id,
        route_step_id=route_step_id, predecessor_operation_ids=predecessors,
        successor_operation_ids=successors)


def _phase(case, operation_id, *, command_id=None, labor=(), physical=(), gates=(), sequence=1):
    return CreateRequiredOperationPhase(case.organization_id, operation_id, sequence,
        f"PH-{sequence}", "Work", "labor", 120, "splittable", case.actor_id,
        command_id or uuid4(), labor_requirements=labor, physical_requirements=physical, gates=gates)


def _route(engine, case, status="published"):
    template, version, step, phase = uuid4(), uuid4(), uuid4(), uuid4()
    suffix = version.hex[:8]
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO production.route_templates(id,organization_id,code,name,status) VALUES (:id,:org,:code,'Route','active')"), {"id": template, "org": case.organization_id, "code": f"R-{suffix}"})
        conn.execute(text("INSERT INTO production.route_versions(id,organization_id,route_template_id,version_no,status,published_at,published_by) VALUES (:id,:org,:template,1,:status,CASE WHEN :status='published' THEN now() END,:actor)"), {"id": version, "org": case.organization_id, "template": template, "status": status, "actor": case.actor_id})
        conn.execute(text("INSERT INTO production.route_steps(id,organization_id,route_version_id,operation_definition_id,code,name,sequence_hint) VALUES (:id,:org,:version,:definition,'CUT','Cut',1)"), {"id": step, "org": case.organization_id, "version": version, "definition": case.operation_definition_id})
        conn.execute(text("INSERT INTO production.route_step_phase_templates(id,organization_id,route_step_id,sequence_no,code,name,estimate_kind,original_estimate_minutes,split_policy) VALUES (:id,:org,:step,1,'WORK','Work','labor',120,'splittable')"), {"id": phase, "org": case.organization_id, "step": step})
    return version, step, phase


def _head(engine, case):
    with engine.connect() as conn:
        return conn.execute(text("SELECT current_revision_id,current_revision_no FROM planning.planning_state_heads WHERE organization_id=:org AND plant_id=:plant"), {"org": case.organization_id, "plant": case.plant_id}).mappings().one()


def _freeze(case, command_id=None, reason="approved definition"):
    return CreateProductDefinitionRevision(case.organization_id, case.plant_id, case.actor_id,
                                            command_id or uuid4(), reason)


def test_create_project_persists_tenant_plant_priority_and_commitment(engine, seeded_case):
    command = _project_command(engine, seeded_case)
    result = CreateProjectService(_factory(engine)).execute(command)
    with engine.connect() as conn:
        row = conn.execute(text("SELECT * FROM core.projects WHERE id=:id"), {"id": result.entity_id}).mappings().one()
    assert (row["organization_id"], row["plant_id"], row["priority_id"], row["committed_date"]) == (command.organization_id, command.plant_id, command.priority_id, command.committed_date)
    assert result.planning_state_revision_id is None


def test_duplicate_project_code_is_controlled(engine, seeded_case):
    service = CreateProjectService(_factory(engine))
    first = _project_command(engine, seeded_case, code=f"P-{uuid4().hex[:8]}")
    service.execute(first)
    with pytest.raises(ProductDefinitionConflict):
        service.execute(_project_command(engine, seeded_case, code=first.code))


def test_create_project_cross_tenant_rejected(engine, seeded_case):
    with pytest.raises(EntityNotFound):
        CreateProjectService(_factory(engine)).execute(_project_command(engine, seeded_case, organization_id=seeded_case.other_organization_id))


def test_create_batch_is_project_owned_lot_and_advances_state_once(engine, seeded_case):
    before = _head(engine, seeded_case)
    result = CreateProductionBatchService(_factory(engine)).execute(_batch(seeded_case))
    after = _head(engine, seeded_case)
    with engine.connect() as conn:
        row = conn.execute(text("SELECT project_id,sequence_no FROM core.project_lots WHERE id=:id"), {"id": result.entity_id}).one()
    assert row == (seeded_case.project_id, 2)
    assert after["current_revision_no"] == before["current_revision_no"] + 1 == result.planning_state_revision_no


def test_batch_command_is_idempotent(engine, seeded_case):
    service = CreateProductionBatchService(_factory(engine))
    command = _batch(seeded_case)
    first, second = service.execute(command), service.execute(command)
    assert first.entity_id == second.entity_id and second.idempotent_replay


def test_idempotency_key_reuse_with_different_batch_data_is_rejected(engine, seeded_case):
    service = CreateProductionBatchService(_factory(engine))
    command_id = uuid4()
    service.execute(_batch(seeded_case, code="IDEMP-A", command_id=command_id))
    with pytest.raises(ProductDefinitionConflict):
        service.execute(_batch(seeded_case, code="IDEMP-B", command_id=command_id))


def test_two_concurrent_batches_get_distinct_sequences(engine, seeded_case):
    service = CreateProductionBatchService(_factory(engine))
    commands = [_batch(seeded_case), _batch(seeded_case)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(service.execute, commands))
    with engine.connect() as conn:
        sequences = conn.execute(text("SELECT sequence_no FROM core.project_lots WHERE id=ANY(:ids) ORDER BY sequence_no"), {"ids": [x.entity_id for x in results]}).scalars().all()
    assert len(set(sequences)) == 2


def test_duplicate_batch_code_and_sequence_are_controlled(engine, seeded_case):
    service = CreateProductionBatchService(_factory(engine))
    first = _batch(seeded_case, code=f"L-{uuid4().hex[:8]}")
    service.execute(first)
    with pytest.raises(ProductDefinitionConflict):
        service.execute(_batch(seeded_case, code=first.code))
    with pytest.raises(ProductDefinitionConflict):
        service.execute(CreateProductionBatch(seeded_case.organization_id, seeded_case.project_id,
            f"L-{uuid4().hex[:8]}", "Lot", seeded_case.actor_id, uuid4(), sequence_no=1))


def test_define_published_route_and_replace_preserves_history(engine, seeded_case):
    service = DefineBatchRouteService(_factory(engine))
    first, _, _ = _route(engine, seeded_case)
    second, _, _ = _route(engine, seeded_case)
    at = datetime.now(timezone.utc)
    one = service.execute(DefineBatchRoute(seeded_case.organization_id, seeded_case.project_lot_id, first, at, seeded_case.actor_id, uuid4()))
    two = service.execute(DefineBatchRoute(seeded_case.organization_id, seeded_case.project_lot_id, second, at + timedelta(minutes=1), seeded_case.actor_id, uuid4()))
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT id,is_active,upper(valid_during) AS finish FROM production.lot_route_assignments WHERE id=ANY(:ids) ORDER BY created_at"), {"ids": [one.entity_id, two.entity_id]}).all()
    assert rows[0][1:] == (False, at + timedelta(minutes=1)) and rows[1][1] is True


def test_unpublished_route_is_rejected(engine, seeded_case):
    version, _, _ = _route(engine, seeded_case, "draft")
    with pytest.raises(InvalidProductDefinition):
        DefineBatchRouteService(_factory(engine)).execute(DefineBatchRoute(seeded_case.organization_id, seeded_case.project_lot_id, version, datetime.now(timezone.utc), seeded_case.actor_id, uuid4()))


def test_two_lots_can_have_distinct_routes_and_availability(engine, seeded_case):
    second_lot = CreateProductionBatchService(_factory(engine)).execute(CreateProductionBatch(
        seeded_case.organization_id, seeded_case.project_id, f"L-{uuid4().hex[:8]}", "Black",
        seeded_case.actor_id, uuid4(), hardware_status="pending",
        hardware_available_at=datetime.now(timezone.utc) + timedelta(days=7))).entity_id
    route_a, _, _ = _route(engine, seeded_case)
    route_b, _, _ = _route(engine, seeded_case)
    service = DefineBatchRouteService(_factory(engine))
    at = datetime.now(timezone.utc)
    service.execute(DefineBatchRoute(seeded_case.organization_id, seeded_case.project_lot_id, route_a, at, seeded_case.actor_id, uuid4()))
    service.execute(DefineBatchRoute(seeded_case.organization_id, second_lot, route_b, at, seeded_case.actor_id, uuid4()))
    with engine.connect() as conn:
        assignments = conn.execute(text("SELECT project_lot_id,route_version_id FROM production.lot_route_assignments WHERE project_lot_id=ANY(:lots) AND is_active"), {"lots": [seeded_case.project_lot_id, second_lot]}).all()
    assert set(assignments) == {(seeded_case.project_lot_id, route_a), (second_lot, route_b)}


def test_create_required_operation_is_demand_not_schedule(engine, seeded_case):
    result = CreateRequiredOperationService(_factory(engine)).execute(_operation(seeded_case))
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM production.required_operations WHERE id=:id"), {"id": result.entity_id}) == 1
        assert conn.scalar(text("SELECT count(*) FROM planning.operation_plan_results WHERE required_operation_id=:id"), {"id": result.entity_id}) == 0


def test_operation_lot_must_belong_to_project(engine, seeded_case):
    other_project = CreateProjectService(_factory(engine)).execute(_project_command(engine, seeded_case)).entity_id
    with pytest.raises(EntityNotFound):
        CreateRequiredOperationService(_factory(engine)).execute(_operation(seeded_case, project_id=other_project))


def test_operation_route_step_must_match_active_route(engine, seeded_case):
    version, step, _ = _route(engine, seeded_case)
    DefineBatchRouteService(_factory(engine)).execute(DefineBatchRoute(seeded_case.organization_id, seeded_case.project_lot_id, version, datetime.now(timezone.utc), seeded_case.actor_id, uuid4()))
    result = CreateRequiredOperationService(_factory(engine)).execute(_operation(seeded_case, route_step_id=step))
    assert result.entity_id
    _, foreign_step, _ = _route(engine, seeded_case)
    with pytest.raises(InvalidProductDefinition):
        CreateRequiredOperationService(_factory(engine)).execute(_operation(seeded_case, route_step_id=foreign_step))


def test_precedence_is_persisted(engine, seeded_case):
    result = CreateRequiredOperationService(_factory(engine)).execute(_operation(seeded_case, predecessors=(seeded_case.project_id and seeded_case.project_lot_id and _existing_operation(engine, seeded_case),)))
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM production.operation_precedences WHERE successor_operation_id=:id AND active"), {"id": result.entity_id}) == 1


def _existing_operation(engine, case):
    with engine.connect() as conn:
        return conn.scalar(text("SELECT id FROM production.required_operations WHERE organization_id=:org AND project_id=:project ORDER BY created_at LIMIT 1"), {"org": case.organization_id, "project": case.project_id})


def test_basic_precedence_cycle_is_rejected(engine, seeded_case):
    service = CreateRequiredOperationService(_factory(engine))
    a = _existing_operation(engine, seeded_case)
    b = service.execute(_operation(seeded_case, predecessors=(a,))).entity_id
    with pytest.raises(PrecedenceCycle):
        service.execute(_operation(seeded_case, predecessors=(b,), successors=(a,)))


def test_phase_with_human_requirement(engine, seeded_case):
    operation = CreateRequiredOperationService(_factory(engine)).execute(_operation(seeded_case)).entity_id
    result = CreateRequiredOperationPhaseService(_factory(engine)).execute(_phase(seeded_case, operation,
        labor=(LaborRequirement(seeded_case.skill_id, 1, 2, 180),)))
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT work_minutes FROM production.operation_labor_requirements WHERE required_operation_phase_id=:id"), {"id": result.entity_id}) == 180


def test_phase_keeps_active_use_and_occupation_separate(engine, seeded_case):
    operation = CreateRequiredOperationService(_factory(engine)).execute(_operation(seeded_case)).entity_id
    requirements = (PhysicalRequirement(1, 1, "active_use", physical_resource_type_id=seeded_case.resource_type_id),
                    PhysicalRequirement(1, 1, "occupation", work_center_id=seeded_case.work_center_id))
    result = CreateRequiredOperationPhaseService(_factory(engine)).execute(_phase(seeded_case, operation, physical=requirements))
    with engine.connect() as conn:
        assert set(conn.execute(text("SELECT usage_mode FROM production.operation_physical_requirements WHERE required_operation_phase_id=:id"), {"id": result.entity_id}).scalars()) == {"active_use", "occupation"}


def test_phase_gate_is_generic_data(engine, seeded_case):
    operation = CreateRequiredOperationService(_factory(engine)).execute(_operation(seeded_case)).entity_id
    gate = OperationGate("before_finish", "DRYING_FINISHED", available_at=datetime.now(timezone.utc))
    result = CreateRequiredOperationPhaseService(_factory(engine)).execute(_phase(seeded_case, operation, gates=(gate,)))
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT gate_type FROM production.operation_gates WHERE required_operation_phase_id=:id"), {"id": result.entity_id}) == "DRYING_FINISHED"


@pytest.mark.parametrize("target", ["material", "drawing", "hardware"])
def test_material_drawing_and_hardware_gates_are_representable(engine, seeded_case, target):
    target_id = uuid4()
    with engine.begin() as conn:
        if target == "material":
            conn.execute(text("INSERT INTO production.material_requirements(id,organization_id,project_lot_id,code,description,required_quantity,unit) VALUES (:id,:org,:lot,:code,'Board',1,'unit')"), {"id": target_id, "org": seeded_case.organization_id, "lot": seeded_case.project_lot_id, "code": f"M-{target_id.hex[:8]}"})
            gate = OperationGate("before_start", "MATERIAL_AVAILABLE", material_requirement_id=target_id)
        elif target == "drawing":
            conn.execute(text("INSERT INTO production.drawing_packages(id,organization_id,project_lot_id,code,name) VALUES (:id,:org,:lot,:code,'Drawings')"), {"id": target_id, "org": seeded_case.organization_id, "lot": seeded_case.project_lot_id, "code": f"D-{target_id.hex[:8]}"})
            gate = OperationGate("before_start", "DRAWING_RELEASED", drawing_package_id=target_id)
        else:
            target_id = seeded_case.project_lot_id
            gate = OperationGate("before_finish", "HARDWARE_READY", hardware_project_lot_id=target_id)
    operation = CreateRequiredOperationService(_factory(engine)).execute(_operation(seeded_case)).entity_id
    phase = CreateRequiredOperationPhaseService(_factory(engine)).execute(_phase(seeded_case, operation, gates=(gate,))).entity_id
    with engine.connect() as conn:
        row = conn.execute(text("SELECT material_requirement_id,drawing_package_id,hardware_project_lot_id FROM production.operation_gates WHERE required_operation_phase_id=:phase"), {"phase": phase}).one()
    assert target_id in row


def test_single_phase_and_multiphase_operations_remain_distinct(engine, seeded_case):
    service = CreateRequiredOperationService(_factory(engine))
    phase_service = CreateRequiredOperationPhaseService(_factory(engine))
    single = service.execute(_operation(seeded_case)).entity_id
    multi = service.execute(_operation(seeded_case)).entity_id
    phase_service.execute(_phase(seeded_case, single))
    phase_service.execute(_phase(seeded_case, multi, sequence=1))
    phase_service.execute(_phase(seeded_case, multi, sequence=2))
    with engine.connect() as conn:
        counts = dict(conn.execute(text("SELECT required_operation_id,count(*) FROM production.required_operation_phases WHERE required_operation_id=ANY(:ids) GROUP BY required_operation_id"), {"ids": [single, multi]}).all())
    assert counts == {single: 1, multi: 2}


def test_phase_aggregate_rolls_back_completely(engine, seeded_case):
    operation = CreateRequiredOperationService(_factory(engine)).execute(_operation(seeded_case)).entity_id
    before = _head(engine, seeded_case)
    with pytest.raises(RuntimeError):
        CreateRequiredOperationPhaseService(_factory(engine, "phase_after_insert")).execute(_phase(seeded_case, operation,
            labor=(LaborRequirement(seeded_case.skill_id, 1, 1, 60),)))
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM production.required_operation_phases WHERE required_operation_id=:id"), {"id": operation}) == 0
    assert _head(engine, seeded_case) == before


@pytest.mark.parametrize("aggregate", ["batch", "route", "operation"])
def test_definition_aggregate_rollbacks_leave_no_partial_rows_or_state_bump(engine, seeded_case, aggregate):
    before = _head(engine, seeded_case)
    if aggregate == "batch":
        command, service, table = _batch(seeded_case), CreateProductionBatchService, "core.project_lots"
        factory = _factory(engine, "batch_after_insert")
    elif aggregate == "operation":
        command, service, table = _operation(seeded_case), CreateRequiredOperationService, "production.required_operations"
        factory = _factory(engine, "operation_after_insert")
    else:
        version, _, _ = _route(engine, seeded_case)
        command = DefineBatchRoute(seeded_case.organization_id, seeded_case.project_lot_id, version, datetime.now(timezone.utc), seeded_case.actor_id, uuid4())
        service, table, factory = DefineBatchRouteService, "production.lot_route_assignments", _factory(engine, "route_after_insert")
    with engine.connect() as conn:
        count = conn.scalar(text(f"SELECT count(*) FROM {table} WHERE organization_id=:org"), {"org": seeded_case.organization_id})
    with pytest.raises(RuntimeError):
        service(factory).execute(command)
    with engine.connect() as conn:
        assert conn.scalar(text(f"SELECT count(*) FROM {table} WHERE organization_id=:org"), {"org": seeded_case.organization_id}) == count
    assert _head(engine, seeded_case) == before


def test_first_snapshot_is_frozen_and_contains_semantic_definition(engine, seeded_case):
    result = CreateProductDefinitionRevisionService(_factory(engine)).execute(_freeze(seeded_case))
    with engine.connect() as conn:
        row = conn.execute(text("SELECT canonical_snapshot,encode(snapshot_sha256,'hex') FROM production.product_definition_revisions WHERE id=:id"), {"id": result.revision_id}).one()
    encoded = canonical_json(row[0]).encode("utf-8")
    assert row[0]["projects"] and hashlib.sha256(encoded).hexdigest() == row[1] == result.snapshot_sha256
    assert str(seeded_case.project_id) not in encoded.decode()


def test_snapshot_captures_material_and_drawing_definitions_without_ids(engine, seeded_case):
    material, drawing = uuid4(), uuid4()
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO production.material_requirements(id,organization_id,project_lot_id,code,description,required_quantity,unit) VALUES (:id,:org,:lot,'BOARD','White board',2,'sheet')"), {"id": material, "org": seeded_case.organization_id, "lot": seeded_case.project_lot_id})
        conn.execute(text("INSERT INTO production.drawing_packages(id,organization_id,project_lot_id,code,name) VALUES (:id,:org,:lot,'PLAN','Plan set')"), {"id": drawing, "org": seeded_case.organization_id, "lot": seeded_case.project_lot_id})
    revision = CreateProductDefinitionRevisionService(_factory(engine)).execute(_freeze(seeded_case))
    with engine.connect() as conn:
        snapshot = conn.scalar(text("SELECT canonical_snapshot FROM production.product_definition_revisions WHERE id=:id"), {"id": revision.revision_id})
    lot = next(value for value in snapshot["projects"][0]["lots"] if value["code"].startswith("LOT-"))
    assert lot["materials"][0]["code"] == "BOARD" and lot["drawing_packages"][0]["code"] == "PLAN"
    assert str(material) not in canonical_json(snapshot) and str(drawing) not in canonical_json(snapshot)


def test_snapshot_captures_route_templates_and_operation_level_gates(engine, seeded_case):
    version, _, template_phase = _route(engine, seeded_case)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO production.route_phase_labor_requirement_templates(organization_id,route_step_phase_template_id,skill_id,min_people,max_people,work_minutes) VALUES (:org,:phase,:skill,1,2,120)"), {"org": seeded_case.organization_id, "phase": template_phase, "skill": seeded_case.skill_id})
        conn.execute(text("INSERT INTO production.route_phase_physical_requirement_templates(organization_id,route_step_phase_template_id,physical_resource_type_id,quantity,capacity_units,usage_mode) VALUES (:org,:phase,:type,1,1,'occupation')"), {"org": seeded_case.organization_id, "phase": template_phase, "type": seeded_case.resource_type_id})
        conn.execute(text("INSERT INTO production.route_phase_gate_templates(organization_id,route_step_phase_template_id,timing,gate_type,target_kind) VALUES (:org,:phase,'before_finish','HARDWARE_READY','project_lot')"), {"org": seeded_case.organization_id, "phase": template_phase})
        conn.execute(text("INSERT INTO production.operation_gates(organization_id,required_operation_id,timing,gate_type,available_at) VALUES (:org,:operation,'before_start','RELEASE_AT',:at)"), {"org": seeded_case.organization_id, "operation": _existing_operation(engine, seeded_case), "at": datetime.now(timezone.utc)})
    DefineBatchRouteService(_factory(engine)).execute(DefineBatchRoute(seeded_case.organization_id, seeded_case.project_lot_id, version, datetime.now(timezone.utc), seeded_case.actor_id, uuid4()))
    revision = CreateProductDefinitionRevisionService(_factory(engine)).execute(_freeze(seeded_case))
    with engine.connect() as conn:
        snapshot = conn.scalar(text("SELECT canonical_snapshot FROM production.product_definition_revisions WHERE id=:id"), {"id": revision.revision_id})
    lot = next(value for value in snapshot["projects"][0]["lots"] if value["code"].startswith("LOT-"))
    phase = lot["route"]["steps"][0]["phase_templates"][0]
    assert phase["labor_requirements"][0]["skill_code"].startswith("SK-")
    assert phase["physical_requirements"][0]["usage_mode"] == "occupation"
    assert phase["gates"][0]["gate_type"] == "HARDWARE_READY"
    assert lot["operations"][0]["gates"][0]["gate_type"] == "RELEASE_AT"


def test_frozen_d1_does_not_change_after_draft_mutation(engine, seeded_case):
    service = CreateProductDefinitionRevisionService(_factory(engine))
    d1 = service.execute(_freeze(seeded_case))
    with engine.connect() as conn:
        before = conn.scalar(text("SELECT canonical_snapshot FROM production.product_definition_revisions WHERE id=:id"), {"id": d1.revision_id})
    CreateProductionBatchService(_factory(engine)).execute(_batch(seeded_case))
    with engine.connect() as conn:
        after = conn.scalar(text("SELECT canonical_snapshot FROM production.product_definition_revisions WHERE id=:id"), {"id": d1.revision_id})
    assert after == before


def test_second_snapshot_differs_after_relevant_mutation(engine, seeded_case):
    service = CreateProductDefinitionRevisionService(_factory(engine))
    d1 = service.execute(_freeze(seeded_case))
    CreateProductionBatchService(_factory(engine)).execute(_batch(seeded_case))
    d2 = service.execute(_freeze(seeded_case, reason="lot added"))
    assert d2.revision_no == d1.revision_no + 1 and d2.snapshot_sha256 != d1.snapshot_sha256


def test_semantically_identical_freeze_reuses_current_revision(engine, seeded_case):
    service = CreateProductDefinitionRevisionService(_factory(engine))
    first = service.execute(_freeze(seeded_case))
    head = _head(engine, seeded_case)
    duplicate = service.execute(_freeze(seeded_case, reason="retry with same content"))
    assert duplicate.revision_id == first.revision_id and duplicate.semantic_duplicate
    assert duplicate.planning_state_revision_id is None and _head(engine, seeded_case) == head


def test_revision_command_replay_is_idempotent(engine, seeded_case):
    service = CreateProductDefinitionRevisionService(_factory(engine))
    command = _freeze(seeded_case)
    first, replay = service.execute(command), service.execute(command)
    assert first.revision_id == replay.revision_id and replay.idempotent_replay


def test_freeze_requires_nonempty_reason(engine, seeded_case):
    with pytest.raises(InvalidProductDefinition):
        CreateProductDefinitionRevisionService(_factory(engine)).execute(_freeze(seeded_case, reason=" "))


def test_canonical_json_is_order_independent_and_normalizes_timezones():
    moment = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    assert canonical_json({"b": 2, "a": moment}) == canonical_json({"a": moment, "b": 2})


def test_revision_rollback_restores_pointer_and_rows(engine, seeded_case):
    before = _head(engine, seeded_case)
    with engine.connect() as conn:
        pointer = conn.scalar(text("SELECT current_product_definition_revision_id FROM core.plants WHERE id=:id"), {"id": seeded_case.plant_id})
        count = conn.scalar(text("SELECT count(*) FROM production.product_definition_revisions WHERE organization_id=:org AND plant_id=:plant"), {"org": seeded_case.organization_id, "plant": seeded_case.plant_id})
    with pytest.raises(RuntimeError):
        CreateProductDefinitionRevisionService(_factory(engine, "revision_after_pointer")).execute(_freeze(seeded_case))
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT current_product_definition_revision_id FROM core.plants WHERE id=:id"), {"id": seeded_case.plant_id}) == pointer
        assert conn.scalar(text("SELECT count(*) FROM production.product_definition_revisions WHERE organization_id=:org AND plant_id=:plant"), {"org": seeded_case.organization_id, "plant": seeded_case.plant_id}) == count
    assert _head(engine, seeded_case) == before


def test_definition_mutation_makes_existing_scenario_stale_without_overwriting_plan(engine, seeded_case):
    with engine.connect() as conn:
        original_plan = conn.scalar(text("SELECT current_plan_version_id FROM core.plants WHERE id=:id"), {"id": seeded_case.plant_id})
    CreateProductionBatchService(_factory(engine)).execute(_batch(seeded_case))
    with engine.connect() as conn:
        stale = conn.scalar(text("""
            SELECT s.base_state_revision_id<>h.current_revision_id
              FROM planning.scenarios s JOIN planning.planning_state_heads h
                ON h.organization_id=s.organization_id AND h.plant_id=s.plant_id
             WHERE s.organization_id=:org AND s.id=(SELECT id FROM planning.scenarios WHERE organization_id=:org AND plant_id=:plant ORDER BY created_at LIMIT 1)
        """), {"org": seeded_case.organization_id, "plant": seeded_case.plant_id})
        plan = conn.scalar(text("SELECT current_plan_version_id FROM core.plants WHERE id=:id"), {"id": seeded_case.plant_id})
    assert stale and plan == original_plan


def test_two_concurrent_freezes_create_one_semantic_revision(engine, seeded_case):
    service = CreateProductDefinitionRevisionService(_factory(engine))
    commands = [_freeze(seeded_case, reason="concurrent A"), _freeze(seeded_case, reason="concurrent B")]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(service.execute, commands))
    assert results[0].revision_id == results[1].revision_id
    assert sum(value.semantic_duplicate for value in results) == 1


def test_concurrent_mutation_and_freeze_produce_coherent_snapshot(engine, seeded_case):
    lot_command = _batch(seeded_case, code=f"CON-{uuid4().hex[:8]}")
    with ThreadPoolExecutor(max_workers=2) as pool:
        future_lot = pool.submit(CreateProductionBatchService(_factory(engine)).execute, lot_command)
        future_revision = pool.submit(CreateProductDefinitionRevisionService(_factory(engine)).execute, _freeze(seeded_case, reason="concurrent freeze"))
        lot, revision = future_lot.result(), future_revision.result()
    with engine.connect() as conn:
        snapshot = conn.scalar(text("SELECT canonical_snapshot FROM production.product_definition_revisions WHERE id=:id"), {"id": revision.revision_id})
    codes = [value["code"] for project in snapshot["projects"] for value in project["lots"]]
    assert (lot_command.code in codes) == (
        revision.planning_state_revision_no > lot.planning_state_revision_no
    )


@pytest.mark.parametrize("target", ["batch", "route", "operation", "phase", "revision"])
def test_cross_tenant_commands_reject_real_foreign_ids(engine, seeded_case, target):
    service_and_command = {
        "batch": (CreateProductionBatchService, _batch(seeded_case, organization_id=seeded_case.other_organization_id)),
        "operation": (CreateRequiredOperationService, _operation(seeded_case, organization_id=seeded_case.other_organization_id)),
        "revision": (CreateProductDefinitionRevisionService, CreateProductDefinitionRevision(seeded_case.other_organization_id, seeded_case.plant_id, seeded_case.actor_id, uuid4(), "foreign")),
    }
    if target == "route":
        version, _, _ = _route(engine, seeded_case)
        pair = (DefineBatchRouteService, DefineBatchRoute(seeded_case.other_organization_id, seeded_case.project_lot_id, version, datetime.now(timezone.utc), seeded_case.actor_id, uuid4()))
    elif target == "phase":
        pair = (CreateRequiredOperationPhaseService, _phase(seeded_case, _existing_operation(engine, seeded_case)))
        pair = (pair[0], CreateRequiredOperationPhase(seeded_case.other_organization_id, pair[1].required_operation_id, 9, "FOREIGN", "Foreign", "labor", 1, "splittable", seeded_case.actor_id, uuid4()))
    else:
        pair = service_and_command[target]
    with pytest.raises(EntityNotFound):
        pair[0](_factory(engine)).execute(pair[1])
