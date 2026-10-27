from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Iterable
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, text

from production_besten.domain.errors import (
    EntityNotFound,
    ExecutionAlreadyActive,
    ExecutionAlreadyCompleted,
    GateBlocked,
    IdempotencyConflict,
    InvalidExecutionState,
    InvalidEstimate,
    StructuralAvailabilityConflict,
)
from production_besten.domain.execution import (
    FinishOperation,
    FinishOperationResult,
    RegisterExecutionSegment,
    RegisterExecutionSegmentResult,
    StartOperation,
    StartOperationResult,
)


class PostgresExecutionUnitOfWork:
    def __init__(self, engine: Engine, *, failpoint: str | None = None) -> None:
        self._engine = engine
        self._failpoint = failpoint
        self.connection: Connection | None = None
        self._transaction: Any = None

    def __enter__(self) -> "PostgresExecutionUnitOfWork":
        self.connection = self._engine.connect()
        self._transaction = self.connection.begin()
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        try:
            if exc_type is None:
                self._transaction.commit()
            else:
                self._transaction.rollback()
        finally:
            self.connection.close()
        return False

    @property
    def conn(self) -> Connection:
        if self.connection is None:
            raise RuntimeError("unit of work is not active")
        return self.connection

    def start_operation(self, command: StartOperation) -> StartOperationResult:
        command.validate()
        external_reference = _external("START_OPERATION", command.command_id)
        replay = self._start_replay(command.organization_id, command.source_system, external_reference, command.required_operation_id, command.phase_id)
        if replay:
            return replay

        installation = self.conn.execute(text("SELECT o.project_id,p.plant_id FROM production.required_operations o JOIN core.projects p ON p.organization_id=o.organization_id AND p.id=o.project_id WHERE o.organization_id=:org AND o.id=:id AND o.operation_kind='installation'"), {'org':command.organization_id,'id':command.required_operation_id}).mappings().one_or_none()
        if installation:
            # Same order as project/location edits; readiness is evaluated under these locks.
            self.conn.execute(text('SELECT id FROM core.organizations WHERE id=:org FOR UPDATE'),{'org':command.organization_id})
            self.conn.execute(text('SELECT id FROM core.plants WHERE organization_id=:org AND id=:plant FOR UPDATE'),{'org':command.organization_id,'plant':installation['plant_id']})
            self.conn.execute(text('SELECT id FROM core.projects WHERE organization_id=:org AND id=:id FOR UPDATE'),{'org':command.organization_id,'id':installation['project_id']})
            from production_besten.persistence.installation_queries import installation_overview
            overview=installation_overview(self.conn,command.organization_id,installation['plant_id'],installation['project_id'])[0]
            item=next((i for i in overview['installations'] if i['operation_id']==command.required_operation_id),None)
            if not item or not item['ready_to_start']:
                raise InvalidExecutionState('Instalación no preparada: ubicación, liberación o producción precedente pendiente; o ya finalizada.')
            late_predecessor=self.conn.scalar(text("SELECT EXISTS(SELECT 1 FROM production.operation_precedences pr LEFT JOIN LATERAL (SELECT completed_at,status FROM execution.operation_executions e WHERE e.organization_id=pr.organization_id AND e.required_operation_id=pr.predecessor_operation_id ORDER BY e.created_at DESC LIMIT 1) e ON true WHERE pr.organization_id=:org AND pr.successor_operation_id=:id AND pr.active AND (e.status IS DISTINCT FROM 'completed' OR e.completed_at+pr.lag_minutes*interval '1 minute'>:at))"),{'org':command.organization_id,'id':command.required_operation_id,'at':command.started_at})
            if late_predecessor:raise InvalidExecutionState('El inicio no puede preceder a la finalización real de sus operaciones precedentes.')
        operation = self.conn.execute(
            text(
                """
                SELECT ro.id,ro.project_id,ro.project_lot_id,p.plant_id,p.status AS project_status,ro.status AS operation_status,
                       pl.current_product_definition_revision_id
                  FROM production.required_operations ro
                  JOIN core.projects p ON p.organization_id=ro.organization_id AND p.id=ro.project_id
                  JOIN core.plants pl ON pl.organization_id=p.organization_id AND pl.id=p.plant_id
                 WHERE ro.organization_id=:org AND ro.id=:operation_id
                 FOR UPDATE OF ro
                """
            ),
            {"org": command.organization_id, "operation_id": command.required_operation_id},
        ).mappings().one_or_none()
        if operation is None:
            raise EntityNotFound("required operation not found in organization")
        replay = self._start_replay(command.organization_id, command.source_system, external_reference, command.required_operation_id, command.phase_id)
        if replay:
            return replay
        if operation['project_status'] in {'inactive','archived'} or operation['operation_status']=='archived':
            raise InvalidExecutionState('El proyecto u operación no está activo para iniciar ejecución.')
        if self.conn.scalar(text("SELECT EXISTS(SELECT 1 FROM execution.operation_executions WHERE organization_id=:org AND required_operation_id=:id AND status='completed')"),{'org':command.organization_id,'id':command.required_operation_id}):
            raise ExecutionAlreadyCompleted('La operación finalizada conserva su historia y no se reabre.')
        if operation["current_product_definition_revision_id"] is None:
            raise InvalidExecutionState("plant has no current product definition revision")
        editor_state = self.conn.scalar(text("""
            SELECT action_code FROM audit.audit_entries
            WHERE organization_id=:org AND entity_id=:project
              AND action_code LIKE 'PRODUCT_EDITOR_%' AND action_code<>'PRODUCT_EDITOR_VALIDATE'
            ORDER BY occurred_at DESC,created_at DESC,id DESC LIMIT 1
        """), {"org": command.organization_id, "project": operation['project_id']})
        if editor_state and editor_state != 'PRODUCT_EDITOR_FREEZE':
            raise InvalidExecutionState("La definición tiene un borrador pendiente. Congelá la revisión antes de iniciar ejecución.")
        self._require_phase(command.organization_id, command.required_operation_id, command.phase_id)
        active = self.conn.execute(
            text(
                """
                SELECT id,origin_plan_version_id,origin_operation_plan_result_id
                  FROM execution.operation_executions
                 WHERE organization_id=:org AND required_operation_id=:operation_id
                   AND status IN ('running','paused')
                 LIMIT 1
                 FOR UPDATE
                """
            ),
            {"org": command.organization_id, "operation_id": command.required_operation_id},
        ).mappings().one_or_none()
        if active is not None:
            phase_started = bool(self.conn.scalar(
                text(
                    """
                    SELECT EXISTS(
                      SELECT 1 FROM execution.execution_segments
                       WHERE organization_id=:org AND operation_execution_id=:execution
                         AND required_operation_phase_id=:phase
                      UNION ALL
                      SELECT 1 FROM planning.effective_events
                       WHERE organization_id=:org
                         AND event_type_code IN ('OPERATION_STARTED','PHASE_STARTED')
                         AND payload->>'phase_id'=:phase_text
                         AND payload->>'operation_execution_id'=:execution_text)
                    """
                ),
                {"org": command.organization_id, "execution": active["id"], "phase": command.phase_id, "phase_text": str(command.phase_id), "execution_text": str(active["id"])},
            ))
            if phase_started:
                raise ExecutionAlreadyActive("operation phase already started")
            self._require_previous_phases_complete(
                command.organization_id, command.required_operation_id, command.phase_id, active["id"]
            )
            self._require_gates(
                command.organization_id, command.required_operation_id, command.phase_id,
                "before_start", command.started_at, include_operation_level=False,
            )
            if command.origin_plan_version_id not in {None, active["origin_plan_version_id"]} or command.origin_operation_plan_result_id not in {None, active["origin_operation_plan_result_id"]}:
                raise InvalidEstimate("phase start cannot change immutable planning origins")
            remaining_id = self.conn.scalar(
                text("SELECT id FROM execution.remaining_estimate_revisions WHERE organization_id=:org AND operation_execution_id=:execution AND superseded_at IS NULL"),
                {"org": command.organization_id, "execution": active["id"]},
            )
            event_id = uuid4()
            state_id, state_no = self._advance_state_and_event(
                organization_id=command.organization_id,
                plant_id=operation["plant_id"], actor_id=command.actor_id,
                reason="operation phase started", event_id=event_id,
                event_type="PHASE_STARTED", effective_at=command.started_at,
                entity_type="required_operation_phase", entity_id=command.phase_id,
                payload={
                    "operation_execution_id": str(active["id"]),
                    "required_operation_id": str(command.required_operation_id),
                    "phase_id": str(command.phase_id),
                    "unplanned": active["origin_plan_version_id"] is None,
                    "remaining_estimate_revision_id": str(remaining_id),
                },
                source_system=command.source_system, external_reference=external_reference,
            )
            return StartOperationResult(active["id"], event_id, state_id, state_no, remaining_id)
        self._require_previous_phases_complete(
            command.organization_id, command.required_operation_id, command.phase_id, None
        )
        self._require_gates(
            command.organization_id,
            command.required_operation_id,
            command.phase_id,
            "before_start",
            command.started_at,
            include_operation_level=True,
        )
        self._validate_start_origins(command)

        phases = self.conn.execute(
            text(
                """
                SELECT id,sequence_no,original_estimate_minutes
                  FROM production.required_operation_phases
                 WHERE organization_id=:org AND required_operation_id=:operation_id
                   AND status <> 'archived'
                 ORDER BY sequence_no
                """
            ),
            {"org": command.organization_id, "operation_id": command.required_operation_id},
        ).mappings().all()
        original_minutes = sum(row["original_estimate_minutes"] for row in phases)
        execution_id, remaining_id, event_id = uuid4(), uuid4(), uuid4()
        snapshot = {
            "labor_minutes": original_minutes,
            "phases": [
                {"phase_id": str(row["id"]), "original_estimate_minutes": row["original_estimate_minutes"]}
                for row in phases
            ],
        }
        self.conn.execute(
            text(
                """
                INSERT INTO execution.operation_executions
                  (id,organization_id,required_operation_id,source_product_definition_revision_id,
                   original_estimate_snapshot,status,origin_plan_version_id,
                   origin_operation_plan_result_id,started_at,remaining_state,created_by)
                VALUES (:id,:org,:operation_id,:definition,CAST(:snapshot AS jsonb),'running',
                        :plan_id,:operation_result_id,:started_at,'estimated',:actor)
                """
            ),
            {
                "id": execution_id,
                "org": command.organization_id,
                "operation_id": command.required_operation_id,
                "definition": operation["current_product_definition_revision_id"],
                "snapshot": _json(snapshot),
                "plan_id": command.origin_plan_version_id,
                "operation_result_id": command.origin_operation_plan_result_id,
                "started_at": command.started_at,
                "actor": command.actor_id,
            },
        )
        if self._failpoint == "start_after_execution":
            raise RuntimeError("injected failure after execution insert")
        state_id, state_no = self._advance_state_and_event(
            organization_id=command.organization_id,
            plant_id=operation["plant_id"],
            actor_id=command.actor_id,
            reason="operation execution started",
            event_id=event_id,
            event_type="OPERATION_STARTED",
            effective_at=command.started_at,
            entity_type="operation_execution",
            entity_id=execution_id,
            payload={
                "operation_execution_id": str(execution_id),
                "required_operation_id": str(command.required_operation_id),
                "phase_id": str(command.phase_id),
                "unplanned": command.origin_plan_version_id is None,
                "remaining_estimate_revision_id": str(remaining_id),
            },
            source_system=command.source_system,
            external_reference=external_reference,
        )
        self.conn.execute(
            text("UPDATE execution.operation_executions SET source_event_id=:event WHERE organization_id=:org AND id=:id"),
            {"event": event_id, "org": command.organization_id, "id": execution_id},
        )
        self.conn.execute(
            text(
                """
                INSERT INTO execution.remaining_estimate_revisions
                  (id,organization_id,operation_execution_id,revision_no,cutoff_at,input_mode,
                   raw_input,reason,effective_event_id,planning_state_revision_id,
                   executed_labor_minutes_at_cutoff,remaining_labor_minutes,
                   updated_total_labor_minutes,created_by)
                VALUES (:id,:org,:execution,1,:cutoff,'remaining_duration',CAST(:raw AS jsonb),
                        'initial estimate at execution start',:event,:state,0,:remaining,:remaining,:actor)
                """
            ),
            {
                "id": remaining_id,
                "org": command.organization_id,
                "execution": execution_id,
                "cutoff": command.started_at,
                "raw": _json({"minutes": original_minutes, "source": "original_estimate"}),
                "event": event_id,
                "state": state_id,
                "remaining": original_minutes,
                "actor": command.actor_id,
            },
        )
        self.conn.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        return StartOperationResult(execution_id, event_id, state_id, state_no, remaining_id)

    def register_execution_segment(
        self, command: RegisterExecutionSegment
    ) -> RegisterExecutionSegmentResult:
        command.validate()
        external_reference = _external("REGISTER_EXECUTION_SEGMENT", command.command_id)
        replay = self._segment_replay(command.organization_id, command.source_system, external_reference, command.operation_execution_id, command.phase_id)
        if replay:
            return replay
        execution = self._lock_execution(command.organization_id, command.operation_execution_id)
        replay = self._segment_replay(command.organization_id, command.source_system, external_reference, command.operation_execution_id, command.phase_id)
        if replay:
            return replay
        if execution["status"] not in {"running", "paused"}:
            raise InvalidExecutionState("execution segment requires running or paused execution")
        if command.started_at < execution["started_at"]:
            raise InvalidEstimate("segment cannot start before operation execution")
        self._require_phase(command.organization_id, execution["required_operation_id"], command.phase_id)
        self._require_previous_phases_complete(
            command.organization_id,
            execution["required_operation_id"],
            command.phase_id,
            command.operation_execution_id,
        )
        phase_has_work = self.conn.scalar(
            text(
                """
                SELECT EXISTS(SELECT 1 FROM execution.execution_segments
                 WHERE organization_id=:org AND operation_execution_id=:execution
                   AND required_operation_phase_id=:phase AND segment_kind='work')
                """
            ),
            {"org": command.organization_id, "execution": command.operation_execution_id, "phase": command.phase_id},
        )
        if not phase_has_work:
            self._require_gates(
                command.organization_id,
                execution["required_operation_id"],
                command.phase_id,
                "before_start",
                command.started_at,
                include_operation_level=False,
            )
        self._validate_segment_origin(command)
        is_installation=self.conn.scalar(text("SELECT operation_kind='installation' FROM production.required_operations WHERE organization_id=:org AND id=:id"),{'org':command.organization_id,'id':execution['required_operation_id']})
        if is_installation:
            if not command.humans:raise StructuralAvailabilityConflict('La instalación debe registrar su equipo real.')
            for table,ids in [('capacity.employees',[h.employee_id for h in command.humans]),('capacity.physical_resources',[h.physical_resource_id for h in command.physical_usages])]:
                count=self.conn.scalar(text('SELECT count(*) FROM '+table+" WHERE organization_id=:org AND plant_id=:plant AND id=ANY(:ids) AND status='active'"),{'org':command.organization_id,'plant':execution['plant_id'],'ids':ids})
                if count!=len(set(ids)):raise EntityNotFound('Equipo real fuera de planta.')
            required=self.conn.execute(text('SELECT * FROM production.operation_physical_requirements WHERE organization_id=:org AND required_operation_phase_id=:phase AND is_mandatory'),{'org':command.organization_id,'phase':command.phase_id}).mappings().all()
            for req in required:
                ids=[h.physical_resource_id for h in command.physical_usages]
                count=self.conn.scalar(text('''SELECT count(*) FROM capacity.physical_resources r WHERE r.organization_id=:org AND r.plant_id=:plant AND r.id=ANY(:ids)
                    AND (CAST(:type AS uuid) IS NULL OR r.resource_type_id=:type) AND (CAST(:center AS uuid) IS NULL OR r.work_center_id=:center)
                    AND (CAST(:group AS uuid) IS NULL OR EXISTS(SELECT 1 FROM capacity.physical_resource_group_members m WHERE m.organization_id=r.organization_id AND m.physical_resource_id=r.id AND m.group_id=:group AND m.valid_during @> CAST(:day AS date)))'''),{'org':command.organization_id,'plant':execution['plant_id'],'ids':ids,'type':req['physical_resource_type_id'],'center':req['work_center_id'],'group':req['physical_resource_group_id'],'day':command.started_at.date()})
                if count<req['quantity']:raise StructuralAvailabilityConflict('Falta recurso físico requerido para instalación.')
        self._validate_actual_resources(command)
        if command.occupations and execution["project_lot_id"] is None:
            raise InvalidEstimate("physical occupation requires an operation project lot")

        segment_no = int(
            self.conn.scalar(
                text("SELECT COALESCE(max(segment_no),0)+1 FROM execution.execution_segments WHERE organization_id=:org AND operation_execution_id=:execution"),
                {"org": command.organization_id, "execution": command.operation_execution_id},
            )
        )
        segment_id, event_id = uuid4(), uuid4()
        state_id, state_no = self._advance_state_and_event(
            organization_id=command.organization_id,
            plant_id=execution["plant_id"],
            actor_id=command.actor_id,
            reason="real execution segment registered",
            event_id=event_id,
            event_type="EXECUTION_SEGMENT_REGISTERED",
            effective_at=command.ended_at,
            entity_type="operation_execution",
            entity_id=command.operation_execution_id,
            payload={
                "operation_execution_id": str(command.operation_execution_id),
                "segment_id": str(segment_id),
                "segment_no": segment_no,
                "phase_id": str(command.phase_id),
            },
            source_system=command.source_system,
            external_reference=external_reference,
        )
        self.conn.execute(
            text(
                """
                INSERT INTO execution.execution_segments
                  (id,organization_id,operation_execution_id,required_operation_phase_id,
                   origin_assignment_segment_id,segment_no,time_range,segment_kind,
                   work_minutes,source_event_id)
                VALUES (:id,:org,:execution,:phase,:origin,:number,
                        tstzrange(:started,:ended,'[)'),'work',:work_minutes,:event)
                """
            ),
            {
                "id": segment_id,
                "org": command.organization_id,
                "execution": command.operation_execution_id,
                "phase": command.phase_id,
                "origin": command.origin_assignment_segment_id,
                "number": segment_no,
                "started": command.started_at,
                "ended": command.ended_at,
                "work_minutes": command.work_minutes,
                "event": event_id,
            },
        )
        if self._failpoint == "segment_after_segment":
            raise RuntimeError("injected failure after segment insert")
        for human in command.humans:
            self._insert_actual_usage(
                command.organization_id, segment_id, command.started_at, command.ended_at,
                human.work_minutes, "labor", employee_id=human.employee_id
            )
        for resource in command.physical_usages:
            self._insert_actual_usage(
                command.organization_id, segment_id, command.started_at, command.ended_at,
                resource.work_minutes, "active_use",
                physical_resource_id=resource.physical_resource_id,
                capacity_units=resource.capacity_units,
            )
        for occupation in command.occupations:
            self.conn.execute(
                text(
                    """
                    INSERT INTO planning.physical_occupations
                      (organization_id,operation_execution_id,project_lot_id,
                       required_operation_phase_id,physical_resource_id,source_kind,
                       time_range,planned_release_at,actual_released_at,is_effective)
                    VALUES (:org,:execution,:lot,:phase,:resource,'actual',
                            tstzrange(:started,:ended,'[)'),:ended,:ended,true)
                    """
                ),
                {
                    "org": command.organization_id,
                    "execution": command.operation_execution_id,
                    "lot": execution["project_lot_id"],
                    "phase": command.phase_id,
                    "resource": occupation.physical_resource_id,
                    "started": occupation.started_at,
                    "ended": occupation.ended_at,
                },
            )
        self.conn.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        return RegisterExecutionSegmentResult(segment_id, segment_no, event_id, state_id, state_no)

    def finish_operation(self, command: FinishOperation) -> FinishOperationResult:
        command.validate()
        external_reference = _external("FINISH_OPERATION", command.command_id)
        replay = self._finish_replay(command.organization_id, command.source_system, external_reference, command.operation_execution_id, command.phase_id)
        if replay:
            return replay
        execution = self._lock_execution(command.organization_id, command.operation_execution_id)
        replay = self._finish_replay(command.organization_id, command.source_system, external_reference, command.operation_execution_id, command.phase_id)
        if replay:
            return replay
        if execution["status"] == "completed":
            raise ExecutionAlreadyCompleted("operation execution already completed")
        if execution["status"] not in {"running", "paused"}:
            raise InvalidExecutionState("finish requires running or paused execution")
        if command.completed_at < execution["started_at"]:
            raise InvalidEstimate("completion cannot precede execution start")
        self._require_phase(command.organization_id, execution["required_operation_id"], command.phase_id)
        self._require_previous_phases_complete(
            command.organization_id,
            execution["required_operation_id"],
            command.phase_id,
            command.operation_execution_id,
        )
        if self._phase_completed(command.organization_id, command.operation_execution_id, command.phase_id):
            raise ExecutionAlreadyCompleted("operation phase already completed")

        total_phases = int(
            self.conn.scalar(
                text("SELECT count(*) FROM production.required_operation_phases WHERE organization_id=:org AND required_operation_id=:operation AND status<>'archived'"),
                {"org": command.organization_id, "operation": execution["required_operation_id"]},
            )
        )
        completed_phases = int(
            self.conn.scalar(
                text(
                    """
                    SELECT count(DISTINCT entity_id) FROM planning.effective_events
                     WHERE organization_id=:org AND entity_type='required_operation_phase'
                       AND event_type_code IN ('PHASE_COMPLETED','OPERATION_COMPLETED')
                       AND payload->>'operation_execution_id'=:execution
                    """
                ),
                {"org": command.organization_id, "execution": str(command.operation_execution_id)},
            )
        )
        operation_completed = completed_phases + 1 == total_phases
        self._require_gates(
            command.organization_id,
            execution["required_operation_id"],
            command.phase_id,
            "before_finish",
            command.completed_at,
            include_operation_level=operation_completed,
        )
        actual_labor = self._actual_labor(command.organization_id, command.operation_execution_id, command.completed_at)
        original_labor = execution["original_estimate_snapshot"].get("labor_minutes")
        if not isinstance(original_labor, int):
            raise InvalidEstimate("original snapshot requires labor_minutes")
        variance = actual_labor - original_labor
        event_id = uuid4()
        state_id, state_no = self._advance_state_and_event(
            organization_id=command.organization_id,
            plant_id=execution["plant_id"],
            actor_id=command.actor_id,
            reason="operation phase completed" if not operation_completed else "operation completed",
            event_id=event_id,
            event_type="OPERATION_COMPLETED" if operation_completed else "PHASE_COMPLETED",
            effective_at=command.completed_at,
            entity_type="required_operation_phase",
            entity_id=command.phase_id,
            payload={
                "operation_execution_id": str(command.operation_execution_id),
                "phase_id": str(command.phase_id),
                "operation_completed": operation_completed,
                "original_labor_minutes": original_labor,
                "actual_labor_minutes": actual_labor,
                "variance_labor_minutes": variance,
            },
            source_system=command.source_system,
            external_reference=external_reference,
        )
        if operation_completed:
            self.conn.execute(
                text(
                    """
                    UPDATE execution.operation_executions
                       SET status='completed',completed_at=:completed_at,remaining_state='completed'
                     WHERE organization_id=:org AND id=:execution
                    """
                ),
                {"completed_at": command.completed_at, "org": command.organization_id, "execution": command.operation_execution_id},
            )
        if self._failpoint == "finish_after_status":
            raise RuntimeError("injected failure after finish status")
        return FinishOperationResult(
            command.operation_execution_id,
            command.phase_id,
            operation_completed,
            event_id,
            state_id,
            state_no,
            original_labor,
            actual_labor,
            variance,
        )

    def _advance_state_and_event(
        self, *, organization_id: UUID, plant_id: UUID, actor_id: UUID,
        reason: str, event_id: UUID, event_type: str, effective_at: datetime,
        entity_type: str, entity_id: UUID, payload: dict[str, Any],
        source_system: str, external_reference: str,
    ) -> tuple[UUID, int]:
        head = self.conn.execute(
            text("SELECT current_revision_no FROM planning.planning_state_heads WHERE organization_id=:org AND plant_id=:plant FOR UPDATE"),
            {"org": organization_id, "plant": plant_id},
        ).mappings().one_or_none()
        if head is None:
            raise EntityNotFound("planning state head not found in organization")
        state_id, state_no = uuid4(), head["current_revision_no"] + 1
        self.conn.execute(
            text(
                """
                INSERT INTO planning.planning_state_revisions
                  (id,organization_id,plant_id,revision_no,reason,transaction_key,change_summary,created_by)
                VALUES (:id,:org,:plant,:number,:reason,:key,CAST(:summary AS jsonb),:actor)
                """
            ),
            {"id": state_id, "org": organization_id, "plant": plant_id, "number": state_no,
             "reason": reason, "key": uuid4(), "summary": _json({"event_type": event_type, "entity_id": str(entity_id)}), "actor": actor_id},
        )
        self.conn.execute(
            text(
                """
                INSERT INTO planning.effective_events
                  (id,organization_id,plant_id,event_type_code,payload_schema_version,
                   occurred_at,effective_at,entity_type,entity_id,payload,cause,
                   planning_state_revision_id,source_system,external_reference,created_by)
                VALUES (:id,:org,:plant,:event_type,1,:occurred,:effective,:entity_type,
                        :entity_id,CAST(:payload AS jsonb),:cause,:state,:source,:reference,:actor)
                """
            ),
            {"id": event_id, "org": organization_id, "plant": plant_id, "event_type": event_type,
             "occurred": datetime.now(timezone.utc), "effective": effective_at, "entity_type": entity_type,
             "entity_id": entity_id, "payload": _json(payload), "cause": reason, "state": state_id,
             "source": source_system, "reference": external_reference, "actor": actor_id},
        )
        self.conn.execute(
            text(
                """
                UPDATE planning.planning_state_heads
                   SET current_revision_id=:state,current_revision_no=:number,
                       row_version=row_version+1,updated_at=now(),updated_by=:actor
                 WHERE organization_id=:org AND plant_id=:plant
                """
            ),
            {"state": state_id, "number": state_no, "actor": actor_id, "org": organization_id, "plant": plant_id},
        )
        return state_id, state_no

    def _lock_execution(self, organization_id: UUID, execution_id: UUID) -> Any:
        row = self.conn.execute(
            text(
                """
                SELECT oe.*,ro.project_id,ro.project_lot_id,p.plant_id
                  FROM execution.operation_executions oe
                  JOIN production.required_operations ro ON ro.organization_id=oe.organization_id AND ro.id=oe.required_operation_id
                  JOIN core.projects p ON p.organization_id=ro.organization_id AND p.id=ro.project_id
                 WHERE oe.organization_id=:org AND oe.id=:execution
                 FOR UPDATE OF oe
                """
            ),
            {"org": organization_id, "execution": execution_id},
        ).mappings().one_or_none()
        if row is None:
            raise EntityNotFound("operation execution not found in organization")
        return row

    def _require_phase(self, organization_id: UUID, operation_id: UUID, phase_id: UUID) -> None:
        found = self.conn.scalar(
            text("SELECT EXISTS(SELECT 1 FROM production.required_operation_phases WHERE organization_id=:org AND required_operation_id=:operation AND id=:phase AND status<>'archived')"),
            {"org": organization_id, "operation": operation_id, "phase": phase_id},
        )
        if not found:
            raise EntityNotFound("operation phase not found in operation and organization")

    def _require_previous_phases_complete(
        self, organization_id: UUID, operation_id: UUID, phase_id: UUID,
        execution_id: UUID | None,
    ) -> None:
        previous = self.conn.execute(
            text(
                """
                SELECT prior.id FROM production.required_operation_phases current_phase
                JOIN production.required_operation_phases prior
                  ON prior.organization_id=current_phase.organization_id
                 AND prior.required_operation_id=current_phase.required_operation_id
                 AND prior.sequence_no<current_phase.sequence_no AND prior.status<>'archived'
                WHERE current_phase.organization_id=:org AND current_phase.required_operation_id=:operation
                  AND current_phase.id=:phase
                """
            ),
            {"org": organization_id, "operation": operation_id, "phase": phase_id},
        ).scalars().all()
        if not previous:
            return
        if execution_id is None:
            raise InvalidExecutionState("cannot start execution at a phase with incomplete predecessors")
        completed = self.conn.execute(
            text(
                """
                SELECT DISTINCT entity_id FROM planning.effective_events
                 WHERE organization_id=:org AND entity_type='required_operation_phase'
                   AND event_type_code IN ('PHASE_COMPLETED','OPERATION_COMPLETED')
                   AND payload->>'operation_execution_id'=:execution
                   AND entity_id=ANY(:phase_ids)
                """
            ),
            {"org": organization_id, "execution": str(execution_id), "phase_ids": previous},
        ).scalars().all()
        if set(completed) != set(previous):
            raise InvalidExecutionState("previous operation phases are incomplete")

    def _phase_completed(self, organization_id: UUID, execution_id: UUID, phase_id: UUID) -> bool:
        return bool(
            self.conn.scalar(
                text(
                    """
                    SELECT EXISTS(SELECT 1 FROM planning.effective_events
                     WHERE organization_id=:org AND entity_type='required_operation_phase'
                       AND entity_id=:phase AND event_type_code IN ('PHASE_COMPLETED','OPERATION_COMPLETED')
                       AND payload->>'operation_execution_id'=:execution)
                    """
                ),
                {"org": organization_id, "phase": phase_id, "execution": str(execution_id)},
            )
        )

    def _require_gates(
        self, organization_id: UUID, operation_id: UUID, phase_id: UUID,
        timing: str, effective_at: datetime, *, include_operation_level: bool,
    ) -> None:
        gates = self.conn.execute(
            text(
                """
                SELECT * FROM production.operation_gates
                 WHERE organization_id=:org AND required_operation_id=:operation
                   AND timing=:timing
                   AND (required_operation_phase_id=:phase
                        OR (:include_operation AND required_operation_phase_id IS NULL))
                """
            ),
            {"org": organization_id, "operation": operation_id, "timing": timing,
             "phase": phase_id, "include_operation": include_operation_level},
        ).mappings().all()
        blocked: list[str] = []
        for gate in gates:
            satisfied = False
            if gate["available_at"] is not None:
                satisfied = gate["available_at"] <= effective_at
            elif gate["hardware_project_lot_id"] is not None:
                satisfied = bool(self.conn.scalar(
                    text("SELECT EXISTS(SELECT 1 FROM core.project_lots WHERE organization_id=:org AND id=:id AND hardware_status IN ('ready','not_required') AND (hardware_available_at IS NULL OR hardware_available_at<=:at))"),
                    {"org": organization_id, "id": gate["hardware_project_lot_id"], "at": effective_at},
                ))
            elif gate["drawing_package_id"] is not None:
                satisfied = bool(self.conn.scalar(
                    text("SELECT EXISTS(SELECT 1 FROM production.drawing_releases WHERE organization_id=:org AND drawing_package_id=:id AND status='released' AND released_at<=:at AND NOT EXISTS(SELECT 1 FROM production.drawing_releases successor WHERE successor.organization_id=production.drawing_releases.organization_id AND successor.supersedes_id=production.drawing_releases.id))"),
                    {"org": organization_id, "id": gate["drawing_package_id"], "at": effective_at},
                ))
            elif gate["milestone_definition_id"] is not None:
                satisfied = bool(self.conn.scalar(
                    text("SELECT EXISTS(SELECT 1 FROM core.project_milestones m JOIN production.required_operations ro ON ro.organization_id=m.organization_id AND ro.project_id=m.project_id WHERE ro.organization_id=:org AND ro.id=:operation AND m.milestone_definition_id=:milestone AND m.occurred_at<=:at)"),
                    {"org": organization_id, "operation": operation_id, "milestone": gate["milestone_definition_id"], "at": effective_at},
                ))
            elif gate["material_requirement_id"] is not None:
                satisfied = bool(self.conn.scalar(
                    text(
                        """
                        SELECT COALESCE(sum(a.quantity*a.movement_sign),0)>=r.required_quantity
                          FROM production.material_requirements r
                          LEFT JOIN production.material_allocations a
                            ON a.organization_id=r.organization_id AND a.material_requirement_id=r.id
                          LEFT JOIN production.supplier_delivery_lines dl
                            ON dl.organization_id=a.organization_id AND dl.id=a.supplier_delivery_line_id
                          LEFT JOIN production.supplier_deliveries d
                            ON d.organization_id=dl.organization_id AND d.id=dl.supplier_delivery_id
                         WHERE r.organization_id=:org AND r.id=:id
                           AND (d.id IS NULL OR d.delivered_at<=:at)
                         GROUP BY r.required_quantity
                        """
                    ),
                    {"org": organization_id, "id": gate["material_requirement_id"], "at": effective_at},
                ))
            if not satisfied:
                blocked.append(f"{gate['gate_type']}:{gate['id']}")
        if blocked:
            raise GateBlocked("unsatisfied gates: " + ", ".join(blocked))

    def _validate_start_origins(self, command: StartOperation) -> None:
        if command.origin_plan_version_id is not None:
            valid = self.conn.scalar(
                text("SELECT EXISTS(SELECT 1 FROM planning.plan_versions WHERE organization_id=:org AND id=:id)"),
                {"org": command.organization_id, "id": command.origin_plan_version_id},
            )
            if not valid:
                raise EntityNotFound("origin plan version not found in organization")
        if command.origin_operation_plan_result_id is not None:
            valid = self.conn.scalar(
                text("SELECT EXISTS(SELECT 1 FROM planning.operation_plan_results WHERE organization_id=:org AND id=:id AND required_operation_id=:operation)"),
                {"org": command.organization_id, "id": command.origin_operation_plan_result_id, "operation": command.required_operation_id},
            )
            if not valid:
                raise EntityNotFound("origin operation plan result not found for operation")

    def _validate_segment_origin(self, command: RegisterExecutionSegment) -> None:
        if command.origin_assignment_segment_id is None:
            return
        valid = self.conn.scalar(
            text("SELECT EXISTS(SELECT 1 FROM planning.assignment_segments WHERE organization_id=:org AND id=:id)"),
            {"org": command.organization_id, "id": command.origin_assignment_segment_id},
        )
        if not valid:
            raise EntityNotFound("origin assignment segment not found in organization")

    def _validate_actual_resources(self, command: RegisterExecutionSegment) -> None:
        employee_ids = [value.employee_id for value in command.humans]
        resource_ids = list({value.physical_resource_id for value in (*command.physical_usages, *command.occupations)})
        required_people=self.conn.scalar(text('SELECT required_people FROM production.required_operation_phases WHERE organization_id=:org AND id=:phase'),{'org':command.organization_id,'phase':command.phase_id}) or 0
        if len(set(employee_ids)) < required_people:
            raise StructuralAvailabilityConflict("actual team does not satisfy required people quantity")
        if employee_ids:
            active = self.conn.execute(
                text("SELECT id FROM capacity.employees WHERE organization_id=:org AND id=ANY(:ids) AND status='active'"),
                {"org": command.organization_id, "ids": employee_ids},
            ).scalars().all()
            if set(active) != set(employee_ids):
                raise EntityNotFound("real employee not found or inactive in organization")
            conflicts = self.conn.scalar(
                text(
                    """
                    SELECT EXISTS(SELECT 1 FROM execution.actual_resource_usages aru
                    WHERE aru.organization_id=:org AND aru.employee_id=ANY(:ids)
                      AND aru.time_range && tstzrange(:started,:ended,'[)')
                      AND NOT EXISTS(SELECT 1 FROM execution.actual_resource_usages successor
                        WHERE successor.organization_id=aru.organization_id AND successor.supersedes_id=aru.id))
                    """
                ),
                {"org": command.organization_id, "ids": employee_ids, "started": command.started_at, "ended": command.ended_at},
            )
            if conflicts:
                raise StructuralAvailabilityConflict("real employee has overlapping actual work")
            requirements = self.conn.execute(
                text("SELECT skill_id,min_people,max_people FROM production.operation_labor_requirements WHERE organization_id=:org AND required_operation_phase_id=:phase AND is_mandatory"),
                {"org": command.organization_id, "phase": command.phase_id},
            ).mappings().all()
            for requirement in requirements:
                skilled = int(self.conn.scalar(
                    text("SELECT count(DISTINCT employee_id) FROM capacity.employee_skills WHERE organization_id=:org AND employee_id=ANY(:ids) AND skill_id=:skill AND enabled AND valid_during @> CAST(:work_date AS date)"),
                    {"org": command.organization_id, "ids": employee_ids, "skill": requirement["skill_id"], "work_date": command.started_at.date()},
                ))
                if skilled < requirement["min_people"] or skilled > requirement["max_people"]:
                    raise StructuralAvailabilityConflict("actual team does not satisfy required skill quantity")
        if resource_ids:
            active = self.conn.execute(
                text("SELECT id FROM capacity.physical_resources WHERE organization_id=:org AND id=ANY(:ids) AND status='active'"),
                {"org": command.organization_id, "ids": resource_ids},
            ).scalars().all()
            if set(active) != set(resource_ids):
                raise EntityNotFound("real physical resource not found or inactive in organization")
        active_use_ids = [value.physical_resource_id for value in command.physical_usages]
        if active_use_ids:
            conflict = self.conn.scalar(
                text(
                    """
                    SELECT EXISTS(SELECT 1 FROM execution.actual_resource_usages aru
                    JOIN capacity.physical_resources r ON r.organization_id=aru.organization_id AND r.id=aru.physical_resource_id
                    WHERE aru.organization_id=:org AND aru.physical_resource_id=ANY(:ids)
                      AND r.scheduling_mode='exclusive'
                      AND aru.time_range && tstzrange(:started,:ended,'[)')
                      AND NOT EXISTS(SELECT 1 FROM execution.actual_resource_usages successor
                        WHERE successor.organization_id=aru.organization_id AND successor.supersedes_id=aru.id))
                    """
                ),
                {"org": command.organization_id, "ids": active_use_ids, "started": command.started_at, "ended": command.ended_at},
            )
            if conflict:
                raise StructuralAvailabilityConflict("exclusive physical resource has overlapping actual use")

    def _insert_actual_usage(
        self, organization_id: UUID, segment_id: UUID, started_at: datetime,
        ended_at: datetime, work_minutes: int, usage_kind: str, *,
        employee_id: UUID | None = None, physical_resource_id: UUID | None = None,
        capacity_units: float | None = None,
    ) -> None:
        self.conn.execute(
            text(
                """
                INSERT INTO execution.actual_resource_usages
                  (organization_id,execution_segment_id,employee_id,physical_resource_id,
                   time_range,work_minutes,capacity_units,usage_kind)
                VALUES (:org,:segment,:employee,:resource,tstzrange(:started,:ended,'[)'),
                        :minutes,:capacity,:kind)
                """
            ),
            {"org": organization_id, "segment": segment_id, "employee": employee_id,
             "resource": physical_resource_id, "started": started_at, "ended": ended_at,
             "minutes": work_minutes, "capacity": capacity_units, "kind": usage_kind},
        )

    def _actual_labor(self, organization_id: UUID, execution_id: UUID, cutoff: datetime) -> int:
        return int(self.conn.scalar(
            text(
                """
                SELECT COALESCE(sum(aru.work_minutes),0)
                  FROM execution.actual_resource_usages aru
                  JOIN execution.execution_segments es ON es.organization_id=aru.organization_id AND es.id=aru.execution_segment_id
                 WHERE aru.organization_id=:org AND es.operation_execution_id=:execution
                   AND aru.employee_id IS NOT NULL AND upper(aru.time_range)<=:cutoff
                   AND NOT EXISTS(SELECT 1 FROM execution.actual_resource_usages successor WHERE successor.organization_id=aru.organization_id AND successor.supersedes_id=aru.id)
                   AND NOT EXISTS(SELECT 1 FROM execution.execution_segments successor_segment WHERE successor_segment.organization_id=es.organization_id AND successor_segment.supersedes_id=es.id)
                """
            ),
            {"org": organization_id, "execution": execution_id, "cutoff": cutoff},
        ) or 0)

    def _event_replay(self, organization_id: UUID, source: str, reference: str) -> Any:
        return self.conn.execute(
            text(
                """
                SELECT e.id,e.payload,e.planning_state_revision_id,r.revision_no
                  FROM planning.effective_events e
                  JOIN planning.planning_state_revisions r ON r.organization_id=e.organization_id AND r.id=e.planning_state_revision_id
                 WHERE e.organization_id=:org AND e.source_system=:source AND e.external_reference=:reference
                """
            ),
            {"org": organization_id, "source": source, "reference": reference},
        ).mappings().one_or_none()

    def _start_replay(self, organization_id: UUID, source: str, reference: str, operation_id: UUID, phase_id: UUID) -> StartOperationResult | None:
        event = self._event_replay(organization_id, source, reference)
        if event is None:
            return None
        if event["payload"].get("required_operation_id") != str(operation_id) or event["payload"].get("phase_id") != str(phase_id):
            raise IdempotencyConflict("idempotency key was already used for another start target")
        execution_id = UUID(event["payload"]["operation_execution_id"])
        remaining_id = UUID(event["payload"]["remaining_estimate_revision_id"])
        return StartOperationResult(execution_id, event["id"], event["planning_state_revision_id"], event["revision_no"], remaining_id, True)

    def _segment_replay(self, organization_id: UUID, source: str, reference: str, execution_id: UUID, phase_id: UUID) -> RegisterExecutionSegmentResult | None:
        event = self._event_replay(organization_id, source, reference)
        if event is None:
            return None
        if event["payload"].get("operation_execution_id") != str(execution_id) or event["payload"].get("phase_id") != str(phase_id):
            raise IdempotencyConflict("idempotency key was already used for another segment target")
        return RegisterExecutionSegmentResult(UUID(event["payload"]["segment_id"]), int(event["payload"]["segment_no"]), event["id"], event["planning_state_revision_id"], event["revision_no"], True)

    def _finish_replay(self, organization_id: UUID, source: str, reference: str, execution_id: UUID, phase_id: UUID) -> FinishOperationResult | None:
        event = self._event_replay(organization_id, source, reference)
        if event is None:
            return None
        payload = event["payload"]
        if payload.get("operation_execution_id") != str(execution_id) or payload.get("phase_id") != str(phase_id):
            raise IdempotencyConflict("idempotency key was already used for another finish target")
        return FinishOperationResult(
            UUID(payload["operation_execution_id"]), UUID(payload["phase_id"]),
            bool(payload["operation_completed"]), event["id"], event["planning_state_revision_id"],
            event["revision_no"], int(payload["original_labor_minutes"]),
            int(payload["actual_labor_minutes"]), int(payload["variance_labor_minutes"]), True,
        )


class PostgresExecutionUnitOfWorkFactory:
    def __init__(self, engine: Engine, *, failpoint: str | None = None) -> None:
        self._engine = engine
        self._failpoint = failpoint

    def __call__(self) -> PostgresExecutionUnitOfWork:
        return PostgresExecutionUnitOfWork(self._engine, failpoint=self._failpoint)


def _external(command_name: str, command_id: UUID) -> str:
    return f"{command_name}:{command_id}"


def _json(value: dict[str, Any]) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)
