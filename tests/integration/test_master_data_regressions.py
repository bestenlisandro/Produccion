from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, time, timedelta, timezone
from time import perf_counter
from uuid import UUID, uuid4
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, text

from production_besten.api.app import create_app
from production_besten.domain.errors import EntityNotFound, IdempotencyConflict, SchedulingBaseStale
from production_besten.persistence.api_queries import PostgresApiQueries
from production_besten.persistence.master_data_uow import PostgresMasterDataUnitOfWorkFactory, _digest
from production_besten.persistence.scheduling_uow import PostgresSchedulingUnitOfWorkFactory
from production_besten.application.replanning_services import AcceptReplanService
from production_besten.domain.replanning import AcceptReplan
from tests.integration.test_master_data import command, service, calendar_payload, person_payload
from tests.integration.scheduling_helpers import (
    HORIZON_START, prepare_basic, generate, add_operation, add_resource, solution_segments, current_state,
)
from tests.integration.test_operational_frontend_api import _publish_operation


def snapshot(engine, case):
    with PostgresMasterDataUnitOfWorkFactory(engine)() as uow:
        return uow.snapshot(case.organization_id, case.plant_id)


def client(engine, case):
    value = TestClient(create_app(engine=engine, enable_dev_context=True))
    value.headers.update({"X-Dev-User-Id": str(case.actor_id),
        "X-Dev-Organization-Id": str(case.organization_id), "X-Dev-Plant-Id": str(case.plant_id),
        "Idempotency-Key": str(uuid4())})
    return value


def center_payload(case, capacity=2):
    return {"code": "CENTER", "name": "Center", "capacity_mode": "cumulative",
        "aggregate_capacity": capacity, "capacity_unit": "unit", "base_calendar_id": case.calendar_id}


def resource_payload(case, center=None):
    return {"code": "RESOURCE", "name": "Resource", "work_center_id": center or case.work_center_id,
        "resource_type_id": case.resource_type_id, "scheduling_mode": "exclusive", "capacity_units": 1,
        "capacity_unit": "unit", "is_mobile": False, "base_calendar_id": case.calendar_id}


@pytest.mark.parametrize("entity", ["person", "skill", "work_center", "resource", "calendar"])
def test_entity_update_deactivate_reactivate_retains_history(engine, seeded_case, entity):
    case = seeded_case
    payloads = {"person": person_payload(case), "skill": {"code": "SKILL", "name": "Skill"},
                "work_center": center_payload(case), "resource": resource_payload(case),
                "calendar": calendar_payload()}
    app = service(engine)
    created = app.execute(command(case, entity, "create", payloads[entity]))
    identifier = created.entity["id"]
    updated_payload = {**payloads[entity], "code": "EDITED"}
    edited = app.execute(command(case, entity, "update", updated_payload, entity_id=identifier, version=1))
    assert edited.entity["code"] == "EDITED"
    for version, status in ((2, "inactive"), (3, "active")):
        changed = app.execute(command(case, entity, "set_status", {"status": status}, entity_id=identifier, version=version))
        assert changed.entity["status"] == status
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM audit.audit_entries WHERE organization_id=:org AND entity_id=:id"),
            {"org": case.organization_id, "id": identifier}) == 4


@pytest.mark.parametrize("capacity", [0, -1, None])
def test_invalid_center_capacity_http_422(engine, seeded_case, capacity):
    response = client(engine, seeded_case).post("/master-data/work-centers", json={
        **center_payload(seeded_case, capacity), "base_calendar_id": str(seeded_case.calendar_id)})
    assert response.status_code == 422


def test_resource_moves_to_a_different_center(engine, seeded_case):
    case = seeded_case
    app = service(engine)
    center = app.execute(command(case, "work_center", "create", center_payload(case)))
    created = app.execute(command(case, "resource", "create", resource_payload(case)))
    changed = app.execute(command(case, "resource", "update", resource_payload(case, center.entity["id"]),
        entity_id=created.entity["id"], version=1))
    assert changed.entity["work_center_id"] == center.entity["id"]
    with engine.connect() as conn:
        assert str(conn.scalar(text("SELECT work_center_id FROM capacity.physical_resources WHERE id=:id"),
            {"id": created.entity["id"]})) == center.entity["id"]


