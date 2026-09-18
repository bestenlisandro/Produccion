from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import Engine, text

from production_besten.domain.errors import EntityNotFound


class PostgresApiQueries:
    """Tenant-safe read adapter used by the HTTP composition layer."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def ready(self) -> bool:
        with self.engine.connect() as conn:
            return conn.scalar(text("SELECT 1")) == 1

    def project(self, org: UUID, project_id: UUID, plant_id: UUID | None = None) -> dict[str, Any]:
        with self.engine.connect() as conn:
            row = conn.execute(text("""
                SELECT id,plant_id,customer_id,priority_id,code,name,description,status,
                       committed_date,desired_start_at
                FROM core.projects WHERE organization_id=:org AND id=:project
                  AND (:plant IS NULL OR plant_id=:plant)
            """), {"org": org, "project": project_id, "plant": plant_id}).mappings().one_or_none()
        if row is None:
            raise EntityNotFound("project not found")
        return dict(row)

    def batches(self, org: UUID, project_id: UUID, plant_id: UUID | None = None) -> list[dict[str, Any]]:
        self.project(org, project_id, plant_id)
        with self.engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT id,project_id,code,name,description,sequence_no,quantity,unit,status,
                       hardware_status,hardware_available_at
                FROM core.project_lots WHERE organization_id=:org AND project_id=:project
                ORDER BY sequence_no,code
            """), {"org": org, "project": project_id}).mappings().all()
        return [dict(row) for row in rows]

    def batch(self, org: UUID, batch_id: UUID, plant_id: UUID | None = None) -> dict[str, Any]:
        with self.engine.connect() as conn:
            row = conn.execute(text("""
                SELECT l.id,l.project_id,p.plant_id FROM core.project_lots l
                JOIN core.projects p ON p.organization_id=l.organization_id AND p.id=l.project_id
                WHERE l.organization_id=:org AND l.id=:batch
                  AND (:plant IS NULL OR p.plant_id=:plant)
            """), {"org": org, "batch": batch_id, "plant": plant_id}).mappings().one_or_none()
        if row is None:
            raise EntityNotFound("batch not found")
        return dict(row)

    def operation(self, org: UUID, operation_id: UUID, plant_id: UUID | None = None) -> dict[str, Any]:
        with self.engine.connect() as conn:
            row = conn.execute(text("""
                SELECT ro.id,ro.project_id,ro.project_lot_id,p.plant_id
                FROM production.required_operations ro
                JOIN core.projects p ON p.organization_id=ro.organization_id AND p.id=ro.project_id
                WHERE ro.organization_id=:org AND ro.id=:operation
                  AND (:plant IS NULL OR p.plant_id=:plant)
            """), {"org": org, "operation": operation_id, "plant": plant_id}).mappings().one_or_none()
        if row is None:
            raise EntityNotFound("operation not found")
        return dict(row)

    def execution_for_operation(self, org: UUID, operation_id: UUID, plant_id: UUID | None,
                                *, require_active: bool) -> UUID:
        self.operation(org, operation_id, plant_id)
        condition = "AND oe.status IN ('running','paused')" if require_active else ""
        with self.engine.connect() as conn:
            value = conn.scalar(text(f"""
                SELECT oe.id FROM execution.operation_executions oe
                WHERE oe.organization_id=:org AND oe.required_operation_id=:operation {condition}
                ORDER BY (oe.status IN ('running','paused')) DESC,oe.started_at DESC,oe.created_at DESC LIMIT 1
            """), {"org": org, "operation": operation_id})
        if value is None:
            raise EntityNotFound("operation execution not found")
        return value

    def execution(self, org: UUID, execution_id: UUID, plant_id: UUID | None = None) -> dict[str, Any]:
        with self.engine.connect() as conn:
            row = conn.execute(text("""
                SELECT oe.id,oe.required_operation_id,p.plant_id
                FROM execution.operation_executions oe
                JOIN production.required_operations ro
                  ON ro.organization_id=oe.organization_id AND ro.id=oe.required_operation_id
                JOIN core.projects p ON p.organization_id=ro.organization_id AND p.id=ro.project_id
                WHERE oe.organization_id=:org AND oe.id=:execution
                  AND (:plant IS NULL OR p.plant_id=:plant)
            """), {"org": org, "execution": execution_id, "plant": plant_id}).mappings().one_or_none()
        if row is None:
            raise EntityNotFound("execution not found")
        return dict(row)

    def remaining_context(self, org: UUID, operation_id: UUID, plant_id: UUID | None) -> dict[str, Any]:
        execution_id = self.execution_for_operation(org, operation_id, plant_id, require_active=True)
        with self.engine.connect() as conn:
            row = conn.execute(text("""
                SELECT oe.id AS execution_id,r.revision_no,
                       COALESCE(
                         (SELECT (e.payload->>'phase_id')::uuid FROM planning.effective_events e
                           WHERE e.organization_id=oe.organization_id
                             AND e.payload->>'operation_execution_id'=oe.id::text
                             AND e.payload ? 'phase_id'
                           ORDER BY e.effective_at DESC,e.created_at DESC LIMIT 1),
                         (oe.original_estimate_snapshot->'phases'->0->>'phase_id')::uuid
                       ) AS phase_id
                FROM execution.operation_executions oe
                JOIN execution.remaining_estimate_revisions r
                  ON r.organization_id=oe.organization_id AND r.operation_execution_id=oe.id
                 AND r.superseded_at IS NULL
                WHERE oe.organization_id=:org AND oe.id=:execution
            """), {"org": org, "execution": execution_id}).mappings().one()
            labor = conn.execute(text("""
                SELECT skill_id,min_people,max_people FROM production.operation_labor_requirements
                WHERE organization_id=:org AND required_operation_phase_id=:phase AND is_mandatory
                ORDER BY id
            """), {"org": org, "phase": row["phase_id"]}).mappings().all()
            physical = conn.execute(text("""
                SELECT id,usage_mode FROM production.operation_physical_requirements
                WHERE organization_id=:org AND required_operation_phase_id=:phase AND is_mandatory
                ORDER BY id
            """), {"org": org, "phase": row["phase_id"]}).mappings().all()
        return dict(row) | {"labor_requirements": [dict(x) for x in labor],
                            "physical_requirements": [dict(x) for x in physical]}

    def revision_created_at(self, org: UUID, revision_id: UUID) -> Any:
        with self.engine.connect() as conn:
            value = conn.scalar(text("SELECT created_at FROM production.product_definition_revisions WHERE organization_id=:org AND id=:id"), {"org": org, "id": revision_id})
        if value is None:
            raise EntityNotFound("product definition revision not found")
        return value
