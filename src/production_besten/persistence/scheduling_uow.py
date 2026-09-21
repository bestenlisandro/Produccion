from __future__ import annotations

import hashlib
import json
import time as clock
from collections import defaultdict
from dataclasses import asdict, is_dataclass, replace
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from math import ceil
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, text

from production_besten.domain.errors import (
    EntityNotFound, IdempotencyConflict, InvalidSchedulingInput, ReplanConflict, RevisionConflict,
    SchedulingBaseStale,
)
from production_besten.domain.replanning import (
    RejectReplan, RejectReplanResult, ReplanRequest, ReplanResult,
)
from production_besten.domain.scheduling.engine import GreedyFiniteCapacityScheduler
from production_besten.domain.scheduling.models import (
    CalendarData, CalendarException, CalendarInterval, CapacityUsage, EmployeeData, GateData,
    GenerateSchedule, LaborNeed, OvertimeData, PhaseData, PhysicalNeed,
    PrecedenceData, ProjectData, ResourceData, ScheduleGenerationResult,
    SchedulingInput, SchedulingOutput, TimeWindow,
)


class PostgresSchedulingUnitOfWork:
    def __init__(self, engine: Engine, *, failpoint: str | None = None) -> None:
        self._engine = engine
        self._failpoint = failpoint
        self._connection: Connection | None = None
        self._transaction: Any = None

    def __enter__(self):
        self._connection = self._engine.connect()
        self._transaction = self._connection.begin()
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        try:
            self._transaction.commit() if exc_type is None else self._transaction.rollback()
        finally:
            self._connection.close()
        return False

    @property
    def conn(self) -> Connection:
        if self._connection is None:
            raise RuntimeError("unit of work is not active")
        return self._connection

    def generate_schedule(self, command: GenerateSchedule) -> ScheduleGenerationResult:
        command.validate()
        started_perf = clock.perf_counter()
        started_at = datetime.now(timezone.utc)
        base = self._lock_and_validate_base(command)
        scenario_id, solution_id = uuid4(), uuid4()
        scenario_kind = "initial" if base["current_plan_version_id"] is None else "simulation"
        horizon_days = max(1, ceil((command.horizon_end - command.horizon_start).total_seconds() / 86400))
        parameters = {"scheduler_version": GreedyFiniteCapacityScheduler.version,
                      "project_ids": [str(value) for value in command.project_ids], **command.parameters}
        self.conn.execute(text("""
            INSERT INTO planning.scenarios
              (id,organization_id,plant_id,scenario_kind,base_plan_version_id,
               base_state_revision_id,base_product_definition_revision_id,code,name,status,
               horizon_days,horizon_range,parameters,requested_by,started_at)
            VALUES (:id,:org,:plant,:kind,:plan,:state,:definition,:code,:name,'calculating',
                    :days,tstzrange(:start,:finish,'[)'),CAST(:parameters AS jsonb),:actor,:started)
        """), {"id": scenario_id, "org": command.organization_id, "plant": command.plant_id,
                "kind": scenario_kind, "plan": base["current_plan_version_id"],
                "state": command.planning_state_revision_id,
                "definition": command.product_definition_revision_id, "code": command.code.strip(),
                "name": command.name.strip(), "days": horizon_days, "start": command.horizon_start,
                "finish": command.horizon_end, "parameters": _json(parameters),
                "actor": command.actor_id, "started": started_at})
        value, product_snapshot = self._load_input(command, base["current_plan_version_id"], scenario_id)
        input_snapshot = {"scheduler_version": GreedyFiniteCapacityScheduler.version,
                          "product_definition": product_snapshot,
                          "capacity_and_state": _jsonable(value)}
        input_json = _json(input_snapshot)
        input_hash = hashlib.sha256(input_json.encode("utf-8")).digest()
        output = GreedyFiniteCapacityScheduler().schedule(value)
        finished_at = datetime.now(timezone.utc)
        elapsed_ms = round((clock.perf_counter() - started_perf) * 1000)
        if output.status == "failed":
            self.conn.execute(text("""
                INSERT INTO planning.schedule_solutions
                  (id,organization_id,scenario_id,run_no,status,algorithm_version,
                   input_product_definition_revision_id,base_state_revision_id,input_snapshot,
                   input_sha256,parameters,started_at,finished_at,diagnostics,horizon_range,metrics,failed_reason)
                VALUES (:id,:org,:scenario,1,'failed',:algorithm,:definition,:state,
                        CAST(:input AS jsonb),:hash,CAST(:parameters AS jsonb),:started,:finished,
                        CAST(:diagnostics AS jsonb),tstzrange(:hstart,:hend,'[)'),CAST(:metrics AS jsonb),:reason)
            """), {"id": solution_id, "org": command.organization_id, "scenario": scenario_id,
                    "algorithm": GreedyFiniteCapacityScheduler.version,
                    "definition": command.product_definition_revision_id,
                    "state": command.planning_state_revision_id, "input": input_json, "hash": input_hash,
                    "parameters": _json(parameters), "started": started_at, "finished": finished_at,
                    "diagnostics": _json({"complete": False}), "hstart": command.horizon_start,
                    "hend": command.horizon_end, "metrics": _json({"elapsed_ms": elapsed_ms}),
                    "reason": output.failed_reason})
            self.conn.execute(text("UPDATE planning.scenarios SET status='failed',completed_at=:at,updated_at=:at,row_version=row_version+1,rejection_reason=:reason WHERE organization_id=:org AND id=:id"), {"at": finished_at, "reason": output.failed_reason, "org": command.organization_id, "id": scenario_id})
            return ScheduleGenerationResult(scenario_id, solution_id, "failed", False, 0, 0, 0, None, elapsed_ms, output.failed_reason)

        solution_json = _json(_semantic_output(output, value))
        solution_hash = hashlib.sha256(solution_json.encode("utf-8")).digest()
        counts = _counts(output)
        self.conn.execute(text("""
            INSERT INTO planning.schedule_solutions
              (id,organization_id,scenario_id,run_no,status,algorithm_version,
               input_product_definition_revision_id,base_state_revision_id,input_snapshot,input_sha256,
               parameters,started_at,finished_at,diagnostics,horizon_range,solution_sha256,metrics,ready_at)
            VALUES (:id,:org,:scenario,1,'ready',:algorithm,:definition,:state,CAST(:input AS jsonb),:input_hash,
                    CAST(:parameters AS jsonb),:started,:finished,CAST(:diagnostics AS jsonb),
                    tstzrange(:hstart,:hend,'[)'),:solution_hash,CAST(:metrics AS jsonb),:finished)
        """), {"id": solution_id, "org": command.organization_id, "scenario": scenario_id,
                "algorithm": GreedyFiniteCapacityScheduler.version,
                "definition": command.product_definition_revision_id,
                "state": command.planning_state_revision_id, "input": input_json, "input_hash": input_hash,
                "parameters": _json(parameters), "started": started_at, "finished": finished_at,
                "diagnostics": _json({"complete": output.complete, "blocker_vocabulary": sorted(_all_blockers(output))}),
                "hstart": command.horizon_start, "hend": command.horizon_end,
                "solution_hash": solution_hash,
                "metrics": _json({"elapsed_ms": elapsed_ms, **counts})})
        if self._failpoint == "after_solution":
            raise RuntimeError("injected persistence failure after schedule solution")
        self._persist_outcomes(command.organization_id, solution_id, value, output)
        self.conn.execute(text("UPDATE planning.scenarios SET status='ready',completed_at=:at,updated_at=:at,row_version=row_version+1 WHERE organization_id=:org AND id=:id"), {"at": finished_at, "org": command.organization_id, "id": scenario_id})
        self.conn.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        return ScheduleGenerationResult(scenario_id, solution_id, "ready", output.complete,
            counts["planned_phases"], counts["blocked_phases"], counts["out_of_horizon_phases"],
            solution_hash.hex(), elapsed_ms)

    def replan(self, command: ReplanRequest) -> ReplanResult:
        """Materialize an isolated, comparable replan; never publish it."""
        command.validate()
        plant = self.conn.execute(text("""
            SELECT current_plan_version_id,current_product_definition_revision_id
              FROM core.plants
             WHERE organization_id=:org AND id=:plant FOR UPDATE
        """), {"org": command.organization_id, "plant": command.plant_id}).mappings().one_or_none()
        if plant is None:
            raise EntityNotFound("plant not found in organization")
        head = self.conn.execute(text("""
            SELECT current_revision_id FROM planning.planning_state_heads
             WHERE organization_id=:org AND plant_id=:plant FOR UPDATE
        """), {"org": command.organization_id, "plant": command.plant_id}).mappings().one_or_none()
        if head is None:
            raise EntityNotFound("planning state head not found in organization")
        if (plant["current_plan_version_id"] != command.base_plan_version_id
                or plant["current_product_definition_revision_id"] != command.product_definition_revision_id
                or head["current_revision_id"] != command.planning_state_revision_id):
            raise SchedulingBaseStale("replan base is stale")
        self.conn.execute(text("""
            UPDATE planning.scenarios
               SET status='stale',updated_at=now(),row_version=row_version+1
             WHERE organization_id=:org AND plant_id=:plant
               AND scenario_kind='replan' AND status='ready'
               AND (base_plan_version_id<>:plan OR base_state_revision_id<>:state
                    OR base_product_definition_revision_id<>:definition)
        """), {"org": command.organization_id, "plant": command.plant_id,
                 "plan": command.base_plan_version_id,
                 "state": command.planning_state_revision_id,
                 "definition": command.product_definition_revision_id})

        replay = self.conn.execute(text("""
            SELECT s.id AS scenario_id,sol.id AS solution_id,s.status,sol.solution_sha256,
                   sol.metrics,sol.comparison,s.parameters
              FROM planning.scenarios s
              JOIN planning.schedule_solutions sol
                ON sol.organization_id=s.organization_id AND sol.scenario_id=s.id
             WHERE s.organization_id=:org AND s.plant_id=:plant
               AND s.parameters->>'idempotency_key'=:key
        """), {"org": command.organization_id, "plant": command.plant_id,
                 "key": command.idempotency_key.strip()}).mappings().one_or_none()
        if replay is not None:
            replay_meta = replay["parameters"].get("replan", {})
            expected_target = (str(command.trigger_operation_id)
                               if command.trigger_operation_id else str(command.project_id))
            stored_target = (replay_meta.get("trigger_operation_id")
                             or replay_meta.get("trigger_project_id"))
            if (replay["parameters"].get("command") != command.command_name
                    or replay_meta.get("cutoff_at") != command.cutoff_at.isoformat()
                    or stored_target != expected_target):
                raise IdempotencyConflict(
                    "idempotency key was reused with incompatible replan data"
                )
            comparison = replay["comparison"] or {}
            metrics = replay["metrics"] or {}
            return ReplanResult(
                replay["scenario_id"], replay["solution_id"], replay["status"],
                bool(metrics.get("complete", replay["status"] == "ready")),
                tuple(UUID(x) for x in comparison.get("frontier_project_ids", [])),
                tuple(UUID(x) for x in comparison.get("frontier_operation_ids", [])),
                int(comparison.get("changed_operations", 0)),
                int(comparison.get("customer_date_alerts", 0)),
                replay["solution_sha256"].hex() if replay["solution_sha256"] else None,
                int(metrics.get("elapsed_ms", 0)), True,
            )

        baseline_solution_id = self.conn.scalar(text("""
            SELECT schedule_solution_id FROM planning.plan_versions
             WHERE organization_id=:org AND plant_id=:plant AND id=:plan
        """), {"org": command.organization_id, "plant": command.plant_id,
                 "plan": command.base_plan_version_id})
        if baseline_solution_id is None:
            raise EntityNotFound("base plan not found in organization and plant")
        frontier_projects, frontier_operations = self._impact_frontier(
            command, baseline_solution_id
        )
        parameters = {
            **(command.parameters or {}),
            "command": command.command_name,
            "replan_version": "v1-replan-1",
            "idempotency_key": command.idempotency_key.strip(),
            "replan": {
                "cutoff_at": command.cutoff_at.isoformat(),
                "base_solution_id": str(baseline_solution_id),
                "frontier_operation_ids": [str(x) for x in frontier_operations],
                "trigger_operation_id": (str(command.trigger_operation_id)
                                         if command.trigger_operation_id else None),
                "trigger_project_id": (str(command.project_id)
                                       if command.project_id else None),
            },
        }
        generated = self.generate_schedule(GenerateSchedule(
            command.organization_id, command.plant_id, command.actor_id,
            command.code, command.name, command.cutoff_at, command.horizon_end,
            command.product_definition_revision_id, command.planning_state_revision_id,
            frontier_projects, parameters,
        ))
        self.conn.execute(text("""
            UPDATE planning.scenarios SET scenario_kind='replan'
             WHERE organization_id=:org AND id=:scenario
        """), {"org": command.organization_id, "scenario": generated.scenario_id})
        comparison = self._compare_replan(
            command, baseline_solution_id, generated.solution_id,
            frontier_projects, frontier_operations,
        )
        self.conn.execute(text("""
            UPDATE planning.schedule_solutions
               SET baseline_solution_id=:baseline,
                   impact_summary=CAST(:impact AS jsonb),
                   comparison=CAST(:comparison AS jsonb),
                   metrics=metrics || CAST(:extra_metrics AS jsonb)
             WHERE organization_id=:org AND id=:solution
        """), {"baseline": baseline_solution_id,
                 "impact": _json(comparison["impact_summary"]),
                 "comparison": _json(comparison),
                 "extra_metrics": _json({"complete": generated.complete}),
                 "org": command.organization_id, "solution": generated.solution_id})
        for item in comparison["operations"]:
            if not item["changed"]:
                continue
            self.conn.execute(text("""
                INSERT INTO planning.impact_items
                  (organization_id,schedule_solution_id,project_id,required_operation_id,
                   impact_kind,delta_minutes,old_value,new_value,reason)
                VALUES (:org,:solution,:project,:operation,:kind,:delta,
                        CAST(:old AS jsonb),CAST(:new AS jsonb),CAST(:reason AS jsonb))
            """), {"org": command.organization_id, "solution": generated.solution_id,
                    "project": UUID(item["project_id"]),
                    "operation": UUID(item["operation_id"]),
                    "kind": item["impact_kind"], "delta": item["delta_minutes"],
                    "old": _json(item["old"]), "new": _json(item["new"]),
                    "reason": _json(item["reason"])})
        return ReplanResult(
            generated.scenario_id, generated.solution_id, generated.status,
            generated.complete, frontier_projects, frontier_operations,
            comparison["changed_operations"], comparison["customer_date_alerts"],
            generated.solution_sha256, generated.elapsed_ms,
        )

    def reject_replan(self, command: RejectReplan) -> RejectReplanResult:
        command.validate()
        if not self.conn.scalar(text("""
            SELECT EXISTS(SELECT 1 FROM core.user_profiles
             WHERE organization_id=:org AND id=:actor)
        """), {"org": command.organization_id, "actor": command.actor_id}):
            raise EntityNotFound("actor not found in organization")
        row = self.conn.execute(text("""
            SELECT status,row_version,scenario_kind FROM planning.scenarios
             WHERE organization_id=:org AND plant_id=:plant AND id=:scenario FOR UPDATE
        """), {"org": command.organization_id, "plant": command.plant_id,
                 "scenario": command.scenario_id}).mappings().one_or_none()
        if row is None:
            raise EntityNotFound("replan scenario not found in organization and plant")
        if row["scenario_kind"] != "replan":
            raise ReplanConflict("only replan scenarios can be rejected")
        if row["status"] == "rejected":
            return RejectReplanResult(command.scenario_id, "rejected", row["row_version"], True)
        if row["status"] not in {"ready", "stale"}:
            raise ReplanConflict(f"scenario in status {row['status']} cannot be rejected")
        if row["row_version"] != command.expected_row_version:
            raise RevisionConflict(
                f"expected row version {command.expected_row_version}, current is {row['row_version']}"
            )
        updated = self.conn.execute(text("""
            UPDATE planning.scenarios
               SET status='rejected',rejected_at=now(),rejection_reason=:reason,
                   updated_at=now(),row_version=row_version+1
             WHERE organization_id=:org AND id=:scenario
             RETURNING row_version
        """), {"reason": command.reason.strip(), "org": command.organization_id,
                 "scenario": command.scenario_id}).scalar_one()
        return RejectReplanResult(command.scenario_id, "rejected", updated)

    def _lock_and_validate_base(self, command):
        plant = self.conn.execute(text("""
            SELECT id,base_calendar_id,current_product_definition_revision_id,current_plan_version_id
            FROM core.plants WHERE organization_id=:org AND id=:plant FOR UPDATE
        """), {"org": command.organization_id, "plant": command.plant_id}).mappings().one_or_none()
        if plant is None:
            raise EntityNotFound("plant not found in organization")
        head = self.conn.execute(text("SELECT current_revision_id FROM planning.planning_state_heads WHERE organization_id=:org AND plant_id=:plant FOR UPDATE"), {"org": command.organization_id, "plant": command.plant_id}).mappings().one_or_none()
        if head is None:
            raise EntityNotFound("planning state head not found in organization")
        if plant["current_product_definition_revision_id"] != command.product_definition_revision_id or head["current_revision_id"] != command.planning_state_revision_id:
            raise SchedulingBaseStale("scheduler base revisions must be current when materializing a new input snapshot")
        if not self.conn.scalar(text("SELECT EXISTS(SELECT 1 FROM core.user_profiles WHERE organization_id=:org AND id=:actor)"), {"org": command.organization_id, "actor": command.actor_id}):
            raise EntityNotFound("actor not found in organization")
        if self.conn.scalar(text("SELECT EXISTS(SELECT 1 FROM planning.scenarios WHERE organization_id=:org AND plant_id=:plant AND code=:code)"), {"org": command.organization_id, "plant": command.plant_id, "code": command.code.strip()}):
            raise InvalidSchedulingInput("scenario code already exists in plant")
        return plant

    def _load_input(self, command, base_plan, scenario_id):
        definition = self.conn.execute(text("SELECT canonical_snapshot FROM production.product_definition_revisions WHERE organization_id=:org AND plant_id=:plant AND id=:id"), {"org": command.organization_id, "plant": command.plant_id, "id": command.product_definition_revision_id}).mappings().one()
        params = {"org": command.organization_id, "plant": command.plant_id,
                  "ids": list(command.project_ids), "all": not command.project_ids}
        project_rows = self.conn.execute(text("""
            SELECT p.id,p.code,pp.code AS priority_code,pp.rank AS priority_rank,p.committed_date
            FROM core.projects p JOIN core.project_priorities pp
              ON pp.organization_id=p.organization_id AND pp.id=p.priority_id
            WHERE p.organization_id=:org AND p.plant_id=:plant AND p.status IN ('draft','active')
              AND (:all OR p.id=ANY(:ids)) ORDER BY p.code
        """), params).mappings().all()
        if command.project_ids and {row["id"] for row in project_rows} != set(command.project_ids):
            raise EntityNotFound("one or more projects not found in plant and organization")
        projects = tuple(ProjectData(row["id"], row["code"], row["priority_code"], row["priority_rank"], row["committed_date"]) for row in project_rows)
        project_ids = [row["id"] for row in project_rows]
        operation_rows = self.conn.execute(text("""
            SELECT ro.id,ro.project_id,ro.project_lot_id,ro.code,ro.earliest_start_at,ro.settings,
                   l.code AS lot_code,COALESCE(l.sequence_no,32767) AS lot_sequence
            FROM production.required_operations ro
            LEFT JOIN core.project_lots l ON l.organization_id=ro.organization_id AND l.id=ro.project_lot_id
            WHERE ro.organization_id=:org AND ro.project_id=ANY(:projects)
              AND ro.status IN ('draft','active') AND ro.cancelled_at IS NULL ORDER BY ro.code
        """), {"org": command.organization_id, "projects": project_ids}).mappings().all() if project_ids else []
        if command.parameters.get("replan"):
            allowed = {UUID(value) for value in command.parameters["replan"]["frontier_operation_ids"]}
            operation_rows = [row for row in operation_rows if row["id"] in allowed]
        operation_ids = [row["id"] for row in operation_rows]
        phase_rows = self.conn.execute(text("""
            SELECT ph.*,ro.project_id,ro.project_lot_id,ro.code AS operation_code,
                   ro.earliest_start_at AS operation_earliest,ro.settings,
                   p.code AS project_code,l.code AS lot_code,COALESCE(l.sequence_no,32767) AS lot_sequence
            FROM production.required_operation_phases ph
            JOIN production.required_operations ro ON ro.organization_id=ph.organization_id AND ro.id=ph.required_operation_id
            JOIN core.projects p ON p.organization_id=ro.organization_id AND p.id=ro.project_id
            LEFT JOIN core.project_lots l ON l.organization_id=ro.organization_id AND l.id=ro.project_lot_id
            WHERE ph.organization_id=:org AND ph.required_operation_id=ANY(:operations)
              AND ph.status IN ('draft','active') ORDER BY p.code,l.sequence_no,ro.code,ph.sequence_no,ph.code
        """), {"org": command.organization_id, "operations": operation_ids}).mappings().all() if operation_ids else []
        phase_ids = [row["id"] for row in phase_rows]
        labor_rows = self.conn.execute(text("SELECT required_operation_phase_id,skill_id,min_people,max_people,work_minutes FROM production.operation_labor_requirements WHERE organization_id=:org AND required_operation_phase_id=ANY(:phases) AND is_mandatory ORDER BY id"), {"org": command.organization_id, "phases": phase_ids}).mappings().all() if phase_ids else []
        physical_rows = self.conn.execute(text("SELECT id,required_operation_phase_id,physical_resource_type_id,physical_resource_group_id,work_center_id,quantity,capacity_units,usage_mode FROM production.operation_physical_requirements WHERE organization_id=:org AND required_operation_phase_id=ANY(:phases) AND is_mandatory ORDER BY id"), {"org": command.organization_id, "phases": phase_ids}).mappings().all() if phase_ids else []
        gates = self._load_gates(command.organization_id, operation_rows, phase_rows)
        labor_by, physical_by = defaultdict(list), defaultdict(list)
        for row in labor_rows:
            labor_by[row["required_operation_phase_id"]].append(LaborNeed(row["skill_id"], row["min_people"], row["max_people"], row["work_minutes"]))
        for row in physical_rows:
            physical_by[row["required_operation_phase_id"]].append(PhysicalNeed(row["id"], row["physical_resource_type_id"], row["physical_resource_group_id"], row["work_center_id"], float(row["quantity"]), float(row["capacity_units"]), row["usage_mode"]))
        phases = tuple(PhaseData(row["id"], row["required_operation_id"], row["project_id"], row["project_code"],
            row["project_lot_id"], row["lot_code"], row["lot_sequence"], row["operation_code"],
            row["sequence_no"], row["code"], row["original_estimate_minutes"], row["estimate_kind"],
            row["split_policy"], max(filter(None, (row["operation_earliest"], row["earliest_start_at"])), default=None),
            bool(row["settings"].get("scalable_labor", False)), tuple(labor_by[row["id"]]),
            tuple(physical_by[row["id"]]), tuple(gates[row["id"]])) for row in phase_rows)
        remaining_revision_by_phase = {}
        if command.parameters.get("replan"):
            phases, remaining_revision_by_phase = self._apply_replanning_state(
                command, phases
            )
        self._remaining_revision_by_phase = remaining_revision_by_phase
        precedence_rows = self.conn.execute(text("SELECT predecessor_operation_id,successor_operation_id,precedence_type,lag_minutes FROM production.operation_precedences WHERE organization_id=:org AND active AND predecessor_operation_id=ANY(:operations) AND successor_operation_id=ANY(:operations) ORDER BY predecessor_operation_id,successor_operation_id"), {"org": command.organization_id, "operations": operation_ids}).mappings().all() if operation_ids else []
        precedences = tuple(PrecedenceData(
            row["predecessor_operation_id"], row["successor_operation_id"],
            row["precedence_type"], row["lag_minutes"],
        ) for row in precedence_rows)
        employees, resources, calendars, unavailability, occupations, actual_capacity, overtime = self._load_capacity(command, scenario_id)
        active_operation_ids = {phase.operation_id for phase in phases}
        precedences = tuple(
            edge for edge in precedences
            if edge.predecessor_operation_id in active_operation_ids
            and edge.successor_operation_id in active_operation_ids
        )
        return SchedulingInput(command.organization_id, command.plant_id,
            self.conn.scalar(text("SELECT base_calendar_id FROM core.plants WHERE organization_id=:org AND id=:plant"), {"org": command.organization_id, "plant": command.plant_id}),
            command.horizon_start, command.horizon_end, command.product_definition_revision_id,
            command.planning_state_revision_id, base_plan, projects, phases, precedences, calendars,
            employees, resources, unavailability, occupations, actual_capacity, overtime), definition["canonical_snapshot"]

    def _impact_frontier(self, command, baseline_solution_id):
        operations = self.conn.execute(text("""
            SELECT ro.id,ro.project_id
              FROM production.required_operations ro
              JOIN core.projects p ON p.organization_id=ro.organization_id AND p.id=ro.project_id
             WHERE ro.organization_id=:org AND p.plant_id=:plant
               AND ro.status IN ('draft','active') AND ro.cancelled_at IS NULL
        """), {"org": command.organization_id,
                 "plant": command.plant_id}).mappings().all()
        project_by_operation = {row["id"]: row["project_id"] for row in operations}
        if command.trigger_operation_id:
            if command.trigger_operation_id not in project_by_operation:
                raise EntityNotFound("trigger operation not found in organization and plant")
            frontier = {command.trigger_operation_id}
        else:
            if command.project_id not in set(project_by_operation.values()):
                raise EntityNotFound("project not found in organization and plant")
            frontier = {op for op, project in project_by_operation.items()
                        if project == command.project_id}
        edges = self.conn.execute(text("""
            SELECT predecessor_operation_id,successor_operation_id
              FROM production.operation_precedences
             WHERE organization_id=:org AND active
        """), {"org": command.organization_id}).all()

        def add_successors(values):
            changed = True
            while changed:
                changed = False
                for predecessor, successor in edges:
                    if predecessor in values and successor in project_by_operation and successor not in values:
                        values.add(successor)
                        changed = True

        add_successors(frontier)
        allocations = self.conn.execute(text("""
            SELECT DISTINCT opr.required_operation_id,ro.project_id,
                   h.employee_id,r.physical_resource_id
              FROM planning.operation_plan_results opr
              JOIN production.required_operations ro
                ON ro.organization_id=opr.organization_id AND ro.id=opr.required_operation_id
              LEFT JOIN planning.phase_plan_results p
                ON p.organization_id=opr.organization_id AND p.operation_plan_result_id=opr.id
              LEFT JOIN planning.planned_phase_assignments a
                ON a.organization_id=p.organization_id AND a.phase_plan_result_id=p.id
              LEFT JOIN planning.assignment_segments s
                ON s.organization_id=a.organization_id AND s.planned_phase_assignment_id=a.id
               AND upper(s.time_range)>:cutoff
              LEFT JOIN planning.human_segment_assignments h
                ON h.organization_id=s.organization_id AND h.assignment_segment_id=s.id
              LEFT JOIN planning.physical_resource_reservations r
                ON r.organization_id=s.organization_id AND r.assignment_segment_id=s.id
             WHERE opr.organization_id=:org AND opr.schedule_solution_id=:solution
        """), {"org": command.organization_id, "solution": baseline_solution_id,
                 "cutoff": command.cutoff_at}).mappings().all()
        changed = True
        while changed:
            changed = False
            employees = {row["employee_id"] for row in allocations
                         if row["required_operation_id"] in frontier and row["employee_id"]}
            resources = {row["physical_resource_id"] for row in allocations
                         if row["required_operation_id"] in frontier and row["physical_resource_id"]}
            for row in allocations:
                operation = row["required_operation_id"]
                if operation not in project_by_operation or operation in frontier:
                    continue
                if row["employee_id"] in employees or row["physical_resource_id"] in resources:
                    frontier.add(operation)
                    changed = True
            if changed:
                add_successors(frontier)
        projects = {project_by_operation[operation] for operation in frontier}
        return (tuple(sorted(projects, key=str)), tuple(sorted(frontier, key=str)))

    def _compare_replan(self, command, baseline_solution_id, solution_id,
                        frontier_projects, frontier_operations):
        rows = self.conn.execute(text("""
            SELECT 'old' AS side,opr.required_operation_id,ro.project_id,opr.result_status,
                   opr.planned_start_at,opr.planned_end_at,opr.remaining_work_minutes
              FROM planning.operation_plan_results opr
              JOIN production.required_operations ro
                ON ro.organization_id=opr.organization_id AND ro.id=opr.required_operation_id
             WHERE opr.organization_id=:org AND opr.schedule_solution_id=:old
               AND opr.required_operation_id=ANY(:operations)
            UNION ALL
            SELECT 'new',opr.required_operation_id,ro.project_id,opr.result_status,
                   opr.planned_start_at,opr.planned_end_at,opr.remaining_work_minutes
              FROM planning.operation_plan_results opr
              JOIN production.required_operations ro
                ON ro.organization_id=opr.organization_id AND ro.id=opr.required_operation_id
             WHERE opr.organization_id=:org AND opr.schedule_solution_id=:new
               AND opr.required_operation_id=ANY(:operations)
        """), {"org": command.organization_id, "old": baseline_solution_id,
                 "new": solution_id, "operations": list(frontier_operations)}).mappings().all()
        values = defaultdict(dict)
        for row in rows:
            values[row["required_operation_id"]][row["side"]] = row
        operations = []
        for operation_id in frontier_operations:
            pair = values[operation_id]
            old, new = pair.get("old"), pair.get("new")
            old_end = old["planned_end_at"] if old else None
            new_end = new["planned_end_at"] if new else None
            delta = (int((new_end-old_end).total_seconds() // 60)
                     if old_end and new_end else None)
            old_value = self._plan_value(old)
            new_value = self._plan_value(new)
            changed = old_value != new_value
            impact_kind = ("newly_planned" if old is None else "removed_from_future"
                           if new is None else "delayed" if delta and delta > 0
                           else "advanced" if delta and delta < 0 else "changed")
            project_id = ((new or old)["project_id"] if (new or old)
                          else self.conn.scalar(text("""
                              SELECT project_id FROM production.required_operations
                               WHERE organization_id=:org AND id=:operation
                          """), {"org": command.organization_id, "operation": operation_id}))
            operations.append({
                "operation_id": str(operation_id), "project_id": str(project_id),
                "changed": changed, "impact_kind": impact_kind,
                "delta_minutes": delta, "old": old_value, "new": new_value,
                "reason": {"command": command.command_name,
                           "cutoff_at": command.cutoff_at,
                           "trigger_operation_id": command.trigger_operation_id,
                           "trigger_project_id": command.project_id},
            })
        communicated = dict(self.conn.execute(text("""
            SELECT DISTINCT ON (project_id) project_id,communicated_date
              FROM portal.communicated_dates
             WHERE organization_id=:org AND project_id=ANY(:projects)
             ORDER BY project_id,communicated_at DESC,id DESC
        """), {"org": command.organization_id,
                 "projects": list(frontier_projects)}).all()) if frontier_projects else {}
        proposed_finish = defaultdict(lambda: None)
        for item in operations:
            end = item["new"].get("end") if item["new"] else None
            if end:
                value = (end if isinstance(end, datetime)
                         else datetime.fromisoformat(end.replace("Z", "+00:00")))
                project = UUID(item["project_id"])
                proposed_finish[project] = max(proposed_finish[project] or value, value)
        alerts = [{"project_id": str(project), "communicated_date": date_value,
                   "proposed_finish": proposed_finish.get(project),
                   "reason": "PROPOSED_DATE_AFTER_COMMUNICATED_DATE"}
                  for project, date_value in communicated.items()
                  if proposed_finish.get(project)
                  and proposed_finish[project].date() > date_value]
        changed = sum(item["changed"] for item in operations)
        return {
            "base_plan_version_id": str(command.base_plan_version_id),
            "baseline_solution_id": str(baseline_solution_id),
            "replan_cutoff": command.cutoff_at,
            "frontier_project_ids": [str(x) for x in frontier_projects],
            "frontier_operation_ids": [str(x) for x in frontier_operations],
            "operations": operations, "changed_operations": changed,
            "customer_date_alerts": len(alerts), "customer_date_alert_items": alerts,
            "impact_summary": {
                "changed_operations": changed,
                "unchanged_operations": len(operations) - changed,
                "customer_date_alerts": len(alerts),
                "current_plan_modified": False,
            },
        }

    @staticmethod
    def _plan_value(row):
        if row is None:
            return None
        return {
            "status": row["result_status"],
            "start": row["planned_start_at"], "end": row["planned_end_at"],
            "remaining_work_minutes": row["remaining_work_minutes"],
        }

    def _apply_replanning_state(self, command, phases):
        """Freeze history at cutoff and replace only running work with its latest remainder."""
        replan = command.parameters["replan"]
        cutoff = datetime.fromisoformat(replan["cutoff_at"])
        baseline = UUID(replan["base_solution_id"])
        operation_ids = [phase.operation_id for phase in phases]
        executions = self.conn.execute(text("""
            SELECT DISTINCT ON (oe.required_operation_id)
                   oe.required_operation_id,oe.id,oe.status,r.id AS revision_id,
                   r.remaining_labor_minutes
              FROM execution.operation_executions oe
              LEFT JOIN execution.remaining_estimate_revisions r
                ON r.organization_id=oe.organization_id
               AND r.operation_execution_id=oe.id AND r.superseded_at IS NULL
             WHERE oe.organization_id=:org
               AND oe.required_operation_id=ANY(:operations)
             ORDER BY oe.required_operation_id,oe.created_at DESC,oe.id DESC
        """), {"org": command.organization_id,
                 "operations": operation_ids}).mappings().all() if operation_ids else []
        by_operation = {row["required_operation_id"]: row for row in executions}
        anchors = dict(self.conn.execute(text("""
            SELECT p.required_operation_phase_id,min(lower(s.time_range))
              FROM planning.phase_plan_results p
              JOIN planning.planned_phase_assignments a
                ON a.organization_id=p.organization_id AND a.phase_plan_result_id=p.id
              JOIN planning.assignment_segments s
                ON s.organization_id=a.organization_id AND s.planned_phase_assignment_id=a.id
             WHERE p.organization_id=:org AND p.schedule_solution_id=:solution
             GROUP BY p.required_operation_phase_id
        """), {"org": command.organization_id, "solution": baseline}).all())
        result = []
        revision_by_phase = {}
        seen_running = set()
        for phase in phases:
            execution = by_operation.get(phase.operation_id)
            if execution and execution["status"] in {"completed", "cancelled"}:
                continue
            minutes = phase.original_minutes
            labor = phase.labor
            earliest = max(cutoff, phase.earliest_start or cutoff, anchors.get(phase.id) or cutoff)
            if execution and execution["status"] in {"running", "paused"}:
                if phase.operation_id in seen_running:
                    minutes = 0
                else:
                    seen_running.add(phase.operation_id)
                    minutes = int(execution["remaining_labor_minutes"] or 0)
                    if len(labor) == 1:
                        labor = (replace(labor[0], work_minutes=minutes),)
                    if execution["revision_id"]:
                        revision_by_phase[phase.id] = execution["revision_id"]
                earliest = cutoff
            result.append(replace(
                phase, original_minutes=minutes, labor=labor, earliest_start=earliest
            ))
        return tuple(result), revision_by_phase

    def _load_gates(self, org, operations, phases):
        phase_ids_by_op = defaultdict(list)
        for phase in phases:
            phase_ids_by_op[phase["required_operation_id"]].append((phase["sequence_no"], phase["id"]))
        operation_ids = [row["id"] for row in operations]
        rows = self.conn.execute(text("SELECT * FROM production.operation_gates WHERE organization_id=:org AND required_operation_id=ANY(:operations) ORDER BY id"), {"org": org, "operations": operation_ids}).mappings().all() if operation_ids else []
        material_ids = [row["material_requirement_id"] for row in rows if row["material_requirement_id"]]
        materials = {}
        if material_ids:
            required = dict(self.conn.execute(text("SELECT id,required_quantity FROM production.material_requirements WHERE organization_id=:org AND id=ANY(:ids)"), {"org": org, "ids": material_ids}).all())
            allocations = self.conn.execute(text("""
                SELECT a.material_requirement_id,a.quantity*a.movement_sign AS quantity,d.delivered_at
                FROM production.material_allocations a
                JOIN production.supplier_delivery_lines dl ON dl.organization_id=a.organization_id AND dl.id=a.supplier_delivery_line_id
                JOIN production.supplier_deliveries d ON d.organization_id=dl.organization_id AND d.id=dl.supplier_delivery_id
                WHERE a.organization_id=:org AND a.material_requirement_id=ANY(:ids)
                  AND NOT EXISTS(SELECT 1 FROM production.material_allocations successor WHERE successor.organization_id=a.organization_id AND successor.supersedes_id=a.id)
                ORDER BY d.delivered_at,a.id
            """), {"org": org, "ids": material_ids}).mappings().all()
            grouped = defaultdict(list)
            for item in allocations: grouped[item["material_requirement_id"]].append(item)
            for material_id in material_ids:
                total, release = Decimal(0), None
                for item in grouped[material_id]:
                    total += item["quantity"]
                    if total >= required[material_id]:
                        release = item["delivered_at"]; break
                materials[material_id] = release
        drawing_ids = [row["drawing_package_id"] for row in rows if row["drawing_package_id"]]
        drawings = dict(self.conn.execute(text("""
            SELECT drawing_package_id,max(released_at) FROM production.drawing_releases
            WHERE organization_id=:org AND drawing_package_id=ANY(:ids) AND status='released'
              AND NOT EXISTS(SELECT 1 FROM production.drawing_releases successor WHERE successor.organization_id=production.drawing_releases.organization_id AND successor.supersedes_id=production.drawing_releases.id)
            GROUP BY drawing_package_id
        """), {"org": org, "ids": drawing_ids}).all()) if drawing_ids else {}
        lot_ids = [row["hardware_project_lot_id"] for row in rows if row["hardware_project_lot_id"]]
        lots = {row["id"]: row for row in self.conn.execute(text("SELECT id,hardware_status,hardware_available_at FROM core.project_lots WHERE organization_id=:org AND id=ANY(:ids)"), {"org": org, "ids": lot_ids}).mappings().all()} if lot_ids else {}
        milestone_ids = [row["milestone_definition_id"] for row in rows if row["milestone_definition_id"]]
        milestones = {}
        if milestone_ids:
            milestone_rows = self.conn.execute(text("SELECT project_id,milestone_definition_id,min(occurred_at) AS occurred_at FROM core.project_milestones WHERE organization_id=:org AND milestone_definition_id=ANY(:ids) GROUP BY project_id,milestone_definition_id"), {"org": org, "ids": milestone_ids}).mappings().all()
            milestones = {(row["project_id"], row["milestone_definition_id"]): row["occurred_at"] for row in milestone_rows}
        project_by_op = {row["id"]: row["project_id"] for row in operations}
        result = defaultdict(list)
        for row in rows:
            release, blocker = None, None
            if row["available_at"] is not None: release = row["available_at"]
            elif row["material_requirement_id"] is not None:
                release = materials.get(row["material_requirement_id"]); blocker = None if release else "MATERIAL_NOT_AVAILABLE"
            elif row["drawing_package_id"] is not None:
                release = drawings.get(row["drawing_package_id"]); blocker = None if release else "DRAWINGS_NOT_AVAILABLE"
            elif row["hardware_project_lot_id"] is not None:
                lot = lots.get(row["hardware_project_lot_id"])
                if lot and lot["hardware_status"] in {"ready", "not_required"}: release = lot["hardware_available_at"] or datetime.min.replace(tzinfo=timezone.utc)
                elif lot and lot["hardware_available_at"]: release = lot["hardware_available_at"]
                else: blocker = "HARDWARE_NOT_AVAILABLE"
            else:
                release = milestones.get((project_by_op[row["required_operation_id"]], row["milestone_definition_id"]))
                blocker = None if release else "MILESTONE_NOT_AVAILABLE"
            target_phase = row["required_operation_phase_id"]
            if target_phase is not None:
                targets = [target_phase]
            else:
                ordered = sorted(phase_ids_by_op[row["required_operation_id"]])
                targets = [ordered[0][1] if row["timing"] == "before_start" else ordered[-1][1]] if ordered else []
            for phase_id in targets:
                result[phase_id].append(GateData(row["gate_type"], release, blocker))
        return result

    def _load_capacity(self, command, scenario_id):
        employee_rows = self.conn.execute(text("SELECT id,code,base_calendar_id FROM capacity.employees WHERE organization_id=:org AND plant_id=:plant AND status='active' ORDER BY code"), {"org": command.organization_id, "plant": command.plant_id}).mappings().all()
        end_date = (command.horizon_end - timedelta(microseconds=1)).date()
        skill_rows = self.conn.execute(text("SELECT employee_id,skill_id FROM capacity.employee_skills WHERE organization_id=:org AND enabled AND employee_id=ANY(:ids) AND valid_during @> CAST(:start AS date) AND valid_during @> CAST(:finish AS date) ORDER BY employee_id,skill_id"), {"org": command.organization_id, "ids": [r["id"] for r in employee_rows], "start": command.horizon_start.date(), "finish": end_date}).all() if employee_rows else []
        skills = defaultdict(set)
        for employee, skill in skill_rows: skills[employee].add(skill)
        employees = tuple(EmployeeData(row["id"], row["code"], row["base_calendar_id"], frozenset(skills[row["id"]])) for row in employee_rows)
        resource_rows = self.conn.execute(text("SELECT id,code,base_calendar_id,resource_type_id,work_center_id,scheduling_mode,capacity_units FROM capacity.physical_resources WHERE organization_id=:org AND plant_id=:plant AND status='active' ORDER BY code"), {"org": command.organization_id, "plant": command.plant_id}).mappings().all()
        membership = self.conn.execute(text("SELECT physical_resource_id,group_id FROM capacity.physical_resource_group_members WHERE organization_id=:org AND physical_resource_id=ANY(:ids) AND valid_during @> CAST(:start AS date) AND valid_during @> CAST(:finish AS date) ORDER BY physical_resource_id,group_id"), {"org": command.organization_id, "ids": [r["id"] for r in resource_rows], "start": command.horizon_start.date(), "finish": end_date}).all() if resource_rows else []
        groups = defaultdict(set)
        for resource, group in membership: groups[resource].add(group)
        resources = tuple(ResourceData(row["id"], row["code"], row["base_calendar_id"], row["resource_type_id"], row["work_center_id"], frozenset(groups[row["id"]]), row["scheduling_mode"], float(row["capacity_units"])) for row in resource_rows)
        calendar_ids = {self.conn.scalar(text("SELECT base_calendar_id FROM core.plants WHERE organization_id=:org AND id=:plant"), {"org": command.organization_id, "plant": command.plant_id}), *(row["base_calendar_id"] for row in employee_rows), *(row["base_calendar_id"] for row in resource_rows)}
        calendar_rows = self.conn.execute(text("SELECT id,timezone FROM capacity.calendars WHERE organization_id=:org AND id=ANY(:ids) AND status='active'"), {"org": command.organization_id, "ids": list(calendar_ids)}).mappings().all()
        interval_rows = self.conn.execute(text("SELECT calendar_id,weekday,local_start,local_end,valid_during FROM capacity.calendar_working_intervals WHERE organization_id=:org AND calendar_id=ANY(:ids) ORDER BY calendar_id,weekday,local_start"), {"org": command.organization_id, "ids": list(calendar_ids)}).mappings().all()
        exception_rows = self.conn.execute(text("SELECT calendar_id,exception_date,effect,lower(time_range) AS start_at,upper(time_range) AS end_at FROM capacity.calendar_exceptions WHERE organization_id=:org AND calendar_id=ANY(:ids) ORDER BY calendar_id,exception_date"), {"org": command.organization_id, "ids": list(calendar_ids)}).mappings().all()
        intervals, exceptions = defaultdict(list), defaultdict(list)
        for row in interval_rows:
            range_value = row["valid_during"]
            intervals[row["calendar_id"]].append(CalendarInterval(row["weekday"], row["local_start"], row["local_end"], range_value.lower, range_value.upper))
        for row in exception_rows:
            exceptions[row["calendar_id"]].append(CalendarException(row["exception_date"], row["effect"], row["start_at"], row["end_at"]))
        calendars = {row["id"]: CalendarData(row["id"], row["timezone"], tuple(intervals[row["id"]]), tuple(exceptions[row["id"]])) for row in calendar_rows}
        if calendar_ids != set(calendars):
            raise InvalidSchedulingInput("an effective calendar is missing or inactive")
        unavailable_rows = self.conn.execute(text("""
            SELECT COALESCE(employee_id,physical_resource_id) AS owner,lower(time_range) AS start_at,upper(time_range) AS end_at
            FROM capacity.resource_unavailabilities u WHERE organization_id=:org
              AND time_range && tstzrange(:start,:finish,'[)')
              AND NOT EXISTS(SELECT 1 FROM capacity.resource_unavailabilities successor WHERE successor.organization_id=u.organization_id AND successor.supersedes_id=u.id)
            UNION ALL
            SELECT COALESCE(aru.employee_id,aru.physical_resource_id),lower(aru.time_range),upper(aru.time_range)
            FROM execution.actual_resource_usages aru
            LEFT JOIN capacity.physical_resources pr
              ON pr.organization_id=aru.organization_id AND pr.id=aru.physical_resource_id
            WHERE aru.organization_id=:org
              AND aru.time_range && tstzrange(:start,:finish,'[)')
              AND (aru.employee_id IS NOT NULL OR pr.scheduling_mode='exclusive')
              AND NOT EXISTS(SELECT 1 FROM execution.actual_resource_usages successor WHERE successor.organization_id=aru.organization_id AND successor.supersedes_id=aru.id)
        """), {"org": command.organization_id, "start": command.horizon_start, "finish": command.horizon_end}).mappings().all()
        unavailability = defaultdict(list)
        for row in unavailable_rows:
            if row["owner"]: unavailability[row["owner"]].append(TimeWindow(row["start_at"], row["end_at"]))
        occupation_rows = self.conn.execute(text("SELECT physical_resource_id,lower(time_range) AS start_at,upper(time_range) AS end_at FROM planning.physical_occupations WHERE organization_id=:org AND source_kind='actual' AND is_effective AND time_range && tstzrange(:start,:finish,'[)')"), {"org": command.organization_id, "start": command.horizon_start, "finish": command.horizon_end}).mappings().all()
        occupations = defaultdict(list)
        for row in occupation_rows: occupations[row["physical_resource_id"]].append(TimeWindow(row["start_at"], row["end_at"]))
        actual_capacity_rows = self.conn.execute(text("""
            SELECT aru.physical_resource_id,lower(aru.time_range) AS start_at,
                   upper(aru.time_range) AS end_at,
                   COALESCE(aru.capacity_units,pr.capacity_units) AS capacity_units
            FROM execution.actual_resource_usages aru
            JOIN capacity.physical_resources pr
              ON pr.organization_id=aru.organization_id AND pr.id=aru.physical_resource_id
            WHERE aru.organization_id=:org AND pr.plant_id=:plant
              AND pr.scheduling_mode='cumulative'
              AND aru.time_range && tstzrange(:start,:finish,'[)')
              AND NOT EXISTS(
                SELECT 1 FROM execution.actual_resource_usages successor
                WHERE successor.organization_id=aru.organization_id AND successor.supersedes_id=aru.id
              )
            ORDER BY aru.physical_resource_id,lower(aru.time_range),aru.id
        """), {"org": command.organization_id, "plant": command.plant_id,
                 "start": command.horizon_start, "finish": command.horizon_end}).mappings().all()
        actual_capacity = defaultdict(list)
        for row in actual_capacity_rows:
            actual_capacity[row["physical_resource_id"]].append(CapacityUsage(
                TimeWindow(row["start_at"], row["end_at"]), float(row["capacity_units"])
            ))
        overtime_rows = self.conn.execute(text("""
            SELECT id,lower(time_range) AS start_at,upper(time_range) AS end_at,project_id,employee_id,physical_resource_id,work_center_id,max_minutes
            FROM capacity.overtime_authorizations WHERE organization_id=:org AND plant_id=:plant AND revoked_at IS NULL
              AND time_range && tstzrange(:start,:finish,'[)') AND (scenario_id IS NULL OR scenario_id=:scenario)
            ORDER BY start_at,id
        """), {"org": command.organization_id, "plant": command.plant_id, "start": command.horizon_start, "finish": command.horizon_end, "scenario": scenario_id}).mappings().all()
        overtime = tuple(OvertimeData(row["id"], row["start_at"], row["end_at"], row["project_id"], row["employee_id"], row["physical_resource_id"], row["work_center_id"], row["max_minutes"]) for row in overtime_rows)
        return (employees, resources, calendars,
                {k: tuple(v) for k,v in unavailability.items()},
                {k: tuple(v) for k,v in occupations.items()},
                {k: tuple(v) for k,v in actual_capacity.items()}, overtime)

    def _persist_outcomes(self, org, solution_id, value, output):
        phase_by_id = {phase.id: phase for phase in value.phases}
        grouped = defaultdict(list)
        for outcome in output.outcomes: grouped[phase_by_id[outcome.phase_id].operation_id].append(outcome)
        for operation_id, outcomes in grouped.items():
            status = "blocked" if any(x.status == "blocked" for x in outcomes) else "out_of_horizon" if any(x.status == "out_of_horizon" for x in outcomes) else "planned"
            segments = [segment for outcome in outcomes for segment in outcome.segments]
            operation_result_id = uuid4()
            self.conn.execute(text("""
                INSERT INTO planning.operation_plan_results
                  (id,organization_id,schedule_solution_id,required_operation_id,result_status,
                   planned_start_at,planned_end_at,remaining_work_minutes,explanation)
                VALUES (:id,:org,:solution,:operation,:status,:start,:finish,:remaining,CAST(:explanation AS jsonb))
            """), {"id": operation_result_id, "org": org, "solution": solution_id, "operation": operation_id,
                    "status": status, "start": min((x.start for x in segments), default=None),
                    "finish": max((x.end for x in segments), default=None),
                    "remaining": sum(x.remaining_work_minutes for x in outcomes),
                    "explanation": _json({"blockers": sorted({b for x in outcomes for b in x.blockers})})})
            for outcome in outcomes:
                phase = phase_by_id[outcome.phase_id]
                phase_result_id = uuid4()
                self.conn.execute(text("""
                    INSERT INTO planning.phase_plan_results
                      (id,organization_id,operation_plan_result_id,schedule_solution_id,
                       required_operation_phase_id,result_status,remaining_estimate_revision_id,planned_work_minutes,
                       remaining_work_minutes,explanation)
                    VALUES (:id,:org,:operation_result,:solution,:phase,:status,:remaining_revision,:planned,:remaining,CAST(:explanation AS jsonb))
                """), {"id": phase_result_id, "org": org, "operation_result": operation_result_id,
                        "solution": solution_id, "phase": outcome.phase_id, "status": outcome.status,
                        "remaining_revision": getattr(self, "_remaining_revision_by_phase", {}).get(outcome.phase_id),
                        "planned": outcome.planned_work_minutes, "remaining": outcome.remaining_work_minutes,
                        "explanation": _json({
                            "ready_at": outcome.ready_at,
                            "why_not_earlier": list(outcome.blockers),
                            "assigned_employee_codes": sorted({
                                next(item.code for item in value.employees if item.id == employee_id)
                                for segment in outcome.segments for employee_id in segment.employee_ids
                            }),
                            "assigned_resource_codes": sorted({
                                next(item.code for item in value.resources if item.id == resource_id)
                                for segment in outcome.segments for resource_id in segment.resource_ids
                            }),
                        })})
                if not outcome.segments: continue
                assignment_id = uuid4()
                self.conn.execute(text("""
                    INSERT INTO planning.planned_phase_assignments
                      (id,organization_id,phase_plan_result_id,schedule_solution_id,assignment_kind,
                       planned_start_at,planned_end_at,work_minutes)
                    VALUES (:id,:org,:phase_result,:solution,'operation',:start,:finish,:minutes)
                """), {"id": assignment_id, "org": org, "phase_result": phase_result_id,
                        "solution": solution_id, "start": outcome.segments[0].start,
                        "finish": outcome.segments[-1].end,
                        "minutes": sum(segment.work_minutes for segment in outcome.segments)})
                for number, segment in enumerate(outcome.segments, 1):
                    segment_id = uuid4()
                    normal = segment.work_minutes - segment.overtime_minutes
                    self.conn.execute(text("""
                        INSERT INTO planning.assignment_segments
                          (id,organization_id,planned_phase_assignment_id,schedule_solution_id,segment_no,
                           time_range,normal_minutes,overtime_minutes,work_minutes)
                        VALUES (:id,:org,:assignment,:solution,:number,tstzrange(:start,:finish,'[)'),:normal,:overtime,:work)
                    """), {"id": segment_id, "org": org, "assignment": assignment_id,
                            "solution": solution_id, "number": number, "start": segment.start, "finish": segment.end,
                            "normal": normal, "overtime": segment.overtime_minutes, "work": segment.work_minutes})
                    employee_ot = dict(segment.employee_overtime)
                    for employee_id in segment.employee_ids:
                        overtime_id = employee_ot.get(employee_id)
                        employee_normal = segment.work_minutes if overtime_id is None else 0
                        self.conn.execute(text("""
                            INSERT INTO planning.human_segment_assignments
                              (organization_id,assignment_segment_id,schedule_solution_id,employee_id,time_range,
                               normal_minutes,overtime_minutes,work_minutes,overtime_authorization_id)
                            VALUES (:org,:segment,:solution,:employee,tstzrange(:start,:finish,'[)'),:normal,:overtime,:work,:authorization)
                        """), {"org": org, "segment": segment_id, "solution": solution_id,
                                "employee": employee_id, "start": segment.start, "finish": segment.end,
                                "normal": employee_normal, "overtime": segment.work_minutes-employee_normal,
                                "work": segment.work_minutes, "authorization": overtime_id})
                    resource_ot = dict(segment.resource_overtime)
                    resource_capacity = dict(segment.resource_capacity_units)
                    for resource_id in segment.resource_ids:
                        resource = next(item for item in value.resources if item.id == resource_id)
                        usage_mode = "occupation" if resource_id in segment.occupation_resource_ids else "active_use"
                        self.conn.execute(text("""
                            INSERT INTO planning.physical_resource_reservations
                              (organization_id,assignment_segment_id,schedule_solution_id,physical_resource_id,
                               time_range,capacity_units,exclusive_guard,usage_mode,overtime_authorization_id)
                            VALUES (:org,:segment,:solution,:resource,tstzrange(:start,:finish,'[)'),:capacity,:exclusive,:mode,:authorization)
                        """), {"org": org, "segment": segment_id, "solution": solution_id,
                                "resource": resource_id, "start": segment.start, "finish": segment.end,
                                "capacity": resource_capacity[resource_id],
                                "exclusive": resource.scheduling_mode == "exclusive", "mode": usage_mode,
                                "authorization": resource_ot.get(resource_id)})
                for resource_id in outcome.segments[0].occupation_resource_ids:
                    self.conn.execute(text("""
                        INSERT INTO planning.physical_occupations
                          (organization_id,schedule_solution_id,project_lot_id,required_operation_phase_id,
                           physical_resource_id,source_kind,time_range,planned_release_at)
                        VALUES (:org,:solution,:lot,:phase,:resource,'planned',tstzrange(:start,:finish,'[)'),:finish)
                    """), {"org": org, "solution": solution_id, "lot": phase.lot_id,
                            "phase": phase.id, "resource": resource_id,
                            "start": outcome.segments[0].start, "finish": outcome.segments[-1].end})

    @staticmethod
    def _resource_matches(value, resource_id, need):
        resource = next(item for item in value.resources if item.id == resource_id)
        return ((need.resource_type_id is not None and resource.resource_type_id == need.resource_type_id)
                or (need.resource_group_id is not None and need.resource_group_id in resource.group_ids)
                or (need.work_center_id is not None and need.work_center_id == resource.work_center_id))


class PostgresSchedulingUnitOfWorkFactory:
    def __init__(self, engine: Engine, *, failpoint: str | None = None) -> None:
        self.engine, self.failpoint = engine, failpoint

    def __call__(self):
        return PostgresSchedulingUnitOfWork(self.engine, failpoint=self.failpoint)


def _jsonable(value):
    if is_dataclass(value): return _jsonable(asdict(value))
    if isinstance(value, dict): return {str(k): _jsonable(v) for k,v in sorted(value.items(), key=lambda x: str(x[0]))}
    if isinstance(value, (set, frozenset)):
        return [_jsonable(v) for v in sorted(value, key=str)]
    if isinstance(value, (tuple, list)): return [_jsonable(v) for v in value]
    if isinstance(value, UUID): return str(value)
    if isinstance(value, datetime): return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, date): return value.isoformat()
    if isinstance(value, time): return value.isoformat()
    if isinstance(value, Decimal): return format(value.normalize(), "f")
    return value