def test_exception_moves_calendar_uses_target_timezone_and_rejects_foreign(engine, seeded_case):
    case = seeded_case
    app = service(engine)
    calendar = app.execute(command(case, "calendar", "create", calendar_payload() | {"timezone": "Asia/Tokyo"}))
    body = {"calendar_id": case.calendar_id, "exception_date": date(2026, 12, 24),
            "effect": "replace", "local_start": time(8), "local_end": time(12), "reason": "Special", "capacity_factor": .5}
    created = app.execute(command(case, "calendar_exception", "create", body))
    changed = app.execute(command(case, "calendar_exception", "update", body | {"calendar_id": calendar.entity["id"]},
        entity_id=created.entity["id"], version=1))
    assert changed.entity["calendar_id"] == calendar.entity["id"]
    with engine.connect() as conn:
        start = conn.scalar(text("SELECT lower(time_range) FROM capacity.calendar_exceptions WHERE id=:id"), {"id": created.entity["id"]})
    assert start.astimezone(timezone.utc) == datetime(2026, 12, 23, 23, tzinfo=timezone.utc)
    with pytest.raises(EntityNotFound):
        app.execute(command(case, "calendar_exception", "update", body | {"calendar_id": uuid4()},
            entity_id=created.entity["id"], version=2))


@pytest.mark.parametrize("different", ["plant", "actor", "payload"])
def test_contextual_digest_prevents_cross_context_replay(engine, seeded_case, different):
    case = seeded_case
    app = service(engine)
    original = command(case, "skill", "create", {"code": "IDEMP", "name": "Skill"})
    result = app.execute(original)
    assert app.execute(original).idempotent_replay
    assert current_state(engine, case) != case.initial_state_revision_id
    if different == "plant":
        plant = uuid4()
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO core.plants(id,organization_id,code,name,timezone,base_calendar_id) VALUES (:id,:org,'OTHER','Other','UTC',:cal)"),
                {"id": plant, "org": case.organization_id, "cal": case.calendar_id})
        changed = replace(original, plant_id=plant)
    elif different == "actor":
        changed = replace(original, actor_id=uuid4())
    else:
        changed = replace(original, payload={"code": "OTHER", "name": "Other"})
    with pytest.raises(IdempotencyConflict):
        app.execute(changed)
    assert result.entity["code"] == "IDEMP"


def test_legacy_replay_is_compatible_only_when_context_can_be_proved(engine, seeded_case):
    case = seeded_case
    original = command(case, "person", "create", person_payload(case))
    result = service(engine).execute(original)
    with engine.begin() as conn:
        conn.execute(text("UPDATE audit.audit_entries SET metadata=jsonb_build_object('command_hash',CAST(:hash AS text)) WHERE request_id=:id"),
            {"hash": _digest(original, UUID(result.entity["id"]), legacy=True), "id": original.command_id})
    assert service(engine).execute(original).idempotent_replay
    with pytest.raises(IdempotencyConflict):
        service(engine).execute(replace(original, actor_id=uuid4()))


def test_windows_edit_preserves_past_and_future_schedule(engine, seeded_case):
    case = seeded_case
    app = service(engine)
    def define(day, start, version):
        return app.execute(command(case, "calendar_windows", "define_windows", {"effective_from": day,
            "windows": [{"weekday": 1, "local_start": time(start), "local_end": time(start + 1)}]},
            entity_id=case.calendar_id, version=version))
    define(date(2026, 1, 1), 8, 1)
    define(date(2026, 11, 1), 10, 2)
    define(date(2026, 6, 1), 9, 3)
    define(date(2026, 6, 1), 11, 4)
    records = snapshot(engine, case)["calendar_windows"]
    assert [(r["local_start"], r["valid_from"], r["valid_to"]) for r in sorted(records, key=lambda r:r["valid_from"])] == [
        ("08:00:00", "2026-01-01", "2026-06-01"), ("11:00:00", "2026-06-01", "2026-11-01"), ("10:00:00", "2026-11-01", None)]


