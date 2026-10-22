from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import text

from production_besten.application.scheduling_services import GenerateScheduleService
from production_besten.domain.scheduling.models import GenerateSchedule
from production_besten.persistence.scheduling_uow import PostgresSchedulingUnitOfWorkFactory


HORIZON_START = datetime(2026, 9, 7, 8, 0, tzinfo=timezone.utc)


def prepare_basic(engine, case, *, minutes=120, split_policy="splittable", usage_mode="active_use"):
    with engine.begin() as connection:
        for weekday in range(1, 6):
            connection.execute(text("""
                INSERT INTO capacity.calendar_working_intervals
                  (organization_id,calendar_id,weekday,local_start,local_end,valid_during)
                VALUES (:org,:calendar,:weekday,'08:00','16:00',daterange('2026-01-01','2027-01-01','[)'))
            """), {"org": case.organization_id, "calendar": case.calendar_id, "weekday": weekday})
        connection.execute(text("""
            INSERT INTO capacity.employee_skills
              (organization_id,employee_id,skill_id,valid_during)
            VALUES (:org,:employee,:skill,daterange('2026-01-01','2027-01-01','[)'))
        """), {"org": case.organization_id, "employee": case.employee_id, "skill": case.skill_id})
        connection.execute(text("""
            INSERT INTO production.operation_labor_requirements
              (organization_id,required_operation_phase_id,skill_id,min_people,max_people,work_minutes)
            VALUES (:org,:phase,:skill,1,1,:minutes)
        """), {"org": case.organization_id, "phase": case.phase_id,
                "skill": case.skill_id, "minutes": minutes})
        connection.execute(text("""
            UPDATE production.required_operation_phases
            SET original_estimate_minutes=:minutes,split_policy=:split,updated_at=now(),row_version=row_version+1
            WHERE organization_id=:org AND id=:phase
        """), {"org": case.organization_id, "phase": case.phase_id,
                "minutes": minutes, "split": split_policy})
        connection.execute(text("""
            UPDATE production.operation_physical_requirements SET usage_mode=:mode
            WHERE organization_id=:org AND id=:requirement
        """), {"org": case.organization_id, "requirement": case.physical_requirement_id,
                "mode": usage_mode})
        connection.execute(text("""
            UPDATE core.project_priorities SET code='NORMAL',rank=3
            WHERE organization_id=:org AND id=(SELECT priority_id FROM core.projects WHERE organization_id=:org AND id=:project)
        """), {"org": case.organization_id, "project": case.project_id})
    return required_operation_id(engine, case)


def required_operation_id(engine, case):
    with engine.connect() as connection:
        return connection.scalar(text("""
            SELECT required_operation_id FROM production.required_operation_phases
            WHERE organization_id=:org AND id=:phase
        """), {"org": case.organization_id, "phase": case.phase_id})


def generate(engine, case, *, project_ids=None, start=HORIZON_START,
             end=None, state_id=None, definition_id=None, failpoint=None):
    end = end or start + timedelta(days=7)
    seed_fixture_release(engine, case)
    command = GenerateSchedule(
        case.organization_id, case.plant_id, case.actor_id,
        f"AUTO-{uuid4().hex}", "Automatic finite-capacity test", start, end,
        definition_id or case.definition_revision_id,
        state_id or current_state(engine, case),
        tuple(project_ids if project_ids is not None else (case.project_id,)),
    )
    service = GenerateScheduleService(PostgresSchedulingUnitOfWorkFactory(engine, failpoint=failpoint))
    return service.execute(command)


def current_state(engine, case):
    with engine.connect() as connection:
        return connection.scalar(text("""
            SELECT current_revision_id FROM planning.planning_state_heads
            WHERE organization_id=:org AND plant_id=:plant
        """), {"org": case.organization_id, "plant": case.plant_id})


def add_employee(connection, case, code, *, skill_id=None):
    employee_id = uuid4()
    connection.execute(text("""
        INSERT INTO capacity.employees
          (id,organization_id,plant_id,code,display_name,base_calendar_id)
        VALUES (:id,:org,:plant,:code,:code,:calendar)
    """), {"id": employee_id, "org": case.organization_id, "plant": case.plant_id,
            "code": code, "calendar": case.calendar_id})
    if skill_id:
        connection.execute(text("""
            INSERT INTO capacity.employee_skills
              (organization_id,employee_id,skill_id,valid_during)
            VALUES (:org,:employee,:skill,daterange('2026-01-01','2027-01-01','[)'))
        """), {"org": case.organization_id, "employee": employee_id, "skill": skill_id})
    return employee_id


def add_resource(connection, case, code, *, resource_type_id=None, center_id=None,
                 scheduling_mode="exclusive", capacity_units=1):
    resource_id = uuid4()
    connection.execute(text("""
        INSERT INTO capacity.physical_resources
          (id,organization_id,plant_id,work_center_id,resource_type_id,code,name,
           scheduling_mode,capacity_units,capacity_unit,base_calendar_id)
        VALUES (:id,:org,:plant,:center,:type,:code,:code,:mode,:capacity,'unit',:calendar)
    """), {"id": resource_id, "org": case.organization_id, "plant": case.plant_id,
            "center": center_id or case.work_center_id,
            "type": resource_type_id or case.resource_type_id, "code": code,
            "mode": scheduling_mode, "capacity": capacity_units,
            "calendar": case.calendar_id})
    return resource_id


