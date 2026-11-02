from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, create_engine, text


@dataclass(frozen=True)
class SeededCase:
    organization_id: UUID
    other_organization_id: UUID
    plant_id: UUID
    actor_id: UUID
    execution_id: UUID
    phase_id: UUID
    skill_id: UUID
    physical_requirement_id: UUID
    physical_resource_id: UUID
    initial_remaining_revision_id: UUID
    initial_state_revision_id: UUID
    plan_version_id: UUID
    cutoff_at: datetime
    project_id: UUID
    project_lot_id: UUID
    operation_definition_id: UUID
    definition_revision_id: UUID
    schedule_solution_id: UUID
    calendar_id: UUID
    employee_id: UUID
    resource_type_id: UUID
    work_center_id: UUID


@pytest.fixture(scope="session")
def engine() -> Engine:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.fail("TEST_DATABASE_URL is required for PostgreSQL integration tests")
    value = create_engine(database_url, pool_pre_ping=True)
    with value.connect() as connection:
        assert connection.scalar(text("SELECT current_setting('server_version_num')::int")) >= 180000
        assert connection.scalar(text("SELECT 1")) == 1
    yield value
    value.dispose()


@pytest.fixture
def seeded_case(engine: Engine) -> SeededCase:
    return seed_case(engine)


@pytest.fixture(scope="module")
def fixed_acceptance_clock():
    """Historical fixtures publish after V1 starts, before their future work."""
    with pytest.MonkeyPatch.context() as patch:
        instant = datetime(2026, 9, 1, 9, tzinfo=timezone.utc)
        def now():
            nonlocal instant
            instant += timedelta(microseconds=1)
            return instant
        patch.setattr("production_besten.persistence.scheduling_uow._utcnow",
                      now)
        yield now