def test_skill_history_is_partitioned_and_audited_before_after(engine, seeded_case):
    case = seeded_case
    app = service(engine)
    first = command(case, "person_skill", "assign_skill", {"skill_id": case.skill_id,
        "valid_from": date(2026, 1, 1), "valid_to": date(2027, 1, 1), "level": 1}, entity_id=case.employee_id)
    app.execute(first)
    second = command(case, "person_skill", "assign_skill", {"skill_id": case.skill_id,
        "valid_from": date(2026, 6, 1), "valid_to": date(2026, 7, 1), "level": 2}, entity_id=case.employee_id)
    app.execute(second)
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT valid_during,level FROM capacity.employee_skills WHERE employee_id=:id AND enabled ORDER BY lower(valid_during)"), {"id": case.employee_id}).all()
        audit = conn.execute(text("SELECT before_data,after_data FROM audit.audit_entries WHERE request_id=:id"), {"id": second.command_id}).one()
    assert [(r.valid_during.lower, r.valid_during.upper, int(r.level)) for r in rows] == [
        (date(2026,1,1),date(2026,6,1),1), (date(2026,6,1),date(2026,7,1),2), (date(2026,7,1),date(2027,1,1),1)]
    assert len(audit.before_data["assignments"]) == 1
    assert len(audit.after_data["skill_history"]["assignments"]) == 3


def test_skill_removal_closes_current_validity_without_erasing_past(engine, seeded_case):
    case = seeded_case
    app = service(engine)
    app.execute(command(case, "person_skill", "assign_skill", {"skill_id": case.skill_id,
        "valid_from": date(2000,1,1), "valid_to": None}, entity_id=case.employee_id))
    app.execute(command(case, "person_skill", "remove_skill", {"skill_id": case.skill_id}, entity_id=case.employee_id))
    with engine.connect() as conn:
        row = conn.execute(text("SELECT enabled,valid_during FROM capacity.employee_skills WHERE employee_id=:id"), {"id": case.employee_id}).one()
    assert row.enabled and row.valid_during.lower == date(2000,1,1)
    assert row.valid_during.upper == date.today()  # seed plant is UTC
    assert snapshot(engine, case)["people"][0]["skills"] == []


@pytest.mark.parametrize("kind", ["person", "resource", "work_center", "skill", "calendar", "resource_type"])
def test_inactive_master_is_excluded_from_future_scheduling(engine, seeded_case, kind):
    case = seeded_case
    prepare_basic(engine, case)
    identifiers = {"person":case.employee_id, "resource":case.physical_resource_id,
        "work_center":case.work_center_id, "skill":case.skill_id, "calendar":case.calendar_id}
    if kind == "resource_type":
        with engine.begin() as conn:
            conn.execute(text("UPDATE capacity.physical_resource_types SET status='inactive' WHERE id=:id"), {"id":case.resource_type_id})
    else:
        service(engine).execute(command(case, kind, "set_status", {"status":"inactive"}, entity_id=identifiers[kind], version=1))
    if kind == "calendar":
        from production_besten.domain.errors import InvalidSchedulingInput
        with pytest.raises(InvalidSchedulingInput, match="calendar"):
            generate(engine, case)
    else:
        result = generate(engine, case)
        assert result.blocked_phases == 1