def add_operation(connection, case, code, *, project_id=None, lot_id=None,
                  minutes=120, skill_id=None, resource_type_id=None,
                  sequence_no=1, split_policy="splittable", settings="{}",
                  capacity_units=1, quantity=1, work_center_id=None):
    operation_id, phase_id = uuid4(), uuid4()
    project_id = project_id or case.project_id
    if lot_id is None:
        lot_id = connection.scalar(text("SELECT id FROM core.project_lots WHERE organization_id=:org AND project_id=:project ORDER BY sequence_no LIMIT 1"), {"org": case.organization_id, "project": project_id})
    connection.execute(text("""
        INSERT INTO production.required_operations
          (id,organization_id,project_id,project_lot_id,operation_definition_id,code,name,status,settings)
        VALUES (:id,:org,:project,:lot,:definition,:code,:code,'active',CAST(:settings AS jsonb))
    """), {"id": operation_id, "org": case.organization_id, "project": project_id,
            "lot": lot_id, "definition": case.operation_definition_id, "code": code,
            "settings": settings})
    connection.execute(text("""
        INSERT INTO production.required_operation_phases
          (id,organization_id,required_operation_id,sequence_no,code,name,estimate_kind,
           original_estimate_minutes,split_policy,status)
        VALUES (:id,:org,:operation,:sequence,:code,:code,'labor',:minutes,:split,'active')
    """), {"id": phase_id, "org": case.organization_id, "operation": operation_id,
            "sequence": sequence_no, "code": f"{code}-P{sequence_no}",
            "minutes": minutes, "split": split_policy})
    if skill_id:
        connection.execute(text("""
            INSERT INTO production.operation_labor_requirements
              (organization_id,required_operation_phase_id,skill_id,min_people,max_people,work_minutes)
            VALUES (:org,:phase,:skill,1,1,:minutes)
        """), {"org": case.organization_id, "phase": phase_id,
                "skill": skill_id, "minutes": minutes})
    if resource_type_id or work_center_id:
        connection.execute(text("""
            INSERT INTO production.operation_physical_requirements
              (organization_id,required_operation_phase_id,physical_resource_type_id,
               work_center_id,quantity,capacity_units,usage_mode)
            VALUES (:org,:phase,:type,:center,:quantity,:capacity,'active_use')
        """), {"org": case.organization_id, "phase": phase_id,
                "type": resource_type_id, "center": work_center_id,
                "quantity": quantity, "capacity": capacity_units})
    return operation_id, phase_id


def solution_segments(engine, solution_id):
    with engine.connect() as connection:
        return connection.execute(text("""
            SELECT s.segment_no,lower(s.time_range) AS start_at,upper(s.time_range) AS end_at,
                   s.normal_minutes,s.overtime_minutes,s.work_minutes,
                   p.required_operation_phase_id
            FROM planning.assignment_segments s
            JOIN planning.planned_phase_assignments a
              ON a.organization_id=s.organization_id AND a.id=s.planned_phase_assignment_id
            JOIN planning.phase_plan_results p
              ON p.organization_id=a.organization_id AND p.id=a.phase_plan_result_id
            WHERE s.schedule_solution_id=:solution ORDER BY start_at,p.required_operation_phase_id
        """), {"solution": solution_id}).mappings().all()


def seed_fixture_release(engine, case, *, include_intake=False):
    """Explicit release facts for historical scheduling fixtures, never runtime behavior.

    New release tests invoke GenerateScheduleService directly and do not use this
    fixture bootstrap. Intake projects remain unreleased unless requested by the
    earlier editor regression fixtures after freezing their productive definition.
    """
    import json
    from production_besten.persistence.production_release_uow import definition_digest
    with engine.begin() as conn:
        snapshot=conn.scalar(text('SELECT d.canonical_snapshot FROM core.plants p JOIN production.product_definition_revisions d ON d.organization_id=p.organization_id AND d.id=p.current_product_definition_revision_id WHERE p.id=:plant'),{'plant':case.plant_id}) or {}
        projects=conn.execute(text("SELECT p.id,p.code,EXISTS(SELECT 1 FROM audit.audit_entries a WHERE a.organization_id=p.organization_id AND a.entity_id=p.id AND a.action_code='PROJECT_INTAKE_CREATE') AS intake FROM core.projects p WHERE organization_id=:org AND plant_id=:plant"),{'org':case.organization_id,'plant':case.plant_id}).mappings().all()
        for project in projects:
            definition=next((p for p in snapshot.get('projects',[]) if p['code']==project['code']),None)
            if project['intake'] and (not include_intake or not definition or not any(o.get('phases') for l in definition.get('lots',[]) for o in l['operations'])):continue
            digest=definition_digest(definition)
            last=conn.execute(text("SELECT event_type_code,payload FROM planning.effective_events WHERE organization_id=:org AND entity_id=:project AND event_type_code IN ('PROJECT_PRODUCTION_RELEASED','PROJECT_PRODUCTION_WITHDRAWN') ORDER BY occurred_at DESC,created_at DESC LIMIT 1"),{'org':case.organization_id,'project':project['id']}).mappings().one_or_none()
            if last and last['event_type_code']=='PROJECT_PRODUCTION_RELEASED' and last['payload']['project_definition_sha256']==digest:continue
            conn.execute(text("INSERT INTO planning.effective_events(organization_id,plant_id,event_type_code,payload_schema_version,occurred_at,effective_at,entity_type,entity_id,payload,source_system,created_by) VALUES (:org,:plant,'PROJECT_PRODUCTION_RELEASED',1,now(),now(),'project',:project,CAST(:payload AS jsonb),'test_fixture',:actor)"),{'org':case.organization_id,'plant':case.plant_id,'project':project['id'],'actor':case.actor_id,'payload':json.dumps({'project_definition_sha256':digest,'fixture_bootstrap':True})})
