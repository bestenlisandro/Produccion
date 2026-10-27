from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, text
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
    DefinitionMutationResult,
    ProductDefinitionRevisionResult,
)

SNAPSHOT_SCHEMA_VERSION = 1
CANONICALIZATION_VERSION = 1


class PostgresProductDefinitionUnitOfWork:
    """Transactional adapter for editable demand and immutable definition snapshots."""

    def __init__(self, engine: Engine, *, failpoint: str | None = None) -> None:
        self._engine = engine
        self._failpoint = failpoint
        self._connection: Connection | None = None
        self._transaction: Any = None

    def __enter__(self) -> "PostgresProductDefinitionUnitOfWork":
        self._connection = self._engine.connect()
        self._transaction = self._connection.begin()
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        try:
            if exc_type is None:
                self._transaction.commit()
            else:
                self._transaction.rollback()
        finally:
            self._connection.close()
        return False

    @property
    def conn(self) -> Connection:
        if self._connection is None:
            raise RuntimeError("unit of work is not active")
        return self._connection

    def create_project(self, command: CreateProject) -> DefinitionMutationResult:
        command.validate()
        self._lock_plant(command.organization_id, command.plant_id)
        self._require_actor(command.organization_id, command.actor_id)
        self._require_owned("core.customers", command.organization_id, command.customer_id, "customer")
        self._require_owned("core.project_priorities", command.organization_id, command.priority_id, "priority")
        if self.conn.scalar(text("SELECT EXISTS(SELECT 1 FROM core.projects WHERE organization_id=:org AND code=:code)"), {"org": command.organization_id, "code": command.code.strip()}):
            raise ProductDefinitionConflict("project code already exists in organization")
        entity_id = uuid4()
        self.conn.execute(text("""
            INSERT INTO core.projects
              (id,organization_id,plant_id,customer_id,priority_id,code,name,description,
               committed_date,desired_start_at,status)
            VALUES (:id,:org,:plant,:customer,:priority,:code,:name,:description,
                    :committed,:desired,:status)
        """), {"id": entity_id, "org": command.organization_id, "plant": command.plant_id,
                "customer": command.customer_id, "priority": command.priority_id,
                "code": command.code.strip(), "name": command.name.strip(),
                "description": command.description, "committed": command.committed_date,
                "desired": command.desired_start_at, "status": command.status})
        return DefinitionMutationResult(entity_id)

    def create_production_batch(self, command: CreateProductionBatch) -> DefinitionMutationResult:
        command.validate()
        project = self._project(command.organization_id, command.project_id, lock_plant=True)
        self._require_actor(command.organization_id, command.actor_id)
        reference = _external("CREATE_PRODUCTION_BATCH", command.command_id)
        replay = self._mutation_replay(command.organization_id, command.source_system, reference, "project_lot",
                                       {"project_id": str(command.project_id), "code": command.code.strip()})
        if replay:
            return replay
        self.conn.execute(text("SELECT id FROM core.projects WHERE organization_id=:org AND id=:id FOR UPDATE"), {"org": command.organization_id, "id": command.project_id})
        if self.conn.scalar(text("SELECT EXISTS(SELECT 1 FROM core.project_lots WHERE organization_id=:org AND project_id=:project AND code=:code)"), {"org": command.organization_id, "project": command.project_id, "code": command.code.strip()}):
            raise ProductDefinitionConflict("lot code already exists in project")
        sequence = command.sequence_no
        if sequence is None:
            sequence = int(self.conn.scalar(text("SELECT COALESCE(max(sequence_no),0)+1 FROM core.project_lots WHERE organization_id=:org AND project_id=:project"), {"org": command.organization_id, "project": command.project_id}))
        elif self.conn.scalar(text("SELECT EXISTS(SELECT 1 FROM core.project_lots WHERE organization_id=:org AND project_id=:project AND sequence_no=:sequence)"), {"org": command.organization_id, "project": command.project_id, "sequence": sequence}):
            raise ProductDefinitionConflict("lot sequence already exists in project")
        entity_id = uuid4()
        self.conn.execute(text("""
            INSERT INTO core.project_lots
              (id,organization_id,project_id,code,name,description,sequence_no,quantity,
               unit,status,hardware_status,hardware_available_at)
            VALUES (:id,:org,:project,:code,:name,:description,:sequence,:quantity,
                    :unit,:status,:hardware_status,:hardware_available_at)
        """), {"id": entity_id, "org": command.organization_id, "project": command.project_id,
                "code": command.code.strip(), "name": command.name.strip(),
                "description": command.description, "sequence": sequence,
                "quantity": command.quantity, "unit": command.unit, "status": command.status,
                "hardware_status": command.hardware_status,
                "hardware_available_at": command.hardware_available_at})
        if self._failpoint == "batch_after_insert":
            raise RuntimeError("injected failure after project lot insert")
        state_id, state_no = self._advance_state(command.organization_id, project["plant_id"],
            command.actor_id, "project lot created", "PROJECT_LOT_CREATED", "project_lot",
            entity_id, {"project_id": str(command.project_id), "code": command.code.strip(), "sequence_no": sequence},
            command.source_system, reference)
        return DefinitionMutationResult(entity_id, state_id, state_no)

    def define_batch_route(self, command: DefineBatchRoute) -> DefinitionMutationResult:
        command.validate()
        lot = self.conn.execute(text("""
            SELECT l.id,l.project_id,p.plant_id FROM core.project_lots l
            JOIN core.projects p ON p.organization_id=l.organization_id AND p.id=l.project_id
            JOIN core.plants pl ON pl.organization_id=p.organization_id AND pl.id=p.plant_id
            WHERE l.organization_id=:org AND l.id=:lot FOR UPDATE OF pl,l
        """), {"org": command.organization_id, "lot": command.project_lot_id}).mappings().one_or_none()
        if lot is None:
            raise EntityNotFound("project lot not found in organization")
        self._require_actor(command.organization_id, command.actor_id)
        reference = _external("DEFINE_BATCH_ROUTE", command.command_id)
        replay = self._mutation_replay(command.organization_id, command.source_system, reference, "lot_route_assignment",
                                       {"project_lot_id": str(command.project_lot_id), "route_version_id": str(command.route_version_id)})
        if replay:
            return replay
        route = self.conn.execute(text("""
            SELECT rv.id,rv.status FROM production.route_versions rv
            WHERE rv.organization_id=:org AND rv.id=:route
        """), {"org": command.organization_id, "route": command.route_version_id}).mappings().one_or_none()
        if route is None:
            raise EntityNotFound("route version not found in organization")
        if route["status"] != "published":
            raise InvalidProductDefinition("only a published route version can be assigned")
        current = self.conn.execute(text("""
            SELECT id,route_version_id,lower(valid_during) AS valid_from
            FROM production.lot_route_assignments
            WHERE organization_id=:org AND project_lot_id=:lot AND is_active FOR UPDATE
        """), {"org": command.organization_id, "lot": command.project_lot_id}).mappings().one_or_none()
        if current and current["route_version_id"] == command.route_version_id:
            raise ProductDefinitionConflict("route version is already active for lot")
        if current:
            if command.effective_at <= current["valid_from"]:
                raise InvalidProductDefinition("new route effective_at must follow current assignment start")
            self.conn.execute(text("""
                UPDATE production.lot_route_assignments
                   SET is_active=false,valid_during=tstzrange(lower(valid_during),:at,'[)')
                 WHERE organization_id=:org AND id=:id
            """), {"at": command.effective_at, "org": command.organization_id, "id": current["id"]})
        entity_id = uuid4()
        self.conn.execute(text("""
            INSERT INTO production.lot_route_assignments
              (id,organization_id,project_lot_id,route_version_id,valid_during,is_active,assigned_by,reason)
            VALUES (:id,:org,:lot,:route,tstzrange(:at,NULL,'[)'),true,:actor,:reason)
        """), {"id": entity_id, "org": command.organization_id, "lot": command.project_lot_id,
                "route": command.route_version_id, "at": command.effective_at,
                "actor": command.actor_id, "reason": command.reason})
        if self._failpoint == "route_after_insert":
            raise RuntimeError("injected failure after route assignment insert")
        state_id, state_no = self._advance_state(command.organization_id, lot["plant_id"], command.actor_id,
            "lot route assigned", "LOT_ROUTE_ASSIGNED", "lot_route_assignment", entity_id,
            {"project_lot_id": str(command.project_lot_id), "route_version_id": str(command.route_version_id)},
            command.source_system, reference)
        return DefinitionMutationResult(entity_id, state_id, state_no)

    def create_required_operation(self, command: CreateRequiredOperation) -> DefinitionMutationResult:
        command.validate()
        project = self._project(command.organization_id, command.project_id, lock_plant=True)
        self._require_actor(command.organization_id, command.actor_id)
        reference = _external("CREATE_REQUIRED_OPERATION", command.command_id)
        replay = self._mutation_replay(command.organization_id, command.source_system, reference, "required_operation",
                                       {"project_id": str(command.project_id),
                                        "project_lot_id": _uuid(command.project_lot_id), "code": command.code.strip()})
        if replay:
            return replay
        if command.project_lot_id is not None:
            self._require_lot_project(command.organization_id, command.project_lot_id, command.project_id)
        self._require_owned("production.operation_definitions", command.organization_id, command.operation_definition_id, "operation definition")
        if command.route_step_id is not None:
            if command.project_lot_id is None:
                raise InvalidProductDefinition("route step requires a project lot")
            compatible = self.conn.scalar(text("""
                SELECT EXISTS(SELECT 1 FROM production.route_steps rs
                JOIN production.lot_route_assignments a
                  ON a.organization_id=rs.organization_id AND a.route_version_id=rs.route_version_id
                 WHERE rs.organization_id=:org AND rs.id=:step
                   AND rs.operation_definition_id=:definition
                   AND a.project_lot_id=:lot AND a.is_active)
            """), {"org": command.organization_id, "step": command.route_step_id,
                    "definition": command.operation_definition_id, "lot": command.project_lot_id})
            if not compatible:
                raise InvalidProductDefinition("route step is not compatible with the lot active route and operation definition")
        entity_id = uuid4()
        related_ids = set(command.predecessor_operation_ids) | set(command.successor_operation_ids)
        if entity_id in related_ids:
            raise PrecedenceCycle("operation cannot precede itself")
        if related_ids:
            rows = self.conn.execute(text("SELECT id,project_id FROM production.required_operations WHERE organization_id=:org AND id=ANY(:ids)"), {"org": command.organization_id, "ids": list(related_ids)}).mappings().all()
            if {r["id"] for r in rows} != related_ids or any(r["project_id"] != command.project_id for r in rows):
                raise EntityNotFound("precedence target not found in the same project and organization")
        edges = self.conn.execute(text("""
            SELECT predecessor_operation_id,successor_operation_id
              FROM production.operation_precedences op
              JOIN production.required_operations ro ON ro.organization_id=op.organization_id AND ro.id=op.predecessor_operation_id
             WHERE op.organization_id=:org AND ro.project_id=:project AND op.active
        """), {"org": command.organization_id, "project": command.project_id}).all()
        proposed = [(value, entity_id) for value in command.predecessor_operation_ids]
        proposed += [(entity_id, value) for value in command.successor_operation_ids]
        if _has_cycle([*edges, *proposed]):
            raise PrecedenceCycle("operation precedences would create a cycle")
        if self.conn.scalar(text("SELECT EXISTS(SELECT 1 FROM production.required_operations WHERE organization_id=:org AND project_id=:project AND project_lot_id IS NOT DISTINCT FROM :lot AND code=:code)"), {"org": command.organization_id, "project": command.project_id, "lot": command.project_lot_id, "code": command.code.strip()}):
            raise ProductDefinitionConflict("operation code already exists in its project/lot scope")
        self.conn.execute(text("""
            INSERT INTO production.required_operations
              (id,organization_id,project_id,project_lot_id,operation_definition_id,route_step_id,
               operation_kind,code,name,status,earliest_start_at,settings)
            VALUES (:id,:org,:project,:lot,:definition,:step,:kind,:code,:name,:status,:earliest,CAST(:settings AS jsonb))
        """), {"id": entity_id, "org": command.organization_id, "project": command.project_id,
                "lot": command.project_lot_id, "definition": command.operation_definition_id,
                "step": command.route_step_id, "kind": command.operation_kind,
                "code": command.code.strip(), "name": command.name.strip(), "status": command.status,
                "earliest": command.earliest_start_at, "settings": _json(command.settings)})
        for predecessor, successor in proposed:
            self.conn.execute(text("""
                INSERT INTO production.operation_precedences
                  (organization_id,predecessor_operation_id,successor_operation_id,precedence_type,lag_minutes,source)
                VALUES (:org,:predecessor,:successor,:kind,:lag,'manual')
            """), {"org": command.organization_id, "predecessor": predecessor,
                    "successor": successor, "kind": command.precedence_type, "lag": command.lag_minutes})
        if self._failpoint == "operation_after_insert":
            raise RuntimeError("injected failure after required operation aggregate insert")
        state_id, state_no = self._advance_state(command.organization_id, project["plant_id"], command.actor_id,
            "required operation created", "REQUIRED_OPERATION_CREATED", "required_operation", entity_id,
            {"project_id": str(command.project_id), "project_lot_id": _uuid(command.project_lot_id),
             "code": command.code.strip(), "precedence_count": len(proposed)},
            command.source_system, reference)
        return DefinitionMutationResult(entity_id, state_id, state_no)

    def create_required_operation_phase(self, command: CreateRequiredOperationPhase) -> DefinitionMutationResult:
        command.validate()
        operation = self.conn.execute(text("""
            SELECT ro.id,ro.route_step_id,p.plant_id FROM production.required_operations ro
            JOIN core.projects p ON p.organization_id=ro.organization_id AND p.id=ro.project_id
            JOIN core.plants pl ON pl.organization_id=p.organization_id AND pl.id=p.plant_id
            WHERE ro.organization_id=:org AND ro.id=:operation FOR UPDATE OF pl,ro
        """), {"org": command.organization_id, "operation": command.required_operation_id}).mappings().one_or_none()
        if operation is None:
            raise EntityNotFound("required operation not found in organization")
        self._require_actor(command.organization_id, command.actor_id)
        reference = _external("CREATE_REQUIRED_OPERATION_PHASE", command.command_id)
        replay = self._mutation_replay(command.organization_id, command.source_system, reference, "required_operation_phase",
                                       {"required_operation_id": str(command.required_operation_id), "code": command.code.strip(),"required_people":command.required_people})
        if replay:
            return replay
        if command.route_step_phase_template_id is not None:
            compatible = self.conn.scalar(text("SELECT EXISTS(SELECT 1 FROM production.route_step_phase_templates WHERE organization_id=:org AND id=:template AND route_step_id=:step)"), {"org": command.organization_id, "template": command.route_step_phase_template_id, "step": operation["route_step_id"]})
            if not compatible:
                raise InvalidProductDefinition("phase template does not belong to the operation route step")
        if self.conn.scalar(text("SELECT EXISTS(SELECT 1 FROM production.required_operation_phases WHERE organization_id=:org AND required_operation_id=:operation AND (sequence_no=:sequence OR code=:code))"), {"org": command.organization_id, "operation": command.required_operation_id, "sequence": command.sequence_no, "code": command.code.strip()}):
            raise ProductDefinitionConflict("phase code or sequence already exists in operation")
        entity_id = uuid4()
        self.conn.execute(text("""
            INSERT INTO production.required_operation_phases
              (id,organization_id,required_operation_id,route_step_phase_template_id,sequence_no,
               code,name,estimate_kind,original_estimate_minutes,split_policy,status,earliest_start_at,required_people)
            VALUES (:id,:org,:operation,:template,:sequence,:code,:name,:estimate_kind,
                    :minutes,:split,:status,:earliest,:people)
        """), {"id": entity_id, "org": command.organization_id, "operation": command.required_operation_id,
                "template": command.route_step_phase_template_id, "sequence": command.sequence_no,
                "code": command.code.strip(), "name": command.name.strip(),
                "estimate_kind": command.estimate_kind, "minutes": command.original_estimate_minutes,
                "split": command.split_policy, "status": command.status, "earliest": command.earliest_start_at,"people":command.required_people})
        for req in command.labor_requirements:
            self._require_owned("capacity.skills", command.organization_id, req.skill_id, "skill")
            self.conn.execute(text("""
                INSERT INTO production.operation_labor_requirements
                  (organization_id,required_operation_phase_id,skill_id,min_people,max_people,
                   work_minutes,productivity_curve,is_mandatory)
                VALUES (:org,:phase,:skill,:minimum,:maximum,:minutes,CAST(:curve AS jsonb),:mandatory)
            """), {"org": command.organization_id, "phase": entity_id, "skill": req.skill_id,
                    "minimum": req.min_people, "maximum": req.max_people, "minutes": req.work_minutes,
                    "curve": _json(req.productivity_curve), "mandatory": req.is_mandatory})
        for req in command.physical_requirements:
            for table, value, label in (("capacity.physical_resource_types", req.physical_resource_type_id, "resource type"), ("capacity.physical_resource_groups", req.physical_resource_group_id, "resource group"), ("capacity.work_centers", req.work_center_id, "work center")):
                if value is not None:
                    self._require_owned(table, command.organization_id, value, label)
            self.conn.execute(text("""
                INSERT INTO production.operation_physical_requirements
                  (organization_id,required_operation_phase_id,physical_resource_type_id,
                   physical_resource_group_id,work_center_id,quantity,capacity_units,is_mandatory,usage_mode)
                VALUES (:org,:phase,:type,:group_id,:center,:quantity,:capacity,:mandatory,:mode)
            """), {"org": command.organization_id, "phase": entity_id,
                    "type": req.physical_resource_type_id, "group_id": req.physical_resource_group_id,
                    "center": req.work_center_id, "quantity": req.quantity,
                    "capacity": req.capacity_units, "mandatory": req.is_mandatory, "mode": req.usage_mode})
        for gate in command.gates:
            self._validate_gate_target(command.organization_id, gate)
            self.conn.execute(text("""
                INSERT INTO production.operation_gates
                  (organization_id,required_operation_id,required_operation_phase_id,timing,gate_type,
                   material_requirement_id,drawing_package_id,hardware_project_lot_id,
                   milestone_definition_id,available_at,config)
                VALUES (:org,:operation,:phase,:timing,:gate_type,:material,:drawing,:hardware,
                        :milestone,:available,CAST(:config AS jsonb))
            """), {"org": command.organization_id, "operation": command.required_operation_id,
                    "phase": entity_id, "timing": gate.timing, "gate_type": gate.gate_type,
                    "material": gate.material_requirement_id, "drawing": gate.drawing_package_id,
                    "hardware": gate.hardware_project_lot_id, "milestone": gate.milestone_definition_id,
                    "available": gate.available_at, "config": _json(gate.config)})
        if self._failpoint == "phase_after_insert":
            raise RuntimeError("injected failure after phase aggregate insert")
        state_id, state_no = self._advance_state(command.organization_id, operation["plant_id"], command.actor_id,
            "required operation phase created", "REQUIRED_OPERATION_PHASE_CREATED", "required_operation_phase",
            entity_id, {"required_operation_id": str(command.required_operation_id), "code": command.code.strip(),
                        "required_people":command.required_people, "labor_requirements": len(command.labor_requirements),
                        "physical_requirements": len(command.physical_requirements), "gates": len(command.gates)},
            command.source_system, reference)
        return DefinitionMutationResult(entity_id, state_id, state_no)

    def create_product_definition_revision(self, command: CreateProductDefinitionRevision) -> ProductDefinitionRevisionResult:
        command.validate()
        plant = self._lock_plant(command.organization_id, command.plant_id)
        self._require_actor(command.organization_id, command.actor_id)
        reference = _external("CREATE_PRODUCT_DEFINITION_REVISION", command.command_id)
        event = self._event(command.organization_id, command.source_system, reference)
        if event:
            revision = self.conn.execute(text("SELECT plant_id,revision_no,encode(snapshot_sha256,'hex') AS hash FROM production.product_definition_revisions WHERE organization_id=:org AND id=:id"), {"org": command.organization_id, "id": UUID(event["payload"]["product_definition_revision_id"])}).mappings().one()
            if revision["plant_id"] != command.plant_id:
                raise ProductDefinitionConflict("idempotency key was used for another plant")
            return ProductDefinitionRevisionResult(UUID(event["payload"]["product_definition_revision_id"]), revision["revision_no"], revision["hash"], event["planning_state_revision_id"], event["state_no"], bool(event["payload"].get("semantic_duplicate")), True)
        snapshot = self._build_snapshot(command.organization_id, command.plant_id)
        canonical = canonical_json(snapshot)
        digest = hashlib.sha256(canonical.encode("utf-8")).digest()
        current_id = plant["current_product_definition_revision_id"]
        if current_id is not None:
            current = self.conn.execute(text("SELECT revision_no,snapshot_sha256 FROM production.product_definition_revisions WHERE organization_id=:org AND id=:id"), {"org": command.organization_id, "id": current_id}).mappings().one()
            if current["snapshot_sha256"] == digest:
                return ProductDefinitionRevisionResult(current_id, current["revision_no"], digest.hex(), None, None, True)
        historical = self.conn.execute(text("SELECT id,revision_no FROM production.product_definition_revisions WHERE organization_id=:org AND plant_id=:plant AND snapshot_sha256=:hash"), {"org": command.organization_id, "plant": command.plant_id, "hash": digest}).mappings().one_or_none()
        if historical:
            raise ProductDefinitionConflict("snapshot matches a non-current historical revision; explicit reactivation is not part of V1")
        revision_no = int(self.conn.scalar(text("SELECT COALESCE(max(revision_no),0)+1 FROM production.product_definition_revisions WHERE organization_id=:org AND plant_id=:plant"), {"org": command.organization_id, "plant": command.plant_id}))
        revision_id = uuid4()
        self.conn.execute(text("""
            INSERT INTO production.product_definition_revisions
              (id,organization_id,plant_id,revision_no,parent_revision_id,snapshot_schema_version,
               canonicalization_version,canonical_snapshot,snapshot_sha256,reason,created_by)
            VALUES (:id,:org,:plant,:number,:parent,:schema,:canonicalizer,
                    CAST(:snapshot AS jsonb),:hash,:reason,:actor)
        """), {"id": revision_id, "org": command.organization_id, "plant": command.plant_id,
                "number": revision_no, "parent": current_id, "schema": SNAPSHOT_SCHEMA_VERSION,
                "canonicalizer": CANONICALIZATION_VERSION, "snapshot": canonical,
                "hash": digest, "reason": command.reason.strip(), "actor": command.actor_id})
        self.conn.execute(text("UPDATE core.plants SET current_product_definition_revision_id=:revision,promotion_lock_version=promotion_lock_version+1,updated_at=now(),row_version=row_version+1 WHERE organization_id=:org AND id=:plant"), {"revision": revision_id, "org": command.organization_id, "plant": command.plant_id})
        if self._failpoint == "revision_after_pointer":
            raise RuntimeError("injected failure after definition pointer update")
        state_id, state_no = self._advance_state(command.organization_id, command.plant_id, command.actor_id,
            command.reason.strip(), "PRODUCT_DEFINITION_REVISION_CREATED", "product_definition_revision",
            revision_id, {"product_definition_revision_id": str(revision_id), "revision_no": revision_no,
                          "snapshot_sha256": digest.hex(), "semantic_duplicate": False},
            command.source_system, reference)
        return ProductDefinitionRevisionResult(revision_id, revision_no, digest.hex(), state_id, state_no)

    def _build_snapshot(self, organization_id: UUID, plant_id: UUID) -> dict[str, Any]:
        projects = self.conn.execute(text("""
            SELECT p.id,p.code,p.name,p.description,p.status,p.committed_date,p.desired_start_at,
                   c.code AS customer_code,pp.code AS priority_code
              FROM core.projects p
              JOIN core.customers c ON c.organization_id=p.organization_id AND c.id=p.customer_id
              JOIN core.project_priorities pp ON pp.organization_id=p.organization_id AND pp.id=p.priority_id
             WHERE p.organization_id=:org AND p.plant_id=:plant AND p.status<>'archived'
             ORDER BY p.code
        """), {"org": organization_id, "plant": plant_id}).mappings().all()
        result: list[dict[str, Any]] = []
        for project in projects:
            p = {"code": project["code"], "name": project["name"], "description": project["description"],
                 "status": project["status"], "customer_code": project["customer_code"],
                 "priority_code": project["priority_code"], "committed_date": project["committed_date"],
                 "desired_start_at": project["desired_start_at"], "lots": [], "unassigned_operations": []}
            lots = self.conn.execute(text("""
                SELECT * FROM core.project_lots WHERE organization_id=:org AND project_id=:project
                 AND status<>'archived' ORDER BY sequence_no,code
            """), {"org": organization_id, "project": project["id"]}).mappings().all()
            for lot in lots:
                item = {"code": lot["code"], "name": lot["name"], "description": lot["description"],
                        "sequence_no": lot["sequence_no"], "quantity": lot["quantity"], "unit": lot["unit"],
                        "status": lot["status"], "hardware_status": lot["hardware_status"],
                        "hardware_available_at": lot["hardware_available_at"],
                        "materials": self._snapshot_materials(organization_id, lot["id"]),
                        "drawing_packages": self._snapshot_drawings(organization_id, lot["id"]),
                        "route": self._snapshot_route(organization_id, lot["id"]),
                        "operations": self._snapshot_operations(organization_id, project["id"], lot["id"])}
                p["lots"].append(item)
            p["unassigned_operations"] = self._snapshot_operations(organization_id, project["id"], None)
            result.append(p)
        return {"snapshot_schema_version": SNAPSHOT_SCHEMA_VERSION,
                "canonicalization_version": CANONICALIZATION_VERSION, "projects": result}

    def _snapshot_materials(self, org: UUID, lot: UUID) -> list[dict[str, Any]]:
        return [dict(value) for value in self.conn.execute(text("""
            SELECT code,description,required_quantity,unit,is_mandatory,needed_at,status
            FROM production.material_requirements
            WHERE organization_id=:org AND project_lot_id=:lot AND status<>'archived'
            ORDER BY code
        """), {"org": org, "lot": lot}).mappings().all()]

    def _snapshot_drawings(self, org: UUID, lot: UUID) -> list[dict[str, Any]]:
        return [dict(value) for value in self.conn.execute(text("""
            SELECT code,name,status,required FROM production.drawing_packages
            WHERE organization_id=:org AND project_lot_id=:lot AND status<>'archived'
            ORDER BY code
        """), {"org": org, "lot": lot}).mappings().all()]

    def _snapshot_route(self, org: UUID, lot: UUID) -> dict[str, Any] | None:
        route = self.conn.execute(text("""
            SELECT rv.id,rv.version_no,rt.code,rt.name FROM production.lot_route_assignments a
            JOIN production.route_versions rv ON rv.organization_id=a.organization_id AND rv.id=a.route_version_id
            JOIN production.route_templates rt ON rt.organization_id=rv.organization_id AND rt.id=rv.route_template_id
            WHERE a.organization_id=:org AND a.project_lot_id=:lot AND a.is_active
        """), {"org": org, "lot": lot}).mappings().one_or_none()
        if route is None:
            return None
        steps = self.conn.execute(text("""
            SELECT rs.id,rs.code,rs.name,rs.sequence_hint,rs.settings,od.code AS operation_definition_code
            FROM production.route_steps rs JOIN production.operation_definitions od
              ON od.organization_id=rs.organization_id AND od.id=rs.operation_definition_id
            WHERE rs.organization_id=:org AND rs.route_version_id=:route ORDER BY rs.sequence_hint NULLS LAST,rs.code
        """), {"org": org, "route": route["id"]}).mappings().all()
        step_values = []
        step_codes = {step["id"]: step["code"] for step in steps}
        for step in steps:
            phases = self.conn.execute(text("""
                SELECT id,sequence_no,code,name,estimate_kind,original_estimate_minutes,
                       split_policy,min_team,max_team,settings
                  FROM production.route_step_phase_templates
                 WHERE organization_id=:org AND route_step_id=:step ORDER BY sequence_no,code
            """), {"org": org, "step": step["id"]}).mappings().all()
            phase_values = []
            for phase in phases:
                labor = self.conn.execute(text("""
                    SELECT s.code AS skill_code,r.min_people,r.max_people,r.work_minutes,
                           r.productivity_curve,r.is_mandatory
                    FROM production.route_phase_labor_requirement_templates r
                    JOIN capacity.skills s ON s.organization_id=r.organization_id AND s.id=r.skill_id
                    WHERE r.organization_id=:org AND r.route_step_phase_template_id=:phase
                    ORDER BY s.code,r.min_people,r.max_people,r.work_minutes,
                             r.productivity_curve::text,r.is_mandatory
                """), {"org": org, "phase": phase["id"]}).mappings().all()
                physical = self.conn.execute(text("""
                    SELECT rt.code AS resource_type_code,rg.code AS resource_group_code,wc.code AS work_center_code,
                           r.quantity,r.capacity_units,r.usage_mode,r.is_mandatory
                    FROM production.route_phase_physical_requirement_templates r
                    LEFT JOIN capacity.physical_resource_types rt ON rt.organization_id=r.organization_id AND rt.id=r.physical_resource_type_id
                    LEFT JOIN capacity.physical_resource_groups rg ON rg.organization_id=r.organization_id AND rg.id=r.physical_resource_group_id
                    LEFT JOIN capacity.work_centers wc ON wc.organization_id=r.organization_id AND wc.id=r.work_center_id
                    WHERE r.organization_id=:org AND r.route_step_phase_template_id=:phase
                    ORDER BY rt.code NULLS LAST,rg.code NULLS LAST,wc.code NULLS LAST,
                             r.usage_mode,r.quantity,r.capacity_units,r.is_mandatory
                """), {"org": org, "phase": phase["id"]}).mappings().all()
                gates = self.conn.execute(text("""
                    SELECT timing,gate_type,target_kind,parameters,is_mandatory
                    FROM production.route_phase_gate_templates
                    WHERE organization_id=:org AND route_step_phase_template_id=:phase
                    ORDER BY timing,gate_type,target_kind,parameters::text
                """), {"org": org, "phase": phase["id"]}).mappings().all()
                phase_values.append({key: value for key, value in dict(phase).items() if key != "id"} |
                    {"labor_requirements": [dict(value) for value in labor],
                     "physical_requirements": [dict(value) for value in physical],
                     "gates": [dict(value) for value in gates]})
            step_values.append({"code": step["code"], "name": step["name"],
                "sequence_hint": step["sequence_hint"],
                "operation_definition_code": step["operation_definition_code"],
                "settings": step["settings"], "phase_templates": phase_values})
        precedences = self.conn.execute(text("""
            SELECT predecessor_step_id,successor_step_id,precedence_type,lag_minutes
              FROM production.route_step_precedences
             WHERE organization_id=:org AND route_version_id=:route
        """), {"org": org, "route": route["id"]}).mappings().all()
        precedence_values = sorted(({
            "predecessor_code": step_codes[value["predecessor_step_id"]],
            "successor_code": step_codes[value["successor_step_id"]],
            "precedence_type": value["precedence_type"], "lag_minutes": value["lag_minutes"],
        } for value in precedences), key=lambda value: (
            value["predecessor_code"], value["successor_code"],
            value["precedence_type"], value["lag_minutes"]))
        return {"code": route["code"], "name": route["name"], "version_no": route["version_no"],
                "steps": step_values, "precedences": precedence_values}

    def _snapshot_operations(self, org: UUID, project: UUID, lot: UUID | None) -> list[dict[str, Any]]:
        operations = self.conn.execute(text("""
            SELECT ro.id,ro.code,ro.name,ro.operation_kind,ro.status,ro.earliest_start_at,ro.settings,
                   od.code AS definition_code,rs.code AS route_step_code
            FROM production.required_operations ro
            JOIN production.operation_definitions od ON od.organization_id=ro.organization_id AND od.id=ro.operation_definition_id
            LEFT JOIN production.route_steps rs ON rs.organization_id=ro.organization_id AND rs.id=ro.route_step_id
            WHERE ro.organization_id=:org AND ro.project_id=:project
              AND ro.project_lot_id IS NOT DISTINCT FROM :lot AND ro.status<>'archived' ORDER BY ro.code
        """), {"org": org, "project": project, "lot": lot}).mappings().all()
        values: list[dict[str, Any]] = []
        for op in operations:
            phases = self.conn.execute(text("""
                SELECT * FROM production.required_operation_phases
                 WHERE organization_id=:org AND required_operation_id=:operation AND status<>'archived'
                 ORDER BY sequence_no,code
            """), {"org": org, "operation": op["id"]}).mappings().all()
            phase_values = []
            for ph in phases:
                labor = self.conn.execute(text("""
                    SELECT s.code,r.min_people,r.max_people,r.work_minutes,r.productivity_curve,r.is_mandatory
                    FROM production.operation_labor_requirements r JOIN capacity.skills s
                      ON s.organization_id=r.organization_id AND s.id=r.skill_id
                    WHERE r.organization_id=:org AND r.required_operation_phase_id=:phase
                    ORDER BY s.code,r.min_people,r.max_people,r.work_minutes,
                             r.productivity_curve::text,r.is_mandatory
                """), {"org": org, "phase": ph["id"]}).mappings().all()
                physical = self.conn.execute(text("""
                    SELECT rt.code AS resource_type_code,rg.code AS resource_group_code,wc.code AS work_center_code,
                           r.quantity,r.capacity_units,r.is_mandatory,r.usage_mode
                    FROM production.operation_physical_requirements r
                    LEFT JOIN capacity.physical_resource_types rt ON rt.organization_id=r.organization_id AND rt.id=r.physical_resource_type_id
                    LEFT JOIN capacity.physical_resource_groups rg ON rg.organization_id=r.organization_id AND rg.id=r.physical_resource_group_id
                    LEFT JOIN capacity.work_centers wc ON wc.organization_id=r.organization_id AND wc.id=r.work_center_id
                    WHERE r.organization_id=:org AND r.required_operation_phase_id=:phase
                    ORDER BY rt.code NULLS LAST,rg.code NULLS LAST,wc.code NULLS LAST,
                             r.usage_mode,r.quantity,r.capacity_units,r.is_mandatory
                """), {"org": org, "phase": ph["id"]}).mappings().all()
                gates = self._snapshot_gates(org, op["id"], ph["id"])
                phase_values.append({"sequence_no": ph["sequence_no"], "code": ph["code"], "name": ph["name"],
                    "estimate_kind": ph["estimate_kind"], "original_estimate_minutes": ph["original_estimate_minutes"],
                    **({"required_people":ph["required_people"]} if ph["required_people"] else {}),
                    "split_policy": ph["split_policy"], "status": ph["status"], "earliest_start_at": ph["earliest_start_at"],
                    "labor_requirements": [dict(x) for x in labor], "physical_requirements": [dict(x) for x in physical],
                    "gates": gates})
            predecessors = self.conn.execute(text("""
                SELECT pred.code AS predecessor_code,pl.code AS predecessor_lot_code,
                       p.precedence_type,p.lag_minutes,p.source
                FROM production.operation_precedences p JOIN production.required_operations pred
                  ON pred.organization_id=p.organization_id AND pred.id=p.predecessor_operation_id
                LEFT JOIN core.project_lots pl ON pl.organization_id=pred.organization_id AND pl.id=pred.project_lot_id
                WHERE p.organization_id=:org AND p.successor_operation_id=:operation AND p.active
                ORDER BY pl.code NULLS FIRST,pred.code,p.precedence_type,p.lag_minutes,p.source
            """), {"org": org, "operation": op["id"]}).mappings().all()
            values.append({"code": op["code"], "name": op["name"], "operation_kind": op["operation_kind"],
                "status": op["status"], "earliest_start_at": op["earliest_start_at"],
                "operation_definition_code": op["definition_code"], "route_step_code": op["route_step_code"],
                "settings": op["settings"], "predecessors": [dict(x) for x in predecessors],
                "gates": self._snapshot_gates(org, op["id"], None), "phases": phase_values})
        return values

    def _snapshot_gates(self, org: UUID, operation: UUID, phase: UUID | None) -> list[dict[str, Any]]:
        gates = self.conn.execute(text("""
            SELECT g.timing,g.gate_type,g.available_at,g.config,m.code AS material_code,
                   ml.code AS material_lot_code,d.code AS drawing_code,dl.code AS drawing_lot_code,
                   l.code AS hardware_lot_code,md.code AS milestone_code
            FROM production.operation_gates g
            LEFT JOIN production.material_requirements m ON m.organization_id=g.organization_id AND m.id=g.material_requirement_id
            LEFT JOIN core.project_lots ml ON ml.organization_id=m.organization_id AND ml.id=m.project_lot_id
            LEFT JOIN production.drawing_packages d ON d.organization_id=g.organization_id AND d.id=g.drawing_package_id
            LEFT JOIN core.project_lots dl ON dl.organization_id=d.organization_id AND dl.id=d.project_lot_id
            LEFT JOIN core.project_lots l ON l.organization_id=g.organization_id AND l.id=g.hardware_project_lot_id
            LEFT JOIN core.milestone_definitions md ON md.organization_id=g.organization_id AND md.id=g.milestone_definition_id
            WHERE g.organization_id=:org AND g.required_operation_id=:operation
              AND g.required_operation_phase_id IS NOT DISTINCT FROM :phase
            ORDER BY g.timing,g.gate_type,COALESCE(ml.code,dl.code,l.code,''),
                     COALESCE(m.code,d.code,l.code,md.code,g.available_at::text),g.config::text
        """), {"org": org, "operation": operation, "phase": phase}).mappings().all()
        return [dict(value) for value in gates]

    def _advance_state(self, org: UUID, plant: UUID, actor: UUID, reason: str,
                       event_type: str, entity_type: str, entity_id: UUID,
                       payload: dict[str, Any], source: str, reference: str) -> tuple[UUID, int]:
        head = self.conn.execute(text("SELECT current_revision_no FROM planning.planning_state_heads WHERE organization_id=:org AND plant_id=:plant FOR UPDATE"), {"org": org, "plant": plant}).mappings().one_or_none()
        if head is None:
            raise EntityNotFound("planning state head not found in organization")
        state_id, event_id, number, now = uuid4(), uuid4(), head["current_revision_no"] + 1, datetime.now(timezone.utc)
        self.conn.execute(text("""
            INSERT INTO planning.planning_state_revisions
              (id,organization_id,plant_id,revision_no,reason,transaction_key,change_summary,created_by)
            VALUES (:id,:org,:plant,:number,:reason,:key,CAST(:summary AS jsonb),:actor)
        """), {"id": state_id, "org": org, "plant": plant, "number": number, "reason": reason,
                "key": uuid4(), "summary": _json({"event_type": event_type, "entity_id": str(entity_id)}), "actor": actor})
        self.conn.execute(text("""
            INSERT INTO planning.effective_events
              (id,organization_id,plant_id,event_type_code,payload_schema_version,occurred_at,effective_at,
               entity_type,entity_id,payload,cause,planning_state_revision_id,source_system,external_reference,created_by)
            VALUES (:id,:org,:plant,:event_type,1,:now,:now,:entity_type,:entity_id,CAST(:payload AS jsonb),
                    :reason,:state,:source,:reference,:actor)
        """), {"id": event_id, "org": org, "plant": plant, "event_type": event_type, "now": now,
                "entity_type": entity_type, "entity_id": entity_id, "payload": _json(payload),
                "reason": reason, "state": state_id, "source": source, "reference": reference, "actor": actor})
        self.conn.execute(text("UPDATE planning.planning_state_heads SET current_revision_id=:state,current_revision_no=:number,row_version=row_version+1,updated_at=:now,updated_by=:actor WHERE organization_id=:org AND plant_id=:plant"), {"state": state_id, "number": number, "now": now, "actor": actor, "org": org, "plant": plant})
        return state_id, number

    def _lock_plant(self, org: UUID, plant: UUID) -> Any:
        row = self.conn.execute(text("SELECT id,current_product_definition_revision_id FROM core.plants WHERE organization_id=:org AND id=:plant FOR UPDATE"), {"org": org, "plant": plant}).mappings().one_or_none()
        if row is None:
            raise EntityNotFound("plant not found in organization")
        return row

    def _project(self, org: UUID, project: UUID, *, lock_plant: bool) -> Any:
        row = self.conn.execute(text("SELECT id,plant_id FROM core.projects WHERE organization_id=:org AND id=:project"), {"org": org, "project": project}).mappings().one_or_none()
        if row is None:
            raise EntityNotFound("project not found in organization")
        if lock_plant:
            self._lock_plant(org, row["plant_id"])
        return row

    def _require_actor(self, org: UUID, actor: UUID) -> None:
        self._require_owned("core.user_profiles", org, actor, "actor")

    def _require_owned(self, table: str, org: UUID, entity_id: UUID, label: str) -> None:
        allowed = {"core.customers", "core.project_priorities", "core.user_profiles", "capacity.skills",
                   "capacity.physical_resource_types", "capacity.physical_resource_groups", "capacity.work_centers",
                   "production.operation_definitions", "production.material_requirements", "production.drawing_packages",
                   "core.project_lots", "core.milestone_definitions"}
        if table not in allowed:
            raise RuntimeError("unsafe table")
        if not self.conn.scalar(text(f"SELECT EXISTS(SELECT 1 FROM {table} WHERE organization_id=:org AND id=:id)"), {"org": org, "id": entity_id}):
            raise EntityNotFound(f"{label} not found in organization")

    def _require_lot_project(self, org: UUID, lot: UUID, project: UUID) -> None:
        if not self.conn.scalar(text("SELECT EXISTS(SELECT 1 FROM core.project_lots WHERE organization_id=:org AND id=:lot AND project_id=:project)"), {"org": org, "lot": lot, "project": project}):
            raise EntityNotFound("project lot not found in project and organization")

    def _validate_gate_target(self, org: UUID, gate: Any) -> None:
        for table, value, label in (("production.material_requirements", gate.material_requirement_id, "material requirement"),
                                    ("production.drawing_packages", gate.drawing_package_id, "drawing package"),
                                    ("core.project_lots", gate.hardware_project_lot_id, "hardware lot"),
                                    ("core.milestone_definitions", gate.milestone_definition_id, "milestone definition")):
            if value is not None:
                self._require_owned(table, org, value, label)

    def _event(self, org: UUID, source: str, reference: str) -> Any:
        return self.conn.execute(text("""
            SELECT e.entity_type,e.entity_id,e.payload,e.planning_state_revision_id,r.revision_no AS state_no
            FROM planning.effective_events e LEFT JOIN planning.planning_state_revisions r
              ON r.organization_id=e.organization_id AND r.id=e.planning_state_revision_id
            WHERE e.organization_id=:org AND e.source_system=:source AND e.external_reference=:reference
        """), {"org": org, "source": source, "reference": reference}).mappings().one_or_none()

    def _mutation_replay(self, org: UUID, source: str, reference: str, entity_type: str,
                         expected_payload: dict[str, Any]) -> DefinitionMutationResult | None:
        event = self._event(org, source, reference)
        if event is None:
            return None
        if event["entity_type"] != entity_type:
            raise ProductDefinitionConflict("idempotency key was used for another command target")
        if any(event["payload"].get(key,0 if key=="required_people" else None) != value for key, value in expected_payload.items()):
            raise ProductDefinitionConflict("idempotency key was used with different command data")
        return DefinitionMutationResult(event["entity_id"], event["planning_state_revision_id"], event["state_no"], True)