@pytest.mark.parametrize("kind", ["person", "person_skill", "resource", "work_center", "capacity", "calendar", "calendar_status", "plant_calendar"])
def test_current_unchanged_reconciliation_persisted_and_scenario_stale(engine, seeded_case, kind):
    case = seeded_case
    prepare_basic(engine, case)
    operation, _ = _publish_operation(engine, case)
    scenario = generate(engine, case)
    old_state = current_state(engine, case)
    with engine.connect() as conn:
        old_plan = conn.execute(text("SELECT row_to_json(p) FROM planning.plan_versions p WHERE id=:id"), {"id":case.plan_version_id}).scalar()
        old_segments = conn.execute(text("SELECT row_to_json(s) FROM planning.assignment_segments s WHERE schedule_solution_id=:id ORDER BY id"), {"id":case.schedule_solution_id}).scalars().all()
    app = service(engine)
    ids = {"person":case.employee_id, "resource":case.physical_resource_id, "work_center":case.work_center_id}
    if kind in ids:
        result = app.execute(command(case, kind, "set_status", {"status":"inactive"}, entity_id=ids[kind], version=1))
    elif kind == "person_skill":
        result = app.execute(command(case, "person_skill", "remove_skill", {"skill_id":case.skill_id}, entity_id=case.employee_id))
    elif kind == "capacity":
        with engine.connect() as conn:
            row = conn.execute(text("SELECT * FROM capacity.work_centers WHERE id=:id"), {"id":case.work_center_id}).mappings().one()
        result = app.execute(command(case, "work_center", "update", {key:row[key] for key in center_payload(case)} | {"aggregate_capacity":.5}, entity_id=case.work_center_id, version=1))
    elif kind == "calendar_status":
        result = app.execute(command(case, "calendar", "set_status", {"status":"inactive"}, entity_id=case.calendar_id, version=1))
    elif kind == "plant_calendar":
        new_calendar = app.execute(command(case,"calendar","create",calendar_payload()))
        with engine.connect() as conn:
            row = conn.execute(text("SELECT * FROM core.plants WHERE id=:id"), {"id":case.plant_id}).mappings().one()
        result = app.execute(command(case,"plant","update", {key:row[key] for key in ("code","name","timezone","base_calendar_id","communication_threshold_business_days")} | {"base_calendar_id":new_calendar.entity["id"]}, entity_id=case.plant_id,version=1))
    else:
        result = app.execute(command(case,"calendar_windows","define_windows", {"effective_from":date(2026,9,1),"windows":[]}, entity_id=case.calendar_id,version=1))
    assert result.plan_requires_reconciliation and result.current_usage_count == 1
    assert current_state(engine,case) != old_state
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT current_plan_version_id FROM core.plants WHERE id=:id"), {"id":case.plant_id}) == case.plan_version_id
        assert conn.scalar(text("SELECT row_to_json(p) FROM planning.plan_versions p WHERE id=:id"), {"id":case.plan_version_id}) == old_plan
        assert conn.execute(text("SELECT row_to_json(s) FROM planning.assignment_segments s WHERE schedule_solution_id=:id ORDER BY id"), {"id":case.schedule_solution_id}).scalars().all() == old_segments
    assert PostgresApiQueries(engine).operation_detail(case.organization_id, case.plant_id, operation)["plan_requires_reconciliation"]
    with pytest.raises(SchedulingBaseStale):
        AcceptReplanService(PostgresSchedulingUnitOfWorkFactory(engine)).execute(AcceptReplan(
            case.organization_id,case.plant_id,case.actor_id,uuid4(),scenario.scenario_id,1,"test"))


def test_plant_base_calendar_usage_is_actual_distinct_operations(engine, seeded_case):
    case = seeded_case
    prepare_basic(engine,case)
    _publish_operation(engine,case)
    app=service(engine)
    other=app.execute(command(case,"calendar","create",calendar_payload()))
    with engine.begin() as conn:
        for table in ("employees","physical_resources","work_centers"):
            conn.execute(text(f"UPDATE capacity.{table} SET base_calendar_id=:cal WHERE organization_id=:org"), {"cal":other.entity["id"],"org":case.organization_id})
    data=snapshot(engine,case)
    calendar=next(c for c in data["calendars"] if c["id"]==str(case.calendar_id))
    assert calendar["current_usage_count"]==1
    assert data["people"][0]["current_usage_count"]==1
    assert data["resources"][0]["current_usage_count"]==1


