from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import Engine, text

from production_besten.application.execution_services import StartOperationService
from production_besten.domain.execution import StartOperation, StartOperationResult
from production_besten.persistence.execution_uow import PostgresExecutionUnitOfWorkFactory

from .conftest import SeededCase


@dataclass(frozen=True)
class UnstartedCase:
    base: SeededCase
    operation_id: UUID
    phase_ids: tuple[UUID, ...]
    planned_employee_id: UUID
    actual_employee_id: UUID
    planned_resource_id: UUID
    actual_resource_id: UUID
    physical_requirement_id: UUID
    started_at: datetime
    original_labor_minutes: int
    operation_plan_result_id: UUID | None = None
    assignment_segment_id: UUID | None = None


def create_unstarted_case(
    engine: Engine,
    base: SeededCase,
    *,
    phase_minutes: tuple[int, ...] = (480,),
    planned: bool = False,
) -> UnstartedCase:
    operation_id = uuid4()
    phase_ids = tuple(uuid4() for _ in phase_minutes)
    actual_employee, planned_employee, actual_resource, planned_resource = (uuid4() for _ in range(4))
    physical_requirement = uuid4()
    started_at = datetime(2026, 10, 2, 8, 30, tzinfo=timezone.utc)
    suffix = operation_id.hex[:12]
    operation_result = assignment_segment = None
    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO production.required_operations(id,organization_id,project_id,project_lot_id,operation_definition_id,code,name,status) VALUES (:id,:org,:project,:lot,:definition,:code,'Execution test','active')"),
            {"id": operation_id, "org": base.organization_id, "project": base.project_id, "lot": base.project_lot_id, "definition": base.operation_definition_id, "code": f"EXEC-{suffix}"},
        )
        for sequence, (phase_id, minutes) in enumerate(zip(phase_ids, phase_minutes), start=1):
            connection.execute(
                text("INSERT INTO production.required_operation_phases(id,organization_id,required_operation_id,sequence_no,code,name,estimate_kind,original_estimate_minutes,split_policy,status) VALUES (:id,:org,:operation,:sequence,:code,:name,'labor',:minutes,'splittable','active')"),
                {"id": phase_id, "org": base.organization_id, "operation": operation_id, "sequence": sequence, "code": f"P{sequence}", "name": f"Phase {sequence}", "minutes": minutes},
            )
            connection.execute(
                text("INSERT INTO production.operation_labor_requirements(organization_id,required_operation_phase_id,skill_id,min_people,max_people,work_minutes,is_mandatory) VALUES (:org,:phase,:skill,1,2,:minutes,true)"),
                {"org": base.organization_id, "phase": phase_id, "skill": base.skill_id, "minutes": minutes},
            )
        connection.execute(
            text("INSERT INTO production.operation_physical_requirements(id,organization_id,required_operation_phase_id,physical_resource_type_id,quantity,capacity_units,usage_mode) VALUES (:id,:org,:phase,:type,1,1,'active_use')"),
            {"id": physical_requirement, "org": base.organization_id, "phase": phase_ids[0], "type": base.resource_type_id},
        )
        for employee_id, label in ((actual_employee, "Actual"), (planned_employee, "Planned")):
            connection.execute(
                text("INSERT INTO capacity.employees(id,organization_id,plant_id,code,display_name,base_calendar_id) VALUES (:id,:org,:plant,:code,:name,:calendar)"),
                {"id": employee_id, "org": base.organization_id, "plant": base.plant_id, "code": f"{label[:1]}-{employee_id.hex[:12]}", "name": label, "calendar": base.calendar_id},
            )
            connection.execute(
                text("INSERT INTO capacity.employee_skills(organization_id,employee_id,skill_id,valid_during,enabled) VALUES (:org,:employee,:skill,daterange('2026-01-01','2027-01-01','[)'),true)"),
                {"org": base.organization_id, "employee": employee_id, "skill": base.skill_id},
            )
        for resource_id, label in ((actual_resource, "Actual bench"), (planned_resource, "Planned bench")):
            connection.execute(
                text("INSERT INTO capacity.physical_resources(id,organization_id,plant_id,work_center_id,resource_type_id,code,name,scheduling_mode,capacity_units,capacity_unit,base_calendar_id) VALUES (:id,:org,:plant,:center,:type,:code,:name,'exclusive',1,'unit',:calendar)"),
                {"id": resource_id, "org": base.organization_id, "plant": base.plant_id, "center": base.work_center_id, "type": base.resource_type_id, "code": f"R-{resource_id.hex[:12]}", "name": label, "calendar": base.calendar_id},
            )
        if planned:
            operation_result, phase_result, assignment_id, assignment_segment = (uuid4() for _ in range(4))
            connection.execute(
                text("INSERT INTO planning.operation_plan_results(id,organization_id,schedule_solution_id,required_operation_id,result_status,planned_start_at,planned_end_at,remaining_work_minutes) VALUES (:id,:org,:solution,:operation,'planned',:start,:finish,:minutes)"),
                {"id": operation_result, "org": base.organization_id, "solution": base.schedule_solution_id, "operation": operation_id, "start": started_at, "finish": started_at + timedelta(minutes=sum(phase_minutes)), "minutes": sum(phase_minutes)},
            )
            connection.execute(
                text("INSERT INTO planning.phase_plan_results(id,organization_id,operation_plan_result_id,schedule_solution_id,required_operation_phase_id,result_status,planned_work_minutes,remaining_work_minutes) VALUES (:id,:org,:operation_result,:solution,:phase,'planned',:minutes,:minutes)"),
                {"id": phase_result, "org": base.organization_id, "operation_result": operation_result, "solution": base.schedule_solution_id, "phase": phase_ids[0], "minutes": phase_minutes[0]},
            )
            connection.execute(
                text("INSERT INTO planning.planned_phase_assignments(id,organization_id,phase_plan_result_id,schedule_solution_id,assignment_kind,planned_start_at,planned_end_at,work_minutes) VALUES (:id,:org,:phase_result,:solution,'operation',:start,:finish,:minutes)"),
                {"id": assignment_id, "org": base.organization_id, "phase_result": phase_result, "solution": base.schedule_solution_id, "start": started_at, "finish": started_at + timedelta(minutes=phase_minutes[0]), "minutes": phase_minutes[0]},
            )
            connection.execute(
                text("INSERT INTO planning.assignment_segments(id,organization_id,planned_phase_assignment_id,schedule_solution_id,segment_no,time_range,normal_minutes,overtime_minutes,work_minutes) VALUES (:id,:org,:assignment,:solution,1,tstzrange(:start,:finish,'[)'),:minutes,0,:minutes)"),
                {"id": assignment_segment, "org": base.organization_id, "assignment": assignment_id, "solution": base.schedule_solution_id, "start": started_at, "finish": started_at + timedelta(minutes=phase_minutes[0]), "minutes": phase_minutes[0]},
            )
            connection.execute(
                text("INSERT INTO planning.human_segment_assignments(organization_id,assignment_segment_id,schedule_solution_id,employee_id,time_range,normal_minutes,overtime_minutes,work_minutes) VALUES (:org,:segment,:solution,:employee,tstzrange(:start,:finish,'[)'),:minutes,0,:minutes)"),
                {"org": base.organization_id, "segment": assignment_segment, "solution": base.schedule_solution_id, "employee": planned_employee, "start": started_at, "finish": started_at + timedelta(minutes=phase_minutes[0]), "minutes": phase_minutes[0]},
            )
            connection.execute(
                text("INSERT INTO planning.physical_resource_reservations(organization_id,assignment_segment_id,schedule_solution_id,physical_resource_id,time_range,capacity_units,exclusive_guard,usage_mode) VALUES (:org,:segment,:solution,:resource,tstzrange(:start,:finish,'[)'),1,true,'active_use')"),
                {"org": base.organization_id, "segment": assignment_segment, "solution": base.schedule_solution_id, "resource": planned_resource, "start": started_at, "finish": started_at + timedelta(minutes=phase_minutes[0])},
            )
    return UnstartedCase(base, operation_id, phase_ids, planned_employee, actual_employee, planned_resource, actual_resource, physical_requirement, started_at, sum(phase_minutes), operation_result, assignment_segment)


def start_case(engine: Engine, case: UnstartedCase, *, command_id: UUID | None = None) -> StartOperationResult:
    return StartOperationService(PostgresExecutionUnitOfWorkFactory(engine)).execute(
        StartOperation(
            organization_id=case.base.organization_id,
            required_operation_id=case.operation_id,
            phase_id=case.phase_ids[0],
            started_at=case.started_at,
            actor_id=case.base.actor_id,
            command_id=command_id or uuid4(),
            origin_plan_version_id=case.base.plan_version_id if case.operation_plan_result_id else None,
            origin_operation_plan_result_id=case.operation_plan_result_id,
        )
    )
