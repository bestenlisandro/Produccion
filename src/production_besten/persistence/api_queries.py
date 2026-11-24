from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Callable
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import Engine, text

from production_besten.domain.errors import EntityNotFound, InvalidSchedulingInput
from production_besten.domain.scenario_expiry import PlannedOperationTiming, scenario_expired
from production_besten.persistence.scenario_expiry import solution_timings


class PostgresApiQueries:
    """Tenant-safe read adapter used by the HTTP composition layer."""

    def __init__(self, engine: Engine, *, now: Callable[[], datetime] | None = None) -> None:
        self.engine = engine
        self._now = now or (lambda: datetime.now(timezone.utc))

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
            required_people = conn.scalar(text("SELECT required_people FROM production.required_operation_phases WHERE organization_id=:org AND id=:phase"),
                                          {"org": org, "phase": row["phase_id"]})
        return dict(row) | {"required_people": required_people, "labor_requirements": [dict(x) for x in labor],
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
                       CASE WHEN exe.status='completed' THEN 100
                            WHEN COALESCE(actual.executed_minutes,0)+rem.remaining_labor_minutes>0
                            THEN LEAST(100,ROUND(100.0*COALESCE(actual.executed_minutes,0)/(COALESCE(actual.executed_minutes,0)+rem.remaining_labor_minutes))::int)
                            ELSE NULL END AS progress_percent,
                       COALESCE(actual.executed_minutes,rem.executed_labor_minutes_at_cutoff,0)::int AS executed_minutes,
                       CASE WHEN exe.status='completed' THEN 0 ELSE rem.remaining_labor_minutes::int END AS remaining_minutes,
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
                    AND es.operation_execution_id=exe.id AND es.segment_kind='work'
                    AND NOT EXISTS(SELECT 1 FROM execution.execution_segments n
                      WHERE n.organization_id=es.organization_id AND n.supersedes_id=es.id)) actual ON true
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
        rows = self.daily_board(org, operation["plant_id"], planned_day) if planned_day else []
        item = next((row for row in rows if row["operation_id"] == operation_id), None)
        if item is None:
            from production_besten.persistence.operation_execution_queries import operation_summary
            with self.engine.connect() as conn:
                item = operation_summary(conn, org, operation['plant_id'], operation_id)
        with self.engine.connect() as conn:
            extra = conn.execute(text("""
                SELECT ph.id AS phase_id,ph.original_estimate_minutes,
                       (EXISTS(SELECT 1 FROM planning.planning_state_revisions sh
                         JOIN core.plants p ON p.organization_id=sh.organization_id AND p.id=sh.plant_id
                         JOIN planning.plan_versions pv ON pv.organization_id=p.organization_id AND pv.id=p.current_plan_version_id
                         JOIN planning.planning_state_revisions base ON base.organization_id=pv.organization_id AND base.id=pv.planning_state_revision_id
                         WHERE sh.organization_id=ro.organization_id AND sh.plant_id=:plant
                           AND sh.revision_no>base.revision_no AND sh.change_summary @> jsonb_build_object('current_affected',true))
                       OR EXISTS(SELECT 1 FROM execution.operation_executions oe
                         JOIN execution.remaining_estimate_revisions r ON r.organization_id=oe.organization_id AND r.operation_execution_id=oe.id AND r.superseded_at IS NULL
                         JOIN core.plants p ON p.organization_id=oe.organization_id
                         JOIN planning.plan_versions pv ON pv.organization_id=p.organization_id AND pv.id=p.current_plan_version_id
                         JOIN planning.planning_state_revisions remaining_state ON remaining_state.organization_id=r.organization_id AND remaining_state.id=r.planning_state_revision_id
                         JOIN planning.planning_state_revisions published_state ON published_state.organization_id=pv.organization_id AND published_state.id=pv.planning_state_revision_id
                        WHERE oe.organization_id=ro.organization_id AND oe.required_operation_id=ro.id
                          AND p.id=:plant AND remaining_state.revision_no>published_state.revision_no)) AS plan_requires_reconciliation,
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

    def gantt(self, org: UUID, plant: UUID, range_from: datetime, range_to: datetime,
              group_by: str, scenario_id: UUID | None = None) -> dict[str, Any]:
        if range_from.tzinfo is None or range_to.tzinfo is None:
            raise InvalidSchedulingInput("gantt range must include a timezone")
        if range_to <= range_from:
            raise InvalidSchedulingInput("gantt range end must be after start")
        if range_to - range_from > timedelta(days=31):
            raise InvalidSchedulingInput("gantt range cannot exceed 31 days")
        if group_by not in {"center", "resource", "person", "project"}:
            raise InvalidSchedulingInput("unsupported gantt grouping")

        with self.engine.connect() as conn:
            metadata = conn.execute(text("""
                SELECT pv.id AS plan_version_id,pv.version_no AS plan_version_number,pv.source_scenario_id,
                       COALESCE(pv.planning_state_revision_id,h.current_revision_id) AS planning_state_revision_id,pv.schedule_solution_id,
                       p.timezone,p.base_calendar_id,p.promotion_lock_version,
                       c.timezone AS calendar_timezone,p.name AS plant_name,
                       (SELECT d.canonical_snapshot FROM planning.schedule_solutions sol
                         JOIN production.product_definition_revisions d ON d.organization_id=sol.organization_id
                          AND d.id=sol.input_product_definition_revision_id
                        WHERE sol.organization_id=p.organization_id AND sol.id=pv.schedule_solution_id) AS definition_snapshot
                  FROM core.plants p
                  LEFT JOIN planning.plan_versions pv
                    ON pv.organization_id=p.organization_id
                   AND pv.id=p.current_plan_version_id
                  JOIN planning.planning_state_heads h ON h.organization_id=p.organization_id AND h.plant_id=p.id
                  JOIN capacity.calendars c
                    ON c.organization_id=p.organization_id
                   AND c.id=p.base_calendar_id
                 WHERE p.organization_id=:org AND p.id=:plant
            """), {"org": org, "plant": plant}).mappings().one_or_none()
            if metadata is None:
                raise EntityNotFound("current plan not found")
            try:
                ZoneInfo(metadata["timezone"])
                ZoneInfo(metadata["calendar_timezone"])
            except (KeyError, ValueError) as exc:
                raise InvalidSchedulingInput("plant or calendar timezone is not a valid IANA timezone") from exc

            selected_scenario = None
            if scenario_id is not None:
                selected_scenario = conn.execute(text("""
                    SELECT s.id,s.code,s.name,s.status,s.row_version,
                           p.promotion_lock_version,sol.comparison,s.scenario_kind,sol.id AS solution_id,
                           (SELECT canonical_snapshot FROM production.product_definition_revisions d WHERE d.organization_id=s.organization_id AND d.id=sol.input_product_definition_revision_id) AS definition_snapshot,
                           COALESCE((sol.diagnostics->>'complete')::boolean,false) AS complete,
                           (s.status='stale'
                            OR s.base_state_revision_id<>h.current_revision_id
                            OR s.base_product_definition_revision_id<>p.current_product_definition_revision_id
                            OR s.base_plan_version_id IS DISTINCT FROM p.current_plan_version_id) AS stale
                      FROM planning.scenarios s
                      JOIN core.plants p
                        ON p.organization_id=s.organization_id AND p.id=s.plant_id
                      JOIN planning.planning_state_heads h
                        ON h.organization_id=s.organization_id AND h.plant_id=s.plant_id
                      JOIN LATERAL (
                        SELECT value.id,value.comparison,value.diagnostics,value.input_product_definition_revision_id
                          FROM planning.schedule_solutions value
                         WHERE value.organization_id=s.organization_id
                           AND value.scenario_id=s.id
                         ORDER BY value.run_no DESC LIMIT 1
                      ) sol ON true
                     WHERE s.organization_id=:org AND s.plant_id=:plant
                       AND s.id=:scenario AND s.scenario_kind IN ('initial','replan','simulation')
                """), {
                    "org": org, "plant": plant, "scenario": scenario_id,
                }).mappings().one_or_none()
                if selected_scenario is None:
                    raise EntityNotFound("scenario not found")
                selected_scenario = dict(selected_scenario)
                selected_scenario["expired"] = scenario_expired(
                    solution_timings(conn, org, selected_scenario["solution_id"]),
                    self._now(),
                )
                selected_scenario["origin_plan_version_number"] = (
                    metadata["plan_version_number"]
                    if selected_scenario["id"] == metadata["source_scenario_id"] else None
                )

            metadata=dict(metadata)
            initial_view = bool(selected_scenario and selected_scenario['scenario_kind']=='initial'
                                and metadata['plan_version_id'] is None)
            if initial_view:
                metadata['schedule_solution_id']=selected_scenario['solution_id']
                metadata['definition_snapshot']=selected_scenario['definition_snapshot']
            elif metadata['plan_version_id'] is None and selected_scenario:
                raise EntityNotFound('current plan not found')

            operation_rows = conn.execute(text("""
                WITH first_phase AS (
                    SELECT DISTINCT ON (ppr.operation_plan_result_id)
                           ppr.operation_plan_result_id,ph.id AS phase_id,
                           ph.name AS phase_name,
                           sum(ppr.planned_work_minutes+ppr.remaining_work_minutes) OVER (PARTITION BY ppr.operation_plan_result_id)::int AS duration_minutes,
                           ppr.explanation->'why_not_earlier'->>0 AS blocker_code
                      FROM planning.phase_plan_results ppr
                      JOIN production.required_operation_phases ph
                        ON ph.organization_id=ppr.organization_id
                       AND ph.id=ppr.required_operation_phase_id
                     WHERE ppr.organization_id=:org
                       AND ppr.schedule_solution_id IN (:solution,:overlay_solution)
                     ORDER BY ppr.operation_plan_result_id,ph.sequence_no
                ), people AS (
                    SELECT ppr.operation_plan_result_id,
                           jsonb_agg(DISTINCT jsonb_build_object(
                             'id',e.id,'name',e.display_name)) AS values
                      FROM planning.phase_plan_results ppr
                      JOIN planning.planned_phase_assignments pa
                        ON pa.organization_id=ppr.organization_id
                       AND pa.phase_plan_result_id=ppr.id
                      JOIN planning.assignment_segments seg
                        ON seg.organization_id=pa.organization_id
                       AND seg.planned_phase_assignment_id=pa.id
                      JOIN planning.human_segment_assignments ha
                        ON ha.organization_id=seg.organization_id
                       AND ha.assignment_segment_id=seg.id
                      JOIN capacity.employees e
                        ON e.organization_id=ha.organization_id
                       AND e.id=ha.employee_id
                     WHERE ppr.organization_id=:org
                       AND ppr.schedule_solution_id IN (:solution,:overlay_solution)
                     GROUP BY ppr.operation_plan_result_id
                ), resources AS (
                    SELECT ppr.operation_plan_result_id,
                           jsonb_agg(DISTINCT jsonb_build_object(
                             'id',pr.id,'name',pr.name,
                             'work_center_id',wc.id,
                             'scheduling_mode',pr.scheduling_mode,
                             'capacity_units',pr.capacity_units)) AS resource_values,
                           jsonb_agg(DISTINCT jsonb_build_object(
                             'id',wc.id,'name',wc.name,
                             'capacity_mode',wc.capacity_mode,
                             'aggregate_capacity',wc.aggregate_capacity)) AS center_values
                      FROM planning.phase_plan_results ppr
                      JOIN planning.planned_phase_assignments pa
                        ON pa.organization_id=ppr.organization_id
                       AND pa.phase_plan_result_id=ppr.id
                      JOIN planning.assignment_segments seg
                        ON seg.organization_id=pa.organization_id
                       AND seg.planned_phase_assignment_id=pa.id
                      JOIN planning.physical_resource_reservations rr
                        ON rr.organization_id=seg.organization_id
                       AND rr.assignment_segment_id=seg.id
                      JOIN capacity.physical_resources pr
                        ON pr.organization_id=rr.organization_id
                       AND pr.id=rr.physical_resource_id
                      JOIN capacity.work_centers wc
                        ON wc.organization_id=pr.organization_id
                       AND wc.id=pr.work_center_id
                     WHERE ppr.organization_id=:org
                       AND ppr.schedule_solution_id IN (:solution,:overlay_solution)
                     GROUP BY ppr.operation_plan_result_id
                ), latest_execution AS (
                    SELECT DISTINCT ON (oe.required_operation_id)
                           oe.required_operation_id,oe.id,oe.status
                      FROM execution.operation_executions oe
                      JOIN production.required_operations ro
                        ON ro.organization_id=oe.organization_id
                       AND ro.id=oe.required_operation_id
                      JOIN core.projects project
                        ON project.organization_id=ro.organization_id
                       AND project.id=ro.project_id
                     WHERE oe.organization_id=:org AND project.plant_id=:plant
                     ORDER BY oe.required_operation_id,
                              (oe.status IN ('running','paused')) DESC,
                              oe.created_at DESC
                ), actual AS (
                    SELECT oe.required_operation_id,
                           COALESCE(sum(es.work_minutes),0)::int AS executed_minutes,
                           jsonb_agg(jsonb_build_object(
                             'id',es.id,'started_at',lower(es.time_range),
                             'ended_at',upper(es.time_range),
                             'work_minutes',es.work_minutes)
                             ORDER BY lower(es.time_range),es.id)
                             FILTER (WHERE es.segment_kind='work') AS segments
                      FROM execution.operation_executions oe
                      JOIN execution.execution_segments es
                        ON es.organization_id=oe.organization_id
                       AND es.operation_execution_id=oe.id
                     WHERE oe.organization_id=:org
                       AND es.time_range && tstzrange(:range_from,:range_to,'[)')
                       AND NOT EXISTS(SELECT 1 FROM execution.execution_segments n
                         WHERE n.organization_id=es.organization_id AND n.supersedes_id=es.id)
                     GROUP BY oe.required_operation_id
                ), actual_people AS (
                    SELECT oe.required_operation_id,
                      jsonb_agg(DISTINCT jsonb_build_object('id',e.id,'name',e.display_name)) AS values
                    FROM execution.operation_executions oe
                    JOIN execution.execution_segments es ON es.organization_id=oe.organization_id AND es.operation_execution_id=oe.id
                    JOIN execution.actual_resource_usages u ON u.organization_id=es.organization_id AND u.execution_segment_id=es.id
                    JOIN capacity.employees e ON e.organization_id=u.organization_id AND e.id=u.employee_id
                    WHERE oe.organization_id=:org AND es.time_range && tstzrange(:range_from,:range_to,'[)')
                      AND NOT EXISTS(SELECT 1 FROM execution.execution_segments n WHERE n.organization_id=es.organization_id AND n.supersedes_id=es.id)
                      AND NOT EXISTS(SELECT 1 FROM execution.actual_resource_usages n WHERE n.organization_id=u.organization_id AND n.supersedes_id=u.id)
                    GROUP BY oe.required_operation_id
                ), actual_resources AS (
                    SELECT oe.required_operation_id,
                      jsonb_agg(DISTINCT jsonb_build_object('id',r.id,'name',r.name,'work_center_id',c.id,
                        'scheduling_mode',r.scheduling_mode,'capacity_units',r.capacity_units)) AS resource_values,
                      jsonb_agg(DISTINCT jsonb_build_object('id',c.id,'name',c.name,'capacity_mode',c.capacity_mode,
                        'aggregate_capacity',c.aggregate_capacity)) AS center_values
                    FROM execution.operation_executions oe
                    JOIN execution.execution_segments es ON es.organization_id=oe.organization_id AND es.operation_execution_id=oe.id
                    JOIN execution.actual_resource_usages u ON u.organization_id=es.organization_id AND u.execution_segment_id=es.id
                    JOIN capacity.physical_resources r ON r.organization_id=u.organization_id AND r.id=u.physical_resource_id
                    JOIN capacity.work_centers c ON c.organization_id=r.organization_id AND c.id=r.work_center_id
                    WHERE oe.organization_id=:org AND es.time_range && tstzrange(:range_from,:range_to,'[)')
                      AND NOT EXISTS(SELECT 1 FROM execution.execution_segments n WHERE n.organization_id=es.organization_id AND n.supersedes_id=es.id)
                      AND NOT EXISTS(SELECT 1 FROM execution.actual_resource_usages n WHERE n.organization_id=u.organization_id AND n.supersedes_id=u.id)
                    GROUP BY oe.required_operation_id
                )
                SELECT COALESCE(opr.schedule_solution_id,CAST(:solution AS uuid)) AS _solution_id,ro.id AS operation_id,project.id AS project_id,
                       project.code AS project_code,project.name AS project_name,
                       lot.code AS lot_code,lot.name AS lot_name,
                       ro.code AS operation_code,ro.name AS operation_name,
                       COALESCE(fp.phase_id,hp.id) AS phase_id,COALESCE(fp.phase_name,hp.name) AS phase_name,
                       COALESCE(fp.duration_minutes,hp.original_estimate_minutes) AS duration_minutes,
                       COALESCE((SELECT jsonb_agg(jsonb_build_object('id',pre.id,'name',pre.name) ORDER BY pre.code) FROM production.operation_precedences edge JOIN production.required_operations pre ON pre.organization_id=edge.organization_id AND pre.id=edge.predecessor_operation_id WHERE edge.organization_id=ro.organization_id AND edge.successor_operation_id=ro.id AND edge.active),'[]'::jsonb) AS predecessors,
                       opr.planned_start_at AS planned_start,
                       opr.planned_end_at AS planned_finish,
                       COALESCE(pe.values,ap.values,'[]'::jsonb) AS people,
                       COALESCE(re.center_values,ar.center_values,'[]'::jsonb) AS centers,
                       COALESCE(re.resource_values,ar.resource_values,'[]'::jsonb) AS resources,
                       priority.name AS priority,priority.rank AS priority_rank,
                       CASE
                         WHEN le.status='completed' OR opr.result_status='completed'
                           THEN 'FINALIZADO'
                         WHEN le.status IN ('running','paused')
                              AND opr.planned_end_at < now() THEN 'DEMORADO'
                         WHEN le.status IN ('running','paused') THEN 'EN_CURSO'
                         WHEN opr.result_status='blocked' THEN 'BLOQUEADO'
                         WHEN opr.planned_end_at < now() THEN 'DEMORADO'
                         WHEN opr.planned_start_at <= now() THEN 'LISTO'
                         ELSE 'PENDIENTE'
                       END AS operational_status,
                       COALESCE(act.executed_minutes,
                                rem.executed_labor_minutes_at_cutoff,0)::int AS executed_minutes,
                       CASE WHEN le.status='completed' THEN 0 ELSE rem.remaining_labor_minutes::int END AS remaining_minutes,
                       CASE WHEN le.status='completed' THEN NULL ELSE COALESCE(opr.explanation->'blockers'->>0,
                                fp.blocker_code) END AS blocker_code,
                       COALESCE(act.segments,'[]'::jsonb) AS actual_segments,
                       COALESCE((SELECT jsonb_agg(jsonb_build_object(
                         'started_at',lower(seg.time_range),'ended_at',upper(seg.time_range),
                         'phase_name',ph.name) ORDER BY lower(seg.time_range))
                         FROM planning.phase_plan_results ppr
                         JOIN production.required_operation_phases ph ON ph.organization_id=ppr.organization_id AND ph.id=ppr.required_operation_phase_id
                         JOIN planning.planned_phase_assignments pa ON pa.organization_id=ppr.organization_id AND pa.phase_plan_result_id=ppr.id
                         JOIN planning.assignment_segments seg ON seg.organization_id=pa.organization_id AND seg.planned_phase_assignment_id=pa.id
                         WHERE ppr.organization_id=opr.organization_id AND ppr.operation_plan_result_id=opr.id),'[]'::jsonb) AS planned_segments
                  FROM production.required_operations ro
                  LEFT JOIN planning.operation_plan_results opr
                    ON opr.organization_id=ro.organization_id AND opr.required_operation_id=ro.id
                   AND opr.schedule_solution_id IN (:solution,:overlay_solution)
                  JOIN core.projects project
                    ON project.organization_id=ro.organization_id
                   AND project.id=ro.project_id
                  JOIN core.project_priorities priority
                    ON priority.organization_id=project.organization_id
                   AND priority.id=project.priority_id
                  LEFT JOIN core.project_lots lot
                    ON lot.organization_id=ro.organization_id
                   AND lot.id=ro.project_lot_id
                  LEFT JOIN first_phase fp
                    ON fp.operation_plan_result_id=opr.id
                  LEFT JOIN LATERAL (SELECT ph.id,ph.name,ph.original_estimate_minutes
                    FROM production.required_operation_phases ph
                    WHERE ph.organization_id=ro.organization_id AND ph.required_operation_id=ro.id AND ph.status<>'archived'
                    ORDER BY ph.sequence_no LIMIT 1) hp ON opr.id IS NULL
                  LEFT JOIN people pe
                    ON pe.operation_plan_result_id=opr.id
                  LEFT JOIN resources re
                    ON re.operation_plan_result_id=opr.id
                  LEFT JOIN latest_execution le
                    ON le.required_operation_id=ro.id
                  LEFT JOIN execution.remaining_estimate_revisions rem
                    ON rem.organization_id=ro.organization_id
                   AND rem.operation_execution_id=le.id
                   AND rem.superseded_at IS NULL
                  LEFT JOIN actual act
                    ON act.required_operation_id=ro.id
                  LEFT JOIN actual_people ap ON ap.required_operation_id=ro.id
                  LEFT JOIN actual_resources ar ON ar.required_operation_id=ro.id
                 WHERE ro.organization_id=:org
                   AND (opr.id IS NOT NULL OR act.required_operation_id IS NOT NULL)
                   AND project.plant_id=:plant
                   AND ((opr.planned_start_at < :range_to
                         AND opr.planned_end_at > :range_from)
                        OR opr.result_status IN ('blocked','out_of_horizon')
                        OR :initial_view OR act.required_operation_id IS NOT NULL)
                 ORDER BY opr.planned_start_at NULLS LAST,priority.rank,ro.id
            """), {
                "org": org, "plant": plant,
                "solution": metadata["schedule_solution_id"],
                "overlay_solution": selected_scenario['solution_id'] if selected_scenario else None,
                "initial_view": bool(selected_scenario),
                "range_from": range_from, "range_to": range_to,
            }).mappings().all()

            occupation_rows = conn.execute(text("""
                SELECT po.id,project.name AS project_name,lot.name AS lot_name,
                       resource.id AS resource_id,resource.name AS resource_name,
                       lower(po.time_range) AS started_at,
                       upper(po.time_range) AS ended_at,po.source_kind
                  FROM planning.physical_occupations po
                  JOIN capacity.physical_resources resource
                    ON resource.organization_id=po.organization_id
                   AND resource.id=po.physical_resource_id
                  JOIN core.project_lots lot
                    ON lot.organization_id=po.organization_id
                   AND lot.id=po.project_lot_id
                  JOIN core.projects project
                    ON project.organization_id=lot.organization_id
                   AND project.id=lot.project_id
                 WHERE po.organization_id=:org
                   AND project.plant_id=:plant
                   AND po.is_effective
                   AND po.time_range && tstzrange(:range_from,:range_to,'[)')
                   AND (po.source_kind='actual'
                        OR po.schedule_solution_id=:solution)
                 ORDER BY lower(po.time_range),po.id
            """), {
                "org": org, "plant": plant,
                "solution": metadata["schedule_solution_id"],
                "range_from": range_from, "range_to": range_to,
            }).mappings().all()

            intervals = conn.execute(text("""
                SELECT weekday,local_start,local_end,valid_during,shift_code
                  FROM capacity.calendar_working_intervals
                 WHERE organization_id=:org AND calendar_id=:calendar
                 ORDER BY weekday,local_start
            """), {"org": org, "calendar": metadata["base_calendar_id"]}).mappings().all()
            exceptions = conn.execute(text("""
                SELECT exception_date,effect,time_range,reason
                  FROM capacity.calendar_exceptions
                 WHERE organization_id=:org AND calendar_id=:calendar
                   AND exception_date BETWEEN :first_day AND :last_day
                 ORDER BY exception_date,id
            """), {
                "org": org, "calendar": metadata["base_calendar_id"],
                "first_day": range_from.date() - timedelta(days=1),
                "last_day": range_to.date() + timedelta(days=1),
            }).mappings().all()

            scenario_options = conn.execute(text("""
                SELECT s.id,s.code,s.name,s.status,s.created_at,s.scenario_kind,
                       sol.id AS solution_id,
                       (s.status='stale'
                        OR s.base_state_revision_id<>h.current_revision_id
                        OR s.base_product_definition_revision_id<>p.current_product_definition_revision_id
                        OR s.base_plan_version_id IS DISTINCT FROM p.current_plan_version_id) AS stale
                  FROM planning.scenarios s
                  JOIN core.plants p
                    ON p.organization_id=s.organization_id AND p.id=s.plant_id
                  JOIN planning.planning_state_heads h
                    ON h.organization_id=s.organization_id AND h.plant_id=s.plant_id
                  JOIN LATERAL (SELECT value.id FROM planning.schedule_solutions value
                    WHERE value.organization_id=s.organization_id AND value.scenario_id=s.id
                    ORDER BY value.run_no DESC LIMIT 1) sol ON true
                 WHERE s.organization_id=:org AND s.plant_id=:plant
                   AND s.scenario_kind IN ('initial','replan','simulation')
                   AND s.status IN ('ready','stale','confirmed')
                 ORDER BY s.created_at DESC,s.id DESC LIMIT 50
            """), {"org": org, "plant": plant}).mappings().all()
            # Batch all option timings; visibility is independent of promotion eligibility.
            timing_rows = conn.execute(text("""
                SELECT opr.schedule_solution_id,opr.planned_start_at,opr.planned_end_at,
                       EXISTS(SELECT 1 FROM execution.operation_executions oe
                         WHERE oe.organization_id=opr.organization_id
                           AND oe.required_operation_id=opr.required_operation_id
                           AND oe.started_at IS NOT NULL) AS execution_started
                  FROM planning.operation_plan_results opr
                 WHERE opr.organization_id=:org AND opr.schedule_solution_id=ANY(:solutions)
            """), {"org":org,"solutions":[r['solution_id'] for r in scenario_options]}).mappings().all()
            timings_by_solution = {}
            for row in timing_rows:
                timings_by_solution.setdefault(row['schedule_solution_id'],[]).append(
                    PlannedOperationTiming(row['planned_start_at'],row['planned_end_at'],row['execution_started']))
            option_now = self._now()
            options = []
            for row in scenario_options:
                option = dict(row)
                solution_id = option.pop('solution_id')
                option['expired'] = scenario_expired(timings_by_solution.get(solution_id,()),option_now)
                option['origin_plan_version_number'] = (metadata['plan_version_number']
                    if option['id']==metadata['source_scenario_id'] else None)
                options.append(option)

            if metadata['plan_version_id'] is None and scenario_id is None and not scenario_options:
                raise EntityNotFound('current plan not found')

        operations, proposed = [], []
        for row in operation_rows:
            operation = dict(row)
            solution_id = operation.pop('_solution_id')
            if solution_id == metadata['schedule_solution_id']:
                operations.append(operation)
            if selected_scenario and solution_id == selected_scenario['solution_id']:
                proposed.append(operation.copy())
        if initial_view:
            pending=operations[:]
            operations=[]
            while pending:
                pending_ids={o['operation_id'] for o in pending}
                ready=next((o for o in pending if not {UUID(str(p['id'])) for p in o['predecessors']} & pending_ids),pending[0])
                pending.remove(ready)
                operations.append(ready)
        _enrich_gantt_definition(operations, metadata.get("definition_snapshot") or {})
        if selected_scenario and metadata['plan_version_id'] is not None:
            # Recompute dates against CURRENT, never against a historical stored base.
            selected_scenario['comparison'] = _gantt_current_comparison(operations,proposed,
                                                                       selected_scenario['comparison'])
            current_ids = {o['operation_id'] for o in operations}
            historical_only = [o for o in proposed if o['operation_id'] not in current_ids]
            _enrich_gantt_definition(historical_only,selected_scenario['definition_snapshot'] or {})
            operations.extend(o | {'planned_start':None,'planned_finish':None,'planned_segments':[]}
                              for o in historical_only)
        groups = _gantt_groups(operations, group_by)
        for operation in operations:
            operation["group_ids"] = _gantt_group_ids(operation, group_by)
        occupations = [
            dict(row) | {"group_id": str(row["resource_id"])}
            for row in occupation_rows
        ]
        scenario = _gantt_scenario({k: v for k, v in selected_scenario.items() if k != 'definition_snapshot'}) if selected_scenario else None
        if initial_view:
            scenario['affected_projects']=len({o['project_id'] for o in operations})
            scenario['changed_operations']=len(operations)
        return {
            "plant_name": metadata["plant_name"],
            "plan_version_id": metadata["plan_version_id"],
            "plan_version_number": metadata["plan_version_number"],
            "planning_state_revision_id": metadata["planning_state_revision_id"],
            "timezone": metadata["timezone"],
            "range_from": range_from,
            "range_to": range_to,
            "generated_at": datetime.now(timezone.utc),
            "group_by": group_by,
            "groups": groups,
            "operations": operations,
            "occupations": occupations,
            "working_windows": _working_windows(
                range_from, range_to, metadata["calendar_timezone"],
                intervals, exceptions,
            ),
            "available_scenarios": options,
            "scenario": scenario,
        }


def _gantt_current_comparison(current, proposed, original):
    """Ephemeral date comparison against CURRENT, including historical initial runs."""
    old = {o['operation_id']:o for o in current}
    new = {o['operation_id']:o for o in proposed}
    changes = []
    for identifier in sorted(old.keys() | new.keys(),key=str):
        a,b = old.get(identifier),new.get(identifier)
        previous = ({'start':a['planned_start'],'end':a['planned_finish']} if a else None)
        following = ({'start':b['planned_start'],'end':b['planned_finish']} if b else None)
        delta = (int((b['planned_finish']-a['planned_finish']).total_seconds()//60)
                 if a and b and a['planned_finish'] and b['planned_finish'] else None)
        removed = not b or not b['planned_finish']
        impact = ('removed_from_future' if removed else 'newly_planned' if not a
                  else 'delayed' if delta and delta>0 else 'advanced' if delta and delta<0 else 'changed')
        changes.append({'operation_id':str(identifier),'project_id':str((b or a)['project_id']),
                        'changed':previous!=following,'impact_kind':impact,
                        'delta_minutes':delta,'old':previous,'new':following})
    finishes = []
    projects = {o['project_id'] for o in [*current,*proposed]}
    for project in sorted(projects,key=str):
        a = max((o['planned_finish'] for o in current if o['project_id']==project and o['planned_finish']),default=None)
        b = max((o['planned_finish'] for o in proposed if o['project_id']==project and o['planned_finish']),default=None)
        if a!=b:
            finishes.append({'project_id':str(project),'current_finish':a,'scenario_finish':b})
    return dict(original or {}) | {
        'operations':changes,'changed_operations':sum(c['changed'] for c in changes),
        'frontier_project_ids':[str(p) for p in sorted(projects,key=str)],
        'customer_date_alert_items':finishes,
    }


def _gantt_group_ids(operation: dict[str, Any], group_by: str) -> list[str]:
    if group_by == "project":
        return [str(operation["project_id"])]
    key = {"center": "centers", "resource": "resources", "person": "people"}[group_by]
    values = [str(item["id"]) for item in operation[key]]
    return values or [f"unassigned-{group_by}"]


def _gantt_groups(operations: list[dict[str, Any]], group_by: str) -> list[dict[str, Any]]:
    values: dict[str, dict[str, Any]] = {}
    for operation in operations:
        if group_by == "project":
            identifier = str(operation["project_id"])
            values[identifier] = {
                "id": identifier, "label": operation["project_name"],
                "kind": "project",
            }
            continue
        key = {"center": "centers", "resource": "resources", "person": "people"}[group_by]
        for item in operation[key]:
            identifier = str(item["id"])
            group = {
                "id": identifier, "label": item["name"], "kind": group_by,
                "capacity_mode": None, "capacity": None,
            }
            if group_by == "center":
                group["capacity_mode"] = item["capacity_mode"]
                group["capacity"] = item["aggregate_capacity"]
            elif group_by == "resource":
                group["capacity_mode"] = item["scheduling_mode"]
                group["capacity"] = item["capacity_units"]
            values[identifier] = group
        if not operation[key]:
            values[f"unassigned-{group_by}"] = {
                "id": f"unassigned-{group_by}",
                "label": "Sin asignar", "kind": group_by,
                "capacity_mode": None, "capacity": None,
            }
    return sorted(values.values(), key=lambda item: (item["label"].casefold(), item["id"]))


def _gantt_scenario(row: Any) -> dict[str, Any]:
    value = dict(row)
    comparison = value.pop("comparison") or {}
    operations = []
    for item in comparison.get("operations", []):
        impact = item.get("impact_kind")
        if not item.get("changed"):
            difference = "UNCHANGED"
        elif impact == "delayed":
            difference = "DELAYED"
        elif impact == "advanced":
            difference = "ADVANCED"
        elif impact == "removed_from_future":
            difference = "OUT_OF_HORIZON"
        elif impact == "newly_planned":
            difference = "NEWLY_PLANNED"
        else:
            difference = "SHIFTED"
        proposed = item.get("new") or {}
        operations.append({
            "operation_id": item["operation_id"],
            "planned_start": proposed.get("start"),
            "planned_finish": proposed.get("end"),
            "difference": difference,
            "delta_minutes": item.get("delta_minutes"),
        })
    return value | {
        "changed_operations": int(comparison.get("changed_operations", 0)),
        "affected_projects": len(comparison.get("frontier_project_ids", [])),
        "customer_date_alerts": int(comparison.get("customer_date_alerts", 0)),
        "communication_recommended": int(comparison.get("customer_date_alerts", 0)) > 0,
        "project_finish_changes": comparison.get("customer_date_alert_items", []),
        "operations": operations,
        "manual_intent": comparison.get("manual_intent"),
    }


def _working_windows(range_from: datetime, range_to: datetime, timezone_name: str,
                     intervals: list[Any], exceptions: list[Any]) -> list[dict[str, Any]]:
    zone = ZoneInfo(timezone_name)
    first_day = range_from.astimezone(zone).date()
    last_day = (range_to - timedelta(microseconds=1)).astimezone(zone).date()
    exceptions_by_day: dict[date, list[Any]] = {}
    for row in exceptions:
        exceptions_by_day.setdefault(row["exception_date"], []).append(row)
    result: list[dict[str, Any]] = []
    current = first_day
    while current <= last_day:
        windows: list[tuple[datetime, datetime, str, str | None]] = []
        for interval in intervals:
            valid = interval["valid_during"]
            if interval["weekday"] != current.isoweekday():
                continue
            if valid.lower is not None and current < valid.lower:
                continue
            if valid.upper is not None and current >= valid.upper:
                continue
            windows.append((
                datetime.combine(current, interval["local_start"], zone),
                datetime.combine(current, interval["local_end"], zone),
                "regular", interval["shift_code"],
            ))
        for exception in exceptions_by_day.get(current, []):
            effect = str(exception["effect"])
            exception_range = exception["time_range"]
            start = exception_range.lower if exception_range is not None else None
            end = exception_range.upper if exception_range is not None else None
            if effect == "replace":
                windows = []
            elif effect == "remove":
                if start is None or end is None:
                    windows = []
                else:
                    windows = _subtract_windows(windows, start, end)
            if effect in {"add", "replace"} and start is not None and end is not None:
                windows.append((start, end, "exception", exception["reason"]))
        for start, end, kind, label in windows:
            clipped_start = max(start.astimezone(timezone.utc), range_from)
            clipped_end = min(end.astimezone(timezone.utc), range_to)
            if clipped_start < clipped_end:
                result.append({
                    "started_at": clipped_start, "ended_at": clipped_end,
                    "kind": kind, "label": label,
                })
        current += timedelta(days=1)
    return sorted(result, key=lambda item: (item["started_at"], item["ended_at"]))


def _subtract_windows(windows: list[tuple[datetime, datetime, str, str | None]],
                      remove_start: datetime, remove_end: datetime
                      ) -> list[tuple[datetime, datetime, str, str | None]]:
    result = []
    for start, end, kind, label in windows:
        if remove_end <= start or remove_start >= end:
            result.append((start, end, kind, label))
            continue
        if start < remove_start:
            result.append((start, remove_start, kind, label))
        if remove_end < end:
            result.append((remove_end, end, kind, label))
    return result


def _enrich_gantt_definition(operations: list[dict[str, Any]], snapshot: dict[str, Any]) -> None:
    """Display frozen metadata, never the next mutable draft or live stage catalog."""
    index = {}
    for project in snapshot.get("projects", []):
        for lot in [*project.get("lots", []), {"code": None, "operations": project.get("unassigned_operations", [])}]:
            for op in lot.get("operations", []):
                index[(project["code"], lot.get("code"), op["code"])] = (project, op)
    for row in operations:
        found = index.get((row["project_code"], row["lot_code"], row["operation_code"]))
        if not found:
            continue
        project, op = found
        phase = next((p for p in op.get("phases", []) if p.get("name") == row["phase_name"]), {})
        row.update(stage_name=op.get("stage_name") or op.get("operation_definition_code"),
                   stage_order=op.get("stage_order"), operation_order=op.get("operation_order"),
                   committed_date=project.get("committed_date"), split_policy=phase.get("split_policy"),
                   skill_codes=[r["code"] for p in op.get("phases", []) for r in p.get("labor_requirements", []) if r.get("is_mandatory")])