@pytest.mark.parametrize("capacity,simultaneous", [(1,1),(2,2),(3,3)])
def test_nominal_center_capacity_api_db_scheduler_end_to_end(engine,seeded_case,capacity,simultaneous):
    case=seeded_case
    prepare_basic(engine,case,minutes=120)
    api=client(engine,case)
    payload=center_payload(case,capacity) | {"base_calendar_id":str(case.calendar_id),"expected_row_version":1}
    response=api.patch(f"/master-data/work-centers/{case.work_center_id}",json=payload)
    assert response.status_code==200,response.text
    with engine.begin() as conn:
        assert conn.scalar(text("SELECT aggregate_capacity FROM capacity.work_centers WHERE id=:id"),{"id":case.work_center_id})==capacity
        for index in range(3):
            add_resource(conn,case,f"R-{index}")
            add_operation(conn,case,f"OP-{index}",resource_type_id=case.resource_type_id)
    result=generate(engine,case)
    starts=[row["start_at"] for row in solution_segments(engine,result.solution_id)]
    assert starts.count(HORIZON_START)==simultaneous
    assert sum(start>HORIZON_START for start in starts)==4-simultaneous
    with engine.connect() as conn:
        saved=conn.scalar(text("SELECT input_snapshot FROM planning.schedule_solutions WHERE id=:id"),{"id":result.solution_id})
    assert saved["capacity_and_state"]["work_centers"][str(case.work_center_id)]["capacity_units"]==capacity


def test_snapshot_benchmark_and_constant_query_count(engine,seeded_case,capsys):
    case=seeded_case
    with engine.begin() as conn:
        for index in range(49):
            conn.execute(text("INSERT INTO capacity.employees(organization_id,plant_id,code,display_name,base_calendar_id) VALUES (:org,:plant,:code,:code,:cal)"),{"org":case.organization_id,"plant":case.plant_id,"code":f"P-{index}","cal":case.calendar_id})
        for index in range(19):
            conn.execute(text("INSERT INTO capacity.skills(organization_id,code,name) VALUES (:org,:code,:code)"),{"org":case.organization_id,"code":f"S-{index}"})
            add_resource(conn,case,f"R-{index}")
    queries=[]
    def record(*args):queries.append(args[2])
    event.listen(engine,"before_cursor_execute",record)
    try:
        started=perf_counter()
        response=client(engine,case).get("/master-data/snapshot")
        elapsed=(perf_counter()-started)*1000
    finally:event.remove(engine,"before_cursor_execute",record)
    assert response.status_code==200
    data=response.json()
    assert (len(data["people"]),len(data["skills"]),len(data["resources"]))==(50,20,20)
    assert len(queries)<=15
    print(f"MASTER_DATA_POSTGRES_BENCHMARK endpoint_ms={elapsed:.2f} payload_bytes={len(response.content)} sql_queries={len(queries)} people=50 skills=20 resources=20")


@pytest.mark.parametrize("kind", ["person", "work_center", "resource", "plant"])
def test_calendar_assignment_and_plant_timezone(engine,seeded_case,kind):
    case=seeded_case
    app=service(engine)
    calendar=app.execute(command(case,"calendar","create",calendar_payload() | {"timezone":"America/Argentina/Buenos_Aires"}))
    if kind=="person":payload=person_payload(case)
    elif kind=="work_center":payload=center_payload(case)
    elif kind=="resource":payload=resource_payload(case)
    else:
        data=snapshot(engine,case)["plant"]
        payload={key:data[key] for key in ("code","name","timezone","base_calendar_id","communication_threshold_business_days")}
        payload["timezone"]="America/Argentina/Buenos_Aires"
    payload["base_calendar_id"]=calendar.entity["id"]
    result=app.execute(command(case,kind,"update" if kind=="plant" else "create",payload,
        entity_id=case.plant_id if kind=="plant" else None,version=1 if kind=="plant" else None))
    assert result.entity["base_calendar_id"]==calendar.entity["id"]
    if kind=="plant":assert result.entity["timezone"]=="America/Argentina/Buenos_Aires"


