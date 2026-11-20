from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, text

from production_besten.domain.errors import (
    EntityNotFound,
    InvalidEstimate,
    InvalidExecutionState,
    RevisionConflict,
)
from production_besten.domain.remaining_estimate import (
    RemainingDimension,
    RemainingEstimateResult,
    UpdateRemainingEstimate,
)


class PostgresRemainingEstimateUnitOfWork:
    """One command per SQLAlchemy transaction; rollback is automatic on errors."""

    def __init__(self, engine: Engine, *, failpoint: str | None = None) -> None:
        self._engine = engine
        self._failpoint = failpoint
        self._connection: Connection | None = None
        self._transaction: Any = None

    def __enter__(self) -> "PostgresRemainingEstimateUnitOfWork":
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
    def connection(self) -> Connection:
        if self._connection is None:
            raise RuntimeError("unit of work is not active")
        return self._connection

    def update_remaining_estimate(
        self, command: UpdateRemainingEstimate
    ) -> RemainingEstimateResult:
        command.validate()
        conn = self.connection
        now = datetime.now(timezone.utc)

        execution = conn.execute(
            text(
                """
                SELECT oe.id, oe.status, oe.required_operation_id,
                       oe.original_estimate_snapshot,
                       ro.project_id, p.plant_id, pl.current_plan_version_id
                  FROM execution.operation_executions oe
                  JOIN production.required_operations ro
                    ON ro.organization_id=oe.organization_id
                   AND ro.id=oe.required_operation_id
                  JOIN core.projects p
                    ON p.organization_id=ro.organization_id
                   AND p.id=ro.project_id
                  JOIN core.plants pl
                    ON pl.organization_id=p.organization_id
                   AND pl.id=p.plant_id
                 WHERE oe.organization_id=:organization_id
                   AND oe.id=:execution_id
                 FOR UPDATE OF oe
                """
            ),
            {
                "organization_id": command.organization_id,
                "execution_id": command.operation_execution_id,
            },
        ).mappings().one_or_none()
        if execution is None:
            raise EntityNotFound("operation execution not found in organization")
        if execution["status"] not in {"running", "paused"}:
            raise InvalidExecutionState("remaining estimate requires running or paused execution")

        phase_belongs = conn.scalar(
            text(
                """
                SELECT EXISTS (
                    SELECT 1 FROM production.required_operation_phases ph
                     WHERE ph.organization_id=:organization_id
                       AND ph.required_operation_id=:operation_id
                       AND ph.id = ANY(:phase_ids)
                    GROUP BY ph.required_operation_id
                    HAVING count(*)=:phase_count
                )
                """
            ),
            {
                "organization_id": command.organization_id,
                "operation_id": execution["required_operation_id"],
                "phase_ids": list({resource.phase_id for resource in command.resources}),
                "phase_count": len({resource.phase_id for resource in command.resources}),
            },
        )
        if not phase_belongs:
            raise InvalidEstimate("a resource dimension references a phase outside the execution")

        for resource in command.resources:
            if resource.dimension is RemainingDimension.LABOR_WORK and resource.skill_id is None:
                generic_team = conn.scalar(text("""
                    SELECT ph.required_people FROM production.required_operation_phases ph
                    WHERE ph.organization_id=:org AND ph.id=:phase
                      AND NOT EXISTS (
                        SELECT 1 FROM production.operation_labor_requirements r
                        WHERE r.organization_id=ph.organization_id
                          AND r.required_operation_phase_id=ph.id AND r.is_mandatory)
                """), {"org": command.organization_id, "phase": resource.phase_id})
                if not generic_team or resource.min_people != generic_team or resource.max_people != generic_team:
                    raise InvalidEstimate("generic labor must match the phase's required people without mandatory skills")

        previous = conn.execute(
            text(
                """
                SELECT id, revision_no
                  FROM execution.remaining_estimate_revisions
                 WHERE organization_id=:organization_id
                   AND operation_execution_id=:execution_id
                   AND superseded_at IS NULL
                 FOR UPDATE
                """
            ),
            {
                "organization_id": command.organization_id,
                "execution_id": command.operation_execution_id,
            },
        ).mappings().one_or_none()
        if previous is None:
            raise EntityNotFound("current remaining estimate revision not found")
        if previous["revision_no"] != command.expected_revision_no:
            raise RevisionConflict(
                f"expected revision {command.expected_revision_no}, current is {previous['revision_no']}"
            )

        executed_labor_minutes = int(
            conn.scalar(
                text(
                    """
                    SELECT COALESCE(sum(aru.work_minutes),0)
                      FROM execution.actual_resource_usages aru
                      JOIN execution.execution_segments es
                        ON es.organization_id=aru.organization_id
                       AND es.id=aru.execution_segment_id
                     WHERE aru.organization_id=:organization_id
                       AND es.operation_execution_id=:execution_id
                       AND es.segment_kind='work'
                       AND aru.employee_id IS NOT NULL
                       AND upper(aru.time_range) <= :cutoff_at
                       AND NOT EXISTS (
                           SELECT 1 FROM execution.execution_segments successor
                            WHERE successor.organization_id=es.organization_id
                              AND successor.supersedes_id=es.id
                       )
                       AND NOT EXISTS (
                           SELECT 1 FROM execution.actual_resource_usages successor_usage
                            WHERE successor_usage.organization_id=aru.organization_id
                              AND successor_usage.supersedes_id=aru.id
                       )
                    """
                ),
                {
                    "organization_id": command.organization_id,
                    "execution_id": command.operation_execution_id,
                    "cutoff_at": command.cutoff_at,
                },
            )
            or 0
        )
        snapshot = execution["original_estimate_snapshot"]
        original_labor_minutes = snapshot.get("labor_minutes")
        if not isinstance(original_labor_minutes, int) or original_labor_minutes < 0:
            raise InvalidEstimate("original snapshot requires non-negative labor_minutes")

        state_head = conn.execute(
            text(
                """
                SELECT current_revision_id, current_revision_no
                  FROM planning.planning_state_heads
                 WHERE organization_id=:organization_id AND plant_id=:plant_id
                 FOR UPDATE
                """
            ),
            {
                "organization_id": command.organization_id,
                "plant_id": execution["plant_id"],
            },
        ).mappings().one_or_none()
        if state_head is None:
            raise EntityNotFound("planning state head not found in organization")

        new_revision_id = uuid4()
        state_revision_id = uuid4()
        event_id = uuid4()
        transaction_key = uuid4()
        next_remaining_revision_no = previous["revision_no"] + 1
        next_state_revision_no = state_head["current_revision_no"] + 1
        updated_total = executed_labor_minutes + command.remaining_labor_minutes

        conn.execute(
            text(
                """
                INSERT INTO planning.planning_state_revisions
                  (id,organization_id,plant_id,revision_no,reason,transaction_key,
                   change_summary,created_by)
                VALUES
                  (:id,:organization_id,:plant_id,:revision_no,:reason,:transaction_key,
                   CAST(:change_summary AS jsonb),:created_by)
                """
            ),
            {
                "id": state_revision_id,
                "organization_id": command.organization_id,
                "plant_id": execution["plant_id"],
                "revision_no": next_state_revision_no,
                "reason": command.reason or "remaining estimate updated",
                "transaction_key": transaction_key,
                "change_summary": _json(
                    {
                        "command": "UPDATE_REMAINING_ESTIMATE",
                        "operation_execution_id": str(command.operation_execution_id),
                        "previous_revision_no": previous["revision_no"],
                        "new_revision_no": next_remaining_revision_no,
                    }
                ),
                "created_by": command.actor_id,
            },
        )
        conn.execute(
            text(
                """
                INSERT INTO planning.effective_events
                  (id,organization_id,plant_id,event_type_code,payload_schema_version,
                   occurred_at,effective_at,entity_type,entity_id,payload,cause,
                   planning_state_revision_id,source_system,external_reference,created_by)
                VALUES
                  (:id,:organization_id,:plant_id,'REMAINING_ESTIMATE_UPDATED',1,
                   :occurred_at,:effective_at,'operation_execution',:entity_id,
                   CAST(:payload AS jsonb),:cause,:state_revision_id,:source_system,
                   :external_reference,:created_by)
                """
            ),
            {
                "id": event_id,
                "organization_id": command.organization_id,
                "plant_id": execution["plant_id"],
                "occurred_at": now,
                "effective_at": command.cutoff_at,
                "entity_id": command.operation_execution_id,
                "payload": _json(
                    {
                        "remaining_estimate_revision_id": str(new_revision_id),
                        "executed_labor_minutes": executed_labor_minutes,
                        "remaining_labor_minutes": command.remaining_labor_minutes,
                        "updated_total_labor_minutes": updated_total,
                    }
                ),
                "cause": command.reason,
                "state_revision_id": state_revision_id,
                "source_system": command.source_system,
                "external_reference": f"remaining-estimate:{new_revision_id}",
                "created_by": command.actor_id,
            },
        )
        conn.execute(
            text(
                """
                UPDATE planning.planning_state_heads
                   SET current_revision_id=:state_revision_id,
                       current_revision_no=:revision_no,
                       row_version=row_version+1,
                       updated_at=:updated_at,
                       updated_by=:updated_by
                 WHERE organization_id=:organization_id AND plant_id=:plant_id
                """
            ),
            {
                "state_revision_id": state_revision_id,
                "revision_no": next_state_revision_no,
                "updated_at": now,
                "updated_by": command.actor_id,
                "organization_id": command.organization_id,
                "plant_id": execution["plant_id"],
            },
        )
        conn.execute(
            text(
                """
                UPDATE execution.remaining_estimate_revisions
                   SET superseded_at=:superseded_at, superseded_by_id=:superseded_by_id
                 WHERE organization_id=:organization_id AND id=:previous_id
                """
            ),
            {
                "superseded_at": now,
                "superseded_by_id": new_revision_id,
                "organization_id": command.organization_id,
                "previous_id": previous["id"],
            },
        )
        if self._failpoint == "after_supersede":
            raise RuntimeError("injected failure after superseding current revision")

        conn.execute(
            text(
                """
                INSERT INTO execution.remaining_estimate_revisions
                  (id,organization_id,operation_execution_id,revision_no,previous_revision_id,
                   cutoff_at,input_mode,raw_input,reason,effective_event_id,
                   planning_state_revision_id,executed_labor_minutes_at_cutoff,
                   remaining_labor_minutes,updated_total_labor_minutes,created_by)
                VALUES
                  (:id,:organization_id,:execution_id,:revision_no,:previous_revision_id,
                   :cutoff_at,:input_mode,CAST(:raw_input AS jsonb),:reason,:event_id,
                   :state_revision_id,:executed,:remaining,:updated_total,:created_by)
                """
            ),
            {
                "id": new_revision_id,
                "organization_id": command.organization_id,
                "execution_id": command.operation_execution_id,
                "revision_no": next_remaining_revision_no,
                "previous_revision_id": previous["id"],
                "cutoff_at": command.cutoff_at,
                "input_mode": command.input_mode,
                "raw_input": _json(command.raw_input or {"minutes": command.remaining_labor_minutes}),
                "reason": command.reason,
                "event_id": event_id,
                "state_revision_id": state_revision_id,
                "executed": executed_labor_minutes,
                "remaining": command.remaining_labor_minutes,
                "updated_total": updated_total,
                "created_by": command.actor_id,
            },
        )
        for resource in command.resources:
            conn.execute(
                text(
                    """
                    INSERT INTO execution.remaining_resource_estimates
                      (organization_id,remaining_estimate_revision_id,
                       required_operation_phase_id,dimension,skill_id,min_people,
                       max_people,physical_requirement_id,physical_resource_id,
                       remaining_minutes,expected_release_at,capacity_units,details)
                    VALUES
                      (:organization_id,:revision_id,:phase_id,:dimension,:skill_id,
                       :min_people,:max_people,:physical_requirement_id,
                       :physical_resource_id,:remaining_minutes,:expected_release_at,
                       :capacity_units,CAST(:details AS jsonb))
                    """
                ),
                {
                    "organization_id": command.organization_id,
                    "revision_id": new_revision_id,
                    "phase_id": resource.phase_id,
                    "dimension": resource.dimension.value,
                    "skill_id": resource.skill_id,
                    "min_people": resource.min_people,
                    "max_people": resource.max_people,
                    "physical_requirement_id": resource.physical_requirement_id,
                    "physical_resource_id": resource.physical_resource_id,
                    "remaining_minutes": resource.remaining_minutes,
                    "expected_release_at": resource.expected_release_at,
                    "capacity_units": resource.capacity_units,
                    "details": _json(resource.details or {}),
                },
            )
        conn.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))

        return RemainingEstimateResult(
            revision_id=new_revision_id,
            revision_no=next_remaining_revision_no,
            planning_state_revision_id=state_revision_id,
            planning_state_revision_no=next_state_revision_no,
            effective_event_id=event_id,
            original_labor_minutes=original_labor_minutes,
            executed_labor_minutes=executed_labor_minutes,
            remaining_labor_minutes=command.remaining_labor_minutes,
            updated_total_labor_minutes=updated_total,
            current_plan_version_id=execution["current_plan_version_id"],
        )


class PostgresUnitOfWorkFactory:
    def __init__(self, engine: Engine, *, failpoint: str | None = None) -> None:
        self._engine = engine
        self._failpoint = failpoint

    def __call__(self) -> PostgresRemainingEstimateUnitOfWork:
        return PostgresRemainingEstimateUnitOfWork(
            self._engine, failpoint=self._failpoint
        )


def _json(value: dict[str, Any]) -> str:
    import json

    return json.dumps(value, separators=(",", ":"), sort_keys=True)
