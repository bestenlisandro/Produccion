from __future__ import annotations

from datetime import date
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

    def scenario(self, org: UUID, scenario_id: UUID,
                 plant_id: UUID | None = None) -> dict[str, Any]:
        with self.engine.connect() as conn:
            row = conn.execute(text("""
                SELECT s.id,s.status,s.base_plan_version_id,s.base_state_revision_id,
                       s.base_product_definition_revision_id,
                       (s.status='stale'
                        OR s.base_state_revision_id<>h.current_revision_id
                        OR s.base_product_definition_revision_id<>p.current_product_definition_revision_id
                        OR (s.base_plan_version_id IS NOT NULL
                            AND s.base_plan_version_id<>p.current_plan_version_id)) AS stale,
                       s.status='rejected' AS rejected,
                       s.status='confirmed' AS promoted,
                       pv.id AS promoted_plan_version_id,s.row_version,
                       p.promotion_lock_version,
                       COALESCE((sol.comparison->>'changed_operations')::int,0) AS changed_operations,
                       COALESCE(jsonb_array_length(COALESCE(sol.comparison->'frontier_project_ids','[]'::jsonb)),0) AS affected_projects,
                       COALESCE((sol.comparison->>'customer_date_alerts')::int,0) AS customer_date_alerts,
                       COALESCE((sol.comparison->>'customer_date_alerts')::int,0)>0 AS communication_recommended,
                       COALESCE((SELECT jsonb_agg(jsonb_build_object(
                           'kind',i.impact_kind,'delta_minutes',i.delta_minutes,
                           'project_id',i.project_id,'operation_id',i.required_operation_id,
                           'old',i.old_value,'new',i.new_value,'reason',i.reason)
                           ORDER BY i.created_at,i.id)
                         FROM planning.impact_items i
                        WHERE i.organization_id=s.organization_id
                          AND i.schedule_solution_id=sol.id),'[]'::jsonb) AS impacts
                  FROM planning.scenarios s
                  JOIN core.plants p
                    ON p.organization_id=s.organization_id AND p.id=s.plant_id
                  JOIN planning.planning_state_heads h
                    ON h.organization_id=s.organization_id AND h.plant_id=s.plant_id
                  LEFT JOIN planning.plan_versions pv
                    ON pv.organization_id=s.organization_id AND pv.source_scenario_id=s.id
                  LEFT JOIN LATERAL (
                    SELECT x.id,x.comparison FROM planning.schedule_solutions x
                     WHERE x.organization_id=s.organization_id AND x.scenario_id=s.id
                     ORDER BY x.run_no DESC LIMIT 1
                  ) sol ON true
                 WHERE s.organization_id=:org AND s.id=:scenario
                   AND (:plant IS NULL OR s.plant_id=:plant)
            """), {"org": org, "scenario": scenario_id,
                     "plant": plant_id}).mappings().one_or_none()
        if row is None:
            raise EntityNotFound("scenario not found")
        return dict(row)

    def replan_context(self, org: UUID, plant: UUID) -> dict[str, Any]:
        with self.engine.connect() as conn:
            row = conn.execute(text("""
                SELECT p.current_plan_version_id AS plan_id,
                       p.current_product_definition_revision_id AS definition_id,
                       h.current_revision_id AS state_id
                  FROM core.plants p
                  JOIN planning.planning_state_heads h
                    ON h.organization_id=p.organization_id AND h.plant_id=p.id
                 WHERE p.organization_id=:org AND p.id=:plant
            """), {"org": org, "plant": plant}).mappings().one_or_none()
        if row is None or any(row[key] is None for key in ("plan_id", "definition_id", "state_id")):
            raise EntityNotFound("current planning context not found")
        return dict(row)

    def daily_board(self, org: UUID, plant: UUID, day: date) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT ro.id AS operation_id,p.id AS project_id,p.code AS project_code,
                       p.name AS project_name,l.code AS lot_code,l.name AS lot_name,
                       ro.code AS operation_code,ro.name AS operation_name,
                       phase.phase_name,opr.planned_start_at AS planned_start,
                       opr.planned_end_at AS planned_finish,
                       COALESCE(hum.people,'[]'::jsonb) AS people,
                       res.work_center,res.physical_resource,pri.name AS priority,
                       pri.rank AS priority_rank,
                       CASE WHEN exe.status='completed' OR opr.result_status='completed' THEN 'FINALIZADO'
                            WHEN exe.status IN ('running','paused') THEN 'EN_CURSO'
                            WHEN opr.result_status='blocked' THEN 'BLOQUEADO'
                            WHEN opr.planned_end_at < now() THEN 'DEMORADO'
                            WHEN opr.planned_start_at <= now() THEN 'LISTO'
                            ELSE 'PENDIENTE' END AS operational_status,
                       CASE WHEN rem.updated_total_labor_minutes>0
                            THEN LEAST(100,ROUND(100.0*rem.executed_labor_minutes_at_cutoff/rem.updated_total_labor_minutes)::int)
                            ELSE NULL END AS progress_percent,
                       COALESCE(rem.executed_labor_minutes_at_cutoff,actual.executed_minutes,0)::int AS executed_minutes,
                       rem.remaining_labor_minutes::int AS remaining_minutes,
                       COALESCE(opr.explanation->'blockers'->>0,phase.blocker_code) AS blocker_code
                  FROM core.plants plant
                  JOIN planning.plan_versions pv
                    ON pv.organization_id=plant.organization_id AND pv.id=plant.current_plan_version_id
                  JOIN planning.operation_plan_results opr
                    ON opr.organization_id=pv.organization_id AND opr.schedule_solution_id=pv.schedule_solution_id
                  JOIN production.required_operations ro
                    ON ro.organization_id=opr.organization_id AND ro.id=opr.required_operation_id
                  JOIN core.projects p ON p.organization_id=ro.organization_id AND p.id=ro.project_id
                  JOIN core.project_priorities pri ON pri.organization_id=p.organization_id AND pri.id=p.priority_id
                  LEFT JOIN core.project_lots l ON l.organization_id=ro.organization_id AND l.id=ro.project_lot_id
                  LEFT JOIN LATERAL (
                    SELECT ph.name AS phase_name,ph.id AS phase_id,
                           ppr.explanation->'why_not_earlier'->>0 AS blocker_code
                      FROM planning.phase_plan_results ppr
                      JOIN production.required_operation_phases ph
                        ON ph.organization_id=ppr.organization_id AND ph.id=ppr.required_operation_phase_id
                     WHERE ppr.organization_id=opr.organization_id
                       AND ppr.operation_plan_result_id=opr.id
                     ORDER BY ph.sequence_no LIMIT 1
                  ) phase ON true
                  LEFT JOIN LATERAL (
                    SELECT jsonb_agg(DISTINCT jsonb_build_object('id',e.id,'name',e.display_name)) AS people
                      FROM planning.phase_plan_results ppr
                      JOIN planning.planned_phase_assignments pa ON pa.organization_id=ppr.organization_id AND pa.phase_plan_result_id=ppr.id
                      JOIN planning.assignment_segments seg ON seg.organization_id=pa.organization_id AND seg.planned_phase_assignment_id=pa.id
                      JOIN planning.human_segment_assignments ha ON ha.organization_id=seg.organization_id AND ha.assignment_segment_id=seg.id
                      JOIN capacity.employees e ON e.organization_id=ha.organization_id AND e.id=ha.employee_id
                     WHERE ppr.organization_id=opr.organization_id AND ppr.operation_plan_result_id=opr.id
                  ) hum ON true
                  LEFT JOIN LATERAL (
                    SELECT string_agg(DISTINCT wc.name,', ') AS work_center,
                           string_agg(DISTINCT pr.name,', ') AS physical_resource
                      FROM planning.phase_plan_results ppr
                      JOIN planning.planned_phase_assignments pa ON pa.organization_id=ppr.organization_id AND pa.phase_plan_result_id=ppr.id
                      JOIN planning.assignment_segments seg ON seg.organization_id=pa.organization_id AND seg.planned_phase_assignment_id=pa.id
                      JOIN planning.physical_resource_reservations rr ON rr.organization_id=seg.organization_id AND rr.assignment_segment_id=seg.id
                      JOIN capacity.physical_resources pr ON pr.organization_id=rr.organization_id AND pr.id=rr.physical_resource_id
                      JOIN capacity.work_centers wc ON wc.organization_id=pr.organization_id AND wc.id=pr.work_center_id
                     WHERE ppr.organization_id=opr.organization_id AND ppr.operation_plan_result_id=opr.id
                  ) res ON true
                  LEFT JOIN LATERAL (SELECT oe.id,oe.status FROM execution.operation_executions oe
                    WHERE oe.organization_id=ro.organization_id AND oe.required_operation_id=ro.id
                    ORDER BY (oe.status IN ('running','paused')) DESC,oe.created_at DESC LIMIT 1) exe ON true
                  LEFT JOIN execution.remaining_estimate_revisions rem
                    ON rem.organization_id=ro.organization_id AND rem.operation_execution_id=exe.id AND rem.superseded_at IS NULL
                  LEFT JOIN LATERAL (SELECT COALESCE(sum(es.work_minutes),0)::int AS executed_minutes
                    FROM execution.execution_segments es WHERE es.organization_id=ro.organization_id
                    AND es.operation_execution_id=exe.id AND es.segment_kind='work') actual ON true
                 WHERE plant.organization_id=:org AND plant.id=:plant
                   AND opr.planned_start_at < CAST(:day AS date)+INTERVAL '1 day'
                   AND opr.planned_end_at >= CAST(:day AS date)
                 ORDER BY opr.planned_start_at,pri.rank,ro.id
            """), {"org": org, "plant": plant, "day": day}).mappings().all()
        return [dict(row) for row in rows]

    def operation_detail(self, org: UUID, plant: UUID | None, operation_id: UUID) -> dict[str, Any]:
        operation = self.operation(org, operation_id, plant)
        with self.engine.connect() as conn:
            planned_day = conn.scalar(text("""
                SELECT opr.planned_start_at::date FROM core.projects p
                JOIN core.plants plant ON plant.organization_id=p.organization_id AND plant.id=p.plant_id
                JOIN planning.plan_versions pv ON pv.organization_id=plant.organization_id AND pv.id=plant.current_plan_version_id
                JOIN planning.operation_plan_results opr ON opr.organization_id=pv.organization_id AND opr.schedule_solution_id=pv.schedule_solution_id
                WHERE opr.organization_id=:org AND opr.required_operation_id=:operation
            """), {"org": org, "operation": operation_id})
        if planned_day is None:
            raise EntityNotFound("operation is not present in current plan")
        rows = self.daily_board(org, operation["plant_id"], planned_day)
        item = next((row for row in rows if row["operation_id"] == operation_id), None)
        if item is None:
            raise EntityNotFound("operation is not present in current plan")
        with self.engine.connect() as conn:
            extra = conn.execute(text("""
                SELECT ph.id AS phase_id,ph.original_estimate_minutes,
                       EXISTS(SELECT 1 FROM execution.operation_executions oe
                         JOIN execution.remaining_estimate_revisions r ON r.organization_id=oe.organization_id AND r.operation_execution_id=oe.id AND r.superseded_at IS NULL
                         JOIN core.plants p ON p.organization_id=oe.organization_id
                         JOIN planning.plan_versions pv ON pv.organization_id=p.organization_id AND pv.id=p.current_plan_version_id
                        WHERE oe.organization_id=ro.organization_id AND oe.required_operation_id=ro.id
                          AND p.id=:plant AND r.planning_state_revision_id<>pv.planning_state_revision_id) AS plan_requires_reconciliation,
                       (SELECT nxt.name FROM production.operation_precedences op
                         JOIN production.required_operations nxt ON nxt.organization_id=op.organization_id AND nxt.id=op.successor_operation_id
                        WHERE op.organization_id=ro.organization_id AND op.predecessor_operation_id=ro.id AND op.active
                        ORDER BY nxt.code LIMIT 1) AS next_operation_name
                  FROM production.required_operations ro
                  LEFT JOIN LATERAL (SELECT x.id,x.original_estimate_minutes FROM production.required_operation_phases x
                    WHERE x.organization_id=ro.organization_id AND x.required_operation_id=ro.id ORDER BY x.sequence_no LIMIT 1) ph ON true
                 WHERE ro.organization_id=:org AND ro.id=:operation
            """), {"org": org, "operation": operation_id, "plant": operation["plant_id"]}).mappings().one()
        return item | dict(extra)