@pytest.mark.parametrize("zone,expected", [("America/Argentina/Buenos_Aires",date(2026,10,21)),("Asia/Tokyo",date(2026,10,22))])
def test_backend_skill_default_uses_plant_day_near_midnight(engine,seeded_case,monkeypatch,zone,expected):
    import production_besten.persistence.master_data_uow as module
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None):
            instant=datetime(2026,10,22,1,30,tzinfo=timezone.utc)
            return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)
    monkeypatch.setattr(module,"datetime",Clock)
    case=seeded_case
    with engine.begin() as conn:
        conn.execute(text("UPDATE core.plants SET timezone=:zone WHERE id=:id"),{"zone":zone,"id":case.plant_id})
    result=service(engine).execute(command(case,"person_skill","assign_skill",{"skill_id":case.skill_id},entity_id=case.employee_id))
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT lower(valid_during) FROM capacity.employee_skills WHERE id=:id"),{"id":result.entity["id"]})==expected
    assert snapshot(engine,case)["people"][0]["skills"]


@pytest.mark.parametrize("target",["people","skills","work-centers","resources","calendars","calendar-exceptions"])
def test_http_foreign_or_missing_targets_return_404(engine,seeded_case,target):
    api=client(engine,seeded_case)
    case=seeded_case
    data={"people":person_payload(case),"skills":{"code":"X","name":"X"},
          "work-centers":center_payload(case),"resources":resource_payload(case),"calendars":calendar_payload(),
          "calendar-exceptions":{"calendar_id":case.calendar_id,"exception_date":"2026-12-24","effect":"remove"}}[target]
    data=json.loads(json.dumps(data,default=str)) | {"expected_row_version":1}
    assert api.patch(f"/master-data/{target}/{uuid4()}",json=data).status_code==404


def test_http_version_conflict_and_rollback_have_no_revision_side_effects(engine,seeded_case):
    case=seeded_case
    api=client(engine,case)
    state=current_state(engine,case)
    payload=json.loads(json.dumps(person_payload(case),default=str)) | {"expected_row_version":99}
    response=api.patch(f"/master-data/people/{case.employee_id}",json=payload)
    assert response.status_code==409
    assert current_state(engine,case)==state
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM audit.audit_entries WHERE organization_id=:org"),{"org":case.organization_id})==0


def test_unused_creation_stales_scenarios_without_claiming_current_impact(engine,seeded_case):
    case=seeded_case
    prepare_basic(engine,case)
    operation,_=_publish_operation(engine,case)
    scenario=generate(engine,case)
    result=service(engine).execute(command(case,"person","create",person_payload(case)))
    assert not result.plan_requires_reconciliation
    assert not PostgresApiQueries(engine).operation_detail(case.organization_id,case.plant_id,operation)["plan_requires_reconciliation"]
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT status FROM planning.scenarios WHERE id=:id"),{"id":scenario.scenario_id})=="stale"


@pytest.mark.parametrize("exception",[False,True])
def test_calendar_capacity_factor_reaches_scheduler(engine,seeded_case,exception):
    case=seeded_case
    prepare_basic(engine,case,minutes=120)
    with engine.begin() as conn:
        conn.execute(text("UPDATE capacity.work_centers SET aggregate_capacity=2 WHERE id=:id"),{"id":case.work_center_id})
        add_resource(conn,case,"SECOND")
        add_operation(conn,case,"SECOND",resource_type_id=case.resource_type_id)
        if not exception:
            conn.execute(text("UPDATE capacity.calendar_working_intervals SET capacity_factor=.5 WHERE calendar_id=:id"),{"id":case.calendar_id})
    if exception:
        service(engine).execute(command(case,"calendar_exception","create",{"calendar_id":case.calendar_id,
            "exception_date":HORIZON_START.date(),"effect":"replace","local_start":time(8),"local_end":time(16),"capacity_factor":.5}))
    starts=[row["start_at"] for row in solution_segments(engine,generate(engine,case).solution_id)]
    assert starts.count(HORIZON_START)==1
    assert starts.count(HORIZON_START+timedelta(hours=2))==1