def _json(value):
    return json.dumps(_jsonable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _semantic_output(output, value):
    phase = {item.id: item for item in value.phases}
    employees = {item.id: item.code for item in value.employees}
    resources = {item.id: item.code for item in value.resources}
    return {"scheduler_version": GreedyFiniteCapacityScheduler.version, "complete": output.complete,
            "phases": [{"project": phase[x.phase_id].project_code, "lot": phase[x.phase_id].lot_code,
                "operation": phase[x.phase_id].operation_code, "phase": phase[x.phase_id].code,
                "status": x.status, "remaining": x.remaining_work_minutes, "blockers": list(x.blockers),
                "segments": [{"start": s.start, "end": s.end, "work_minutes": s.work_minutes,
                    "employees": [employees[e] for e in s.employee_ids],
                    "resources": [resources[r] for r in s.resource_ids],
                    "resource_capacity_units": [
                        {"resource": resources[r], "capacity_units": units}
                        for r, units in s.resource_capacity_units
                    ]} for s in x.segments]}
                for x in output.outcomes]}


def _counts(output):
    return {"planned_phases": sum(x.status == "planned" for x in output.outcomes),
            "blocked_phases": sum(x.status == "blocked" for x in output.outcomes),
            "out_of_horizon_phases": sum(x.status == "out_of_horizon" for x in output.outcomes)}


def _all_blockers(output):
    return {blocker for outcome in output.outcomes for blocker in outcome.blockers}