def seed_case(engine: Engine) -> SeededCase:
    ids = {name: uuid4() for name in (
        "org", "other_org", "calendar", "plant", "actor", "customer", "priority",
        "project", "lot", "skill", "center", "resource_type", "resource", "operation_definition",
        "operation", "phase", "physical_requirement", "definition_revision", "state_revision",
        "scenario", "solution", "plan", "execution", "segment", "usage", "event", "remaining"
    )}
    suffix = ids["org"].hex[:12]
    started = datetime(2026, 9, 1, 8, 0, tzinfo=timezone.utc)
    cutoff = started + timedelta(minutes=420)
    horizon_end = started + timedelta(days=30)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO core.organizations(id,slug,legal_name,display_name,default_timezone) VALUES (:id,:slug,'Test','Test','UTC')"), {"id": ids["org"], "slug": f"test-{suffix}"})
        connection.execute(text("INSERT INTO core.organizations(id,slug,legal_name,display_name,default_timezone) VALUES (:id,:slug,'Other','Other','UTC')"), {"id": ids["other_org"], "slug": f"other-{suffix}"})
        connection.execute(text("INSERT INTO capacity.calendars(id,organization_id,code,name,timezone,calendar_kind) VALUES (:id,:org,:code,'Base','UTC','production')"), {"id": ids["calendar"], "org": ids["org"], "code": f"CAL-{suffix}"})
        connection.execute(text("INSERT INTO core.plants(id,organization_id,code,name,timezone,base_calendar_id) VALUES (:id,:org,:code,'Plant','UTC',:calendar)"), {"id": ids["plant"], "org": ids["org"], "code": f"PL-{suffix}", "calendar": ids["calendar"]})
        connection.execute(text("INSERT INTO core.user_profiles(id,organization_id,auth_subject,display_name,email) VALUES (:id,:org,:subject,'Tester',:email)"), {"id": ids["actor"], "org": ids["org"], "subject": f"test-{suffix}", "email": f"{suffix}@test.invalid"})
        connection.execute(text("INSERT INTO core.customers(id,organization_id,code,display_name) VALUES (:id,:org,:code,'Customer')"), {"id": ids["customer"], "org": ids["org"], "code": f"CU-{suffix}"})
        connection.execute(text("INSERT INTO core.project_priorities(id,organization_id,code,name,rank,is_default) VALUES (:id,:org,:code,'Normal',1,true)"), {"id": ids["priority"], "org": ids["org"], "code": f"PRI-{suffix}"})
        connection.execute(text("INSERT INTO core.projects(id,organization_id,plant_id,customer_id,code,name,priority_id,status) VALUES (:id,:org,:plant,:customer,:code,'Project',:priority,'active')"), {"id": ids["project"], "org": ids["org"], "plant": ids["plant"], "customer": ids["customer"], "code": f"PR-{suffix}", "priority": ids["priority"]})
        connection.execute(text("INSERT INTO core.project_lots(id,organization_id,project_id,code,name,sequence_no,status,hardware_status) VALUES (:id,:org,:project,:code,'Lot',1,'active','ready')"), {"id": ids["lot"], "org": ids["org"], "project": ids["project"], "code": f"LOT-{suffix}"})
        connection.execute(text("INSERT INTO capacity.skills(id,organization_id,code,name) VALUES (:id,:org,:code,'Assembly')"), {"id": ids["skill"], "org": ids["org"], "code": f"SK-{suffix}"})
        connection.execute(text("INSERT INTO capacity.work_centers(id,organization_id,plant_id,code,name,capacity_mode,aggregate_capacity,capacity_unit,base_calendar_id) VALUES (:id,:org,:plant,:code,'Assembly','cumulative',1,'unit',:calendar)"), {"id": ids["center"], "org": ids["org"], "plant": ids["plant"], "code": f"WC-{suffix}", "calendar": ids["calendar"]})
        connection.execute(text("INSERT INTO capacity.physical_resource_types(id,organization_id,code,name,resource_kind,default_scheduling_mode,default_capacity_unit) VALUES (:id,:org,:code,'Bench','bench','exclusive','unit')"), {"id": ids["resource_type"], "org": ids["org"], "code": f"RT-{suffix}"})
        connection.execute(text("INSERT INTO capacity.physical_resources(id,organization_id,plant_id,work_center_id,resource_type_id,code,name,scheduling_mode,capacity_units,capacity_unit,base_calendar_id) VALUES (:id,:org,:plant,:center,:type,:code,'Bench','exclusive',1,'unit',:calendar)"), {"id": ids["resource"], "org": ids["org"], "plant": ids["plant"], "center": ids["center"], "type": ids["resource_type"], "code": f"RES-{suffix}", "calendar": ids["calendar"]})
        connection.execute(text("INSERT INTO production.operation_definitions(id,organization_id,code,name,category) VALUES (:id,:org,:code,'Assembly','assembly')"), {"id": ids["operation_definition"], "org": ids["org"], "code": f"OPD-{suffix}"})
        connection.execute(text("INSERT INTO production.required_operations(id,organization_id,project_id,project_lot_id,operation_definition_id,code,name,status) VALUES (:id,:org,:project,:lot,:definition,:code,'Assembly','active')"), {"id": ids["operation"], "org": ids["org"], "project": ids["project"], "lot": ids["lot"], "definition": ids["operation_definition"], "code": f"OP-{suffix}"})
        connection.execute(text("INSERT INTO production.required_operation_phases(id,organization_id,required_operation_id,sequence_no,code,name,estimate_kind,original_estimate_minutes,split_policy,status) VALUES (:id,:org,:operation,1,'WORK','Work','labor',600,'splittable','active')"), {"id": ids["phase"], "org": ids["org"], "operation": ids["operation"]})
        connection.execute(text("INSERT INTO production.operation_physical_requirements(id,organization_id,required_operation_phase_id,physical_resource_type_id,quantity,capacity_units,usage_mode) VALUES (:id,:org,:phase,:type,1,1,'active_use')"), {"id": ids["physical_requirement"], "org": ids["org"], "phase": ids["phase"], "type": ids["resource_type"]})
        connection.execute(text("INSERT INTO production.product_definition_revisions(id,organization_id,plant_id,revision_no,snapshot_schema_version,canonicalization_version,canonical_snapshot,snapshot_sha256,reason,created_by) VALUES (:id,:org,:plant,1,1,1,'{}',:hash,'test',:actor)"), {"id": ids["definition_revision"], "org": ids["org"], "plant": ids["plant"], "hash": hashlib.sha256(ids["org"].bytes).digest(), "actor": ids["actor"]})
        connection.execute(text("INSERT INTO planning.planning_state_revisions(id,organization_id,plant_id,revision_no,reason,transaction_key,change_summary,created_by) VALUES (:id,:org,:plant,1,'initial',:key,'{}',:actor)"), {"id": ids["state_revision"], "org": ids["org"], "plant": ids["plant"], "key": uuid4(), "actor": ids["actor"]})
        connection.execute(text("INSERT INTO planning.planning_state_heads(plant_id,organization_id,current_revision_id,current_revision_no,updated_by) VALUES (:plant,:org,:revision,1,:actor)"), {"plant": ids["plant"], "org": ids["org"], "revision": ids["state_revision"], "actor": ids["actor"]})
        connection.execute(text("INSERT INTO planning.scenarios(id,organization_id,plant_id,scenario_kind,base_state_revision_id,base_product_definition_revision_id,code,name,status,horizon_range,requested_by) VALUES (:id,:org,:plant,'initial',:state,:definition,:code,'Initial','ready',tstzrange(:start,:finish,'[)'),:actor)"), {"id": ids["scenario"], "org": ids["org"], "plant": ids["plant"], "state": ids["state_revision"], "definition": ids["definition_revision"], "code": f"SC-{suffix}", "start": started, "finish": horizon_end, "actor": ids["actor"]})
        connection.execute(text("INSERT INTO planning.schedule_solutions(id,organization_id,scenario_id,run_no,status,algorithm_version,input_product_definition_revision_id,base_state_revision_id,input_snapshot,input_sha256,started_at,finished_at,horizon_range,solution_sha256,ready_at) VALUES (:id,:org,:scenario,1,'ready','test',:definition,:state,'{}',:input_hash,:start,:start,tstzrange(:start,:finish,'[)'),:solution_hash,:start)"), {"id": ids["solution"], "org": ids["org"], "scenario": ids["scenario"], "definition": ids["definition_revision"], "state": ids["state_revision"], "input_hash": hashlib.sha256(b"input" + ids["org"].bytes).digest(), "solution_hash": hashlib.sha256(b"solution" + ids["org"].bytes).digest(), "start": started, "finish": horizon_end})
        connection.execute(text("INSERT INTO planning.plan_versions(id,organization_id,plant_id,version_no,schedule_solution_id,product_definition_revision_id,planning_state_revision_id,source_scenario_id,status,valid_during,confirmed_at,confirmed_by) VALUES (:id,:org,:plant,1,:solution,:definition,:state,:scenario,'published',tstzrange(:start,NULL,'[)'),:start,:actor)"), {"id": ids["plan"], "org": ids["org"], "plant": ids["plant"], "solution": ids["solution"], "definition": ids["definition_revision"], "state": ids["state_revision"], "scenario": ids["scenario"], "start": started, "actor": ids["actor"]})
        connection.execute(text("UPDATE core.plants SET current_product_definition_revision_id=:definition,current_plan_version_id=:plan WHERE organization_id=:org AND id=:plant"), {"definition": ids["definition_revision"], "plan": ids["plan"], "org": ids["org"], "plant": ids["plant"]})
        connection.execute(text("INSERT INTO execution.operation_executions(id,organization_id,required_operation_id,source_product_definition_revision_id,original_estimate_snapshot,status,origin_plan_version_id,started_at,created_by) VALUES (:id,:org,:operation,:definition,CAST(:snapshot AS jsonb),'running',:plan,:start,:actor)"), {"id": ids["execution"], "org": ids["org"], "operation": ids["operation"], "definition": ids["definition_revision"], "snapshot": '{"labor_minutes":600}', "plan": ids["plan"], "start": started, "actor": ids["actor"]})
        connection.execute(text("INSERT INTO execution.execution_segments(id,organization_id,operation_execution_id,required_operation_phase_id,segment_no,time_range,segment_kind,work_minutes) VALUES (:id,:org,:execution,:phase,1,tstzrange(:start,:finish,'[)'),'work',420)"), {"id": ids["segment"], "org": ids["org"], "execution": ids["execution"], "phase": ids["phase"], "start": started, "finish": cutoff})
        connection.execute(text("INSERT INTO capacity.employees(id,organization_id,plant_id,code,display_name,base_calendar_id) VALUES (:id,:org,:plant,:code,'Worker',:calendar)"), {"id": ids["usage"], "org": ids["org"], "plant": ids["plant"], "code": f"EMP-{suffix}", "calendar": ids["calendar"]})
        connection.execute(text("INSERT INTO execution.actual_resource_usages(organization_id,execution_segment_id,employee_id,time_range,work_minutes,usage_kind) VALUES (:org,:segment,:employee,tstzrange(:start,:finish,'[)'),420,'labor')"), {"org": ids["org"], "segment": ids["segment"], "employee": ids["usage"], "start": started, "finish": cutoff})
        connection.execute(text("INSERT INTO planning.effective_events(id,organization_id,plant_id,event_type_code,payload_schema_version,occurred_at,effective_at,entity_type,entity_id,payload,planning_state_revision_id,source_system,external_reference,created_by) VALUES (:id,:org,:plant,'EXECUTION_STARTED',1,:start,:start,'operation_execution',:execution,'{}',:state,'test',:reference,:actor)"), {"id": ids["event"], "org": ids["org"], "plant": ids["plant"], "start": started, "execution": ids["execution"], "state": ids["state_revision"], "reference": f"start-{suffix}", "actor": ids["actor"]})
        connection.execute(text("INSERT INTO execution.remaining_estimate_revisions(id,organization_id,operation_execution_id,revision_no,cutoff_at,input_mode,raw_input,reason,effective_event_id,planning_state_revision_id,executed_labor_minutes_at_cutoff,remaining_labor_minutes,updated_total_labor_minutes,created_by) VALUES (:id,:org,:execution,1,:start,'remaining_duration',CAST(:raw_input AS jsonb),'initial',:event,:state,0,600,600,:actor)"), {"id": ids["remaining"], "org": ids["org"], "execution": ids["execution"], "start": started, "raw_input": '{"minutes":600}', "event": ids["event"], "state": ids["state_revision"], "actor": ids["actor"]})
        connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    case = SeededCase(
        ids["org"], ids["other_org"], ids["plant"], ids["actor"], ids["execution"],
        ids["phase"], ids["skill"], ids["physical_requirement"], ids["resource"],
        ids["remaining"], ids["state_revision"], ids["plan"], cutoff,
        ids["project"], ids["lot"], ids["operation_definition"], ids["definition_revision"],
        ids["solution"], ids["calendar"], ids["usage"], ids["resource_type"], ids["center"],
    )

    from tests.integration.scheduling_helpers import seed_fixture_release
    seed_fixture_release(engine, case)
    return case