class PostgresProductDefinitionUnitOfWorkFactory:
    def __init__(self, engine: Engine, *, failpoint: str | None = None) -> None:
        self._engine = engine
        self._failpoint = failpoint

    def __call__(self) -> PostgresProductDefinitionUnitOfWork:
        return PostgresProductDefinitionUnitOfWork(self._engine, failpoint=self._failpoint)


def canonical_json(value: Any) -> str:
    return json.dumps(_canonical(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _canonical(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _canonical(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if isinstance(value, Decimal):
        normalized = format(value.normalize(), "f")
        return "0" if normalized == "-0" else normalized
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, UUID):
        raise InvalidProductDefinition("non-semantic UUID leaked into canonical snapshot")
    return value


def _has_cycle(edges: list[tuple[UUID, UUID]]) -> bool:
    graph: dict[UUID, set[UUID]] = {}
    for start, end in edges:
        graph.setdefault(start, set()).add(end)
        graph.setdefault(end, set())
    visiting: set[UUID] = set()
    visited: set[UUID] = set()

    def visit(node: UUID) -> bool:
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        if any(visit(child) for child in graph[node]):
            return True
        visiting.remove(node)
        visited.add(node)
        return False

    return any(visit(node) for node in graph)


def _external(name: str, command_id: UUID) -> str:
    return f"{name}:{command_id}"


def _uuid(value: UUID | None) -> str | None:
    return str(value) if value is not None else None


def _json(value: Any) -> str:
    return canonical_json(value)