@pytest.mark.parametrize("day,start,finish",[(date(2026,3,8),time(2,30),time(3,30)),(date(2026,11,1),time(1,30),time(2,30))])
def test_exception_rejects_nonexistent_or_ambiguous_dst_times(engine,seeded_case,day,start,finish):
    from production_besten.domain.master_data import InvalidMasterData
    case=seeded_case
    app=service(engine)
    calendar=app.execute(command(case,"calendar","create",calendar_payload()|{"timezone":"America/New_York"}))
    with pytest.raises(InvalidMasterData,match="local time"):
        app.execute(command(case,"calendar_exception","create",{"calendar_id":calendar.entity["id"],
            "exception_date":day,"effect":"replace","local_start":start,"local_end":finish}))


def test_edit_window_respects_finite_end_even_without_future_start(engine,seeded_case):
    case=seeded_case
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO capacity.calendar_working_intervals(organization_id,calendar_id,weekday,local_start,local_end,valid_during) VALUES (:org,:cal,1,'08:00','12:00',daterange('2026-01-01','2026-06-01','[)'))"),{"org":case.organization_id,"cal":case.calendar_id})
    service(engine).execute(command(case,"calendar_windows","define_windows",{"effective_from":date(2026,3,1),
        "windows":[{"weekday":1,"local_start":time(9),"local_end":time(12)}]},entity_id=case.calendar_id,version=1))
    windows=snapshot(engine,case)["calendar_windows"]
    assert all(row["valid_to"] is not None for row in windows)
    assert next(row for row in windows if row["valid_from"]=="2026-03-01")["valid_to"]=="2026-06-01"


def test_actual_occupation_consumes_center_capacity_even_with_another_free_station(engine,seeded_case):
    case=seeded_case
    prepare_basic(engine,case,minutes=120)
    with engine.begin() as conn:
        add_resource(conn,case,"SECOND")
        conn.execute(text("""INSERT INTO planning.physical_occupations
            (organization_id,operation_execution_id,project_lot_id,required_operation_phase_id,physical_resource_id,source_kind,time_range)
            VALUES (:org,:execution,:lot,:phase,:resource,'actual',tstzrange(:start,:finish,'[)'))"""),
            {"org":case.organization_id,"execution":case.execution_id,"lot":case.project_lot_id,"phase":case.phase_id,
             "resource":case.physical_resource_id,"start":HORIZON_START,"finish":HORIZON_START+timedelta(hours=2)})
    result=generate(engine,case)
    assert solution_segments(engine,result.solution_id)[0]["start_at"]==HORIZON_START+timedelta(hours=2)


def test_numeric_noop_does_not_invalidate_current(engine,seeded_case):
    case=seeded_case
    with engine.connect() as conn:
        row=conn.execute(text("SELECT * FROM capacity.work_centers WHERE id=:id"),{"id":case.work_center_id}).mappings().one()
    state=current_state(engine,case)
    service(engine).execute(command(case,"work_center","update",{key:row[key] for key in center_payload(case)}|{"aggregate_capacity":1},entity_id=case.work_center_id,version=1))
    assert current_state(engine,case)==state


def test_exported_openapi_matches_real_fastapi(engine):
    from pathlib import Path
    expected=json.loads((Path(__file__).resolve().parents[2]/"frontend/openapi.json").read_text(encoding="utf-8"))
    actual=create_app(engine=engine,enable_dev_context=True).openapi()
    assert actual==expected
    assert "/master-data/calendars/{entity_id}/status" in actual["paths"]
