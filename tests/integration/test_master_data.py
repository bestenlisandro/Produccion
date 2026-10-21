from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, time
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError

from production_besten.api.app import create_app
from production_besten.application.master_data_services import (
    MasterDataCommandService, MasterDataQueryService,
)
from production_besten.domain.errors import EntityNotFound, IdempotencyConflict
from production_besten.domain.master_data import (
    InvalidMasterData, MasterDataCommand, MasterDataConflict,
)
from production_besten.persistence.master_data_uow import PostgresMasterDataUnitOfWorkFactory
from tests.integration.conftest import SeededCase


def service(engine: Engine) -> MasterDataCommandService:
    return MasterDataCommandService(PostgresMasterDataUnitOfWorkFactory(engine))


def command(case: SeededCase, entity_type, action, payload, *, entity_id=None,
            command_id=None, version=None, organization_id=None):
    return MasterDataCommand(
        command_id or uuid4(), organization_id or case.organization_id,
        case.plant_id, case.actor_id, action, entity_type, payload,
        entity_id, version,
    )


def calendar_payload(code="CAL-NEW"):
    return {"code": code, "name": "Calendario nuevo",
            "timezone": "America/Argentina/Buenos_Aires",
            "calendar_kind": "production", "description": "Turno"}


def person_payload(case: SeededCase, code="EMP-NEW"):
    return {"code": code, "display_name": "Persona Nueva",
            "base_calendar_id": case.calendar_id,
            "default_work_center_id": case.work_center_id}


def test_snapshot_reuses_all_existing_master_structures(
    engine: Engine, seeded_case: SeededCase
) -> None:
    data = MasterDataQueryService(PostgresMasterDataUnitOfWorkFactory(engine)).snapshot(
        seeded_case.organization_id, seeded_case.plant_id
    )
    assert data["dev_only"]
    assert data["people"] and data["skills"] and data["work_centers"]
    assert data["resources"] and data["calendars"] and data["resource_types"]
    assert data["plant"]["id"] == str(seeded_case.plant_id)


def test_person_create_edit_status_replay_and_tenant_isolation(
    engine: Engine, seeded_case: SeededCase
) -> None:
    app = service(engine)
    create = command(seeded_case, "person", "create", person_payload(seeded_case))
    first = app.execute(create)
    replay = app.execute(create)
    assert replay.entity["id"] == first.entity["id"] and replay.idempotent_replay
    person_id = first.entity["id"]
    updated = app.execute(command(
        seeded_case, "person", "update",
        {**person_payload(seeded_case), "display_name": "Persona Editada"},
        entity_id=person_id, version=1,
    ))
    assert updated.entity["display_name"] == "Persona Editada"
    inactive = app.execute(command(
        seeded_case, "person", "set_status", {"status": "inactive"},
        entity_id=person_id, version=2,
    ))
    assert inactive.entity["status"] == "inactive"
    active = app.execute(command(
        seeded_case, "person", "set_status", {"status": "active"},
        entity_id=person_id, version=3,
    ))
    assert active.entity["status"] == "active"
    with pytest.raises(EntityNotFound):
        app.execute(command(
            seeded_case, "person", "update", person_payload(seeded_case),
            entity_id=person_id, version=4,
            organization_id=seeded_case.other_organization_id,
        ))


def test_idempotency_rejects_same_key_with_different_input(
    engine: Engine, seeded_case: SeededCase
) -> None:
    app = service(engine)
    key = uuid4()
    app.execute(command(seeded_case, "skill", "create", {
        "code": "IDEM", "name": "Idempotente", "description": None, "category": None,
    }, command_id=key))
    with pytest.raises(IdempotencyConflict):
        app.execute(command(seeded_case, "skill", "create", {
            "code": "IDEM-2", "name": "Otro", "description": None, "category": None,
        }, command_id=key))


def test_skill_create_edit_assign_remove_and_uniqueness(
    engine: Engine, seeded_case: SeededCase
) -> None:
    app = service(engine)
    created = app.execute(command(seeded_case, "skill", "create", {
        "code": "CNC-X", "name": "CNC", "description": "Mecanizado", "category": "Máquina",
    }))
    skill_id = created.entity["id"]
    edited = app.execute(command(seeded_case, "skill", "update", {
        "code": "CNC-X", "name": "CNC avanzado", "description": "Mecanizado", "category": "Máquina",
    }, entity_id=skill_id, version=1))
    assert edited.entity["name"] == "CNC avanzado"
    assigned = app.execute(command(seeded_case, "person_skill", "assign_skill", {
        "skill_id": skill_id, "valid_from": date.today(), "valid_to": None, "level": 1,
    }, entity_id=seeded_case.employee_id))
    assert assigned.entity["enabled"] is True
    removed = app.execute(command(seeded_case, "person_skill", "remove_skill", {
        "skill_id": skill_id,
    }, entity_id=seeded_case.employee_id))
    assert removed.entity["enabled"] is False
    with pytest.raises(IntegrityError):
        app.execute(command(seeded_case, "skill", "create", {
            "code": "CNC-X", "name": "Duplicada", "description": None, "category": None,
        }))


def test_center_capacity_validation_and_history_preserved(
    engine: Engine, seeded_case: SeededCase
) -> None:
    app = service(engine)
    center = app.execute(command(seeded_case, "work_center", "create", {
        "code": "ARM-2", "name": "Armado 2", "capacity_mode": "cumulative",
        "aggregate_capacity": 3, "capacity_unit": "puesto",
        "base_calendar_id": seeded_case.calendar_id,
    }))
    center_id = center.entity["id"]
    edited = app.execute(command(seeded_case, "work_center", "update", {
        "code": "ARM-2", "name": "Armado flexible", "capacity_mode": "cumulative",
        "aggregate_capacity": 4, "capacity_unit": "puesto",
        "base_calendar_id": seeded_case.calendar_id,
    }, entity_id=center_id, version=1))
    assert edited.entity["aggregate_capacity"] == "4.0000"
    app.execute(command(seeded_case, "work_center", "set_status", {"status": "inactive"},
                        entity_id=center_id, version=2))
    with engine.connect() as connection:
        assert connection.scalar(text(
            "SELECT count(*) FROM capacity.work_centers WHERE organization_id=:org AND id=:id"
        ), {"org": seeded_case.organization_id, "id": center_id}) == 1


def test_resource_create_move_center_deactivate_and_current_unchanged(
    engine: Engine, seeded_case: SeededCase
) -> None:
    app = service(engine)
    with engine.connect() as connection:
        current = connection.scalar(text("SELECT current_plan_version_id FROM core.plants WHERE id=:id"),
                                    {"id": seeded_case.plant_id})
    resource = app.execute(command(seeded_case, "resource", "create", {
        "code": "BANCO-X", "name": "Banco X", "work_center_id": seeded_case.work_center_id,
        "resource_type_id": seeded_case.resource_type_id, "scheduling_mode": "exclusive",
        "capacity_units": 1, "capacity_unit": "unit", "is_mobile": False,
        "base_calendar_id": seeded_case.calendar_id,
    }))
    resource_id = resource.entity["id"]
    edited = app.execute(command(seeded_case, "resource", "update", {
        "code": "BANCO-X", "name": "Banco móvil", "work_center_id": seeded_case.work_center_id,
        "resource_type_id": seeded_case.resource_type_id, "scheduling_mode": "exclusive",
        "capacity_units": 1, "capacity_unit": "unit", "is_mobile": True,
        "base_calendar_id": seeded_case.calendar_id,
    }, entity_id=resource_id, version=1))
    assert edited.entity["is_mobile"] is True
    app.execute(command(seeded_case, "resource", "set_status", {"status": "inactive"},
                        entity_id=resource_id, version=2))
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT current_plan_version_id FROM core.plants WHERE id=:id"),
                                 {"id": seeded_case.plant_id}) == current
        assert connection.scalar(text("SELECT count(*) FROM capacity.physical_resources WHERE id=:id"),
                                 {"id": resource_id}) == 1


def test_calendar_windows_exception_timezone_and_assignments(
    engine: Engine, seeded_case: SeededCase
) -> None:
    app = service(engine)
    calendar = app.execute(command(seeded_case, "calendar", "create", calendar_payload()))
    calendar_id = calendar.entity["id"]
    windows = app.execute(command(seeded_case, "calendar_windows", "define_windows", {
        "effective_from": date.today(), "windows": [
            {"weekday": 1, "local_start": time(8, 30), "local_end": time(12, 30), "capacity_factor": 1},
            {"weekday": 1, "local_start": time(13), "local_end": time(16), "capacity_factor": 1},
        ],
    }, entity_id=calendar_id, version=1))
    assert windows.entity["row_version"] == 2
    with pytest.raises(InvalidMasterData, match="overlap"):
        app.execute(command(seeded_case, "calendar_windows", "define_windows", {
            "effective_from": date.today(), "windows": [
                {"weekday": 1, "local_start": time(8), "local_end": time(12), "capacity_factor": 1},
                {"weekday": 1, "local_start": time(11), "local_end": time(13), "capacity_factor": 1},
            ],
        }, entity_id=calendar_id, version=2))
    exception = app.execute(command(seeded_case, "calendar_exception", "create", {
        "calendar_id": calendar_id, "exception_date": date(2026, 12, 24),
        "effect": "replace", "local_start": time(8, 30), "local_end": time(12),
        "capacity_factor": 1, "reason": "Horario reducido",
    }))
    assert exception.entity["effect"] == "replace"
    person = app.execute(command(seeded_case, "person", "create",
        {**person_payload(seeded_case, "CAL-PER"), "base_calendar_id": calendar_id}))
    assert person.entity["base_calendar_id"] == str(calendar_id)


def test_invalid_timezone_rolls_back_without_audit(
    engine: Engine, seeded_case: SeededCase
) -> None:
    key = uuid4()
    with pytest.raises(InvalidMasterData, match="IANA"):
        service(engine).execute(command(
            seeded_case, "calendar", "create", calendar_payload("BAD-TZ") | {"timezone": "UTC-3"},
            command_id=key,
        ))
    with engine.connect() as connection:
        assert connection.scalar(text(
            "SELECT count(*) FROM capacity.calendars WHERE organization_id=:org AND code='BAD-TZ'"
        ), {"org": seeded_case.organization_id}) == 0
        assert connection.scalar(text(
            "SELECT count(*) FROM audit.audit_entries WHERE organization_id=:org AND request_id=:key"
        ), {"org": seeded_case.organization_id, "key": key}) == 0


def test_row_version_prevents_lost_updates(
    engine: Engine, seeded_case: SeededCase
) -> None:
    app = service(engine)
    created = app.execute(command(seeded_case, "skill", "create", {
        "code": "RACE", "name": "Race", "description": None, "category": None,
    }))
    skill_id = created.entity["id"]
    def update(name):
        return service(engine).execute(command(seeded_case, "skill", "update", {
            "code": "RACE", "name": name, "description": None, "category": None,
        }, entity_id=skill_id, version=1))
    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = []
        for future in [executor.submit(update, "A"), executor.submit(update, "B")]:
            try:
                outcomes.append(type(future.result()).__name__)
            except Exception as exc:
                outcomes.append(type(exc).__name__)
    assert sorted(outcomes) == ["MasterDataConflict", "MasterDataResult"]


def test_http_contract_openapi_422_and_cross_tenant_404(
    engine: Engine, seeded_case: SeededCase
) -> None:
    client = TestClient(create_app(engine=engine, enable_dev_context=True),
                        raise_server_exceptions=False)
    headers = {"X-Dev-Organization-Id": str(seeded_case.organization_id),
               "X-Dev-Plant-Id": str(seeded_case.plant_id),
               "X-Dev-User-Id": str(seeded_case.actor_id),
               "Idempotency-Key": str(uuid4())}
    assert client.get("/master-data/snapshot", headers=headers).status_code == 200
    invalid = client.post("/master-data/work-centers", headers=headers, json={
        "code": "BAD", "name": "Bad", "capacity_mode": "cumulative",
        "aggregate_capacity": 0, "capacity_unit": "unit",
        "base_calendar_id": str(seeded_case.calendar_id),
    })
    assert invalid.status_code == 422
    foreign = client.patch(f"/master-data/people/{seeded_case.employee_id}", headers={
        **headers, "X-Dev-Organization-Id": str(seeded_case.other_organization_id),
        "Idempotency-Key": str(uuid4()),
    }, json={**person_payload(seeded_case), "base_calendar_id": str(seeded_case.calendar_id),
             "default_work_center_id": str(seeded_case.work_center_id),
             "expected_row_version": 1})
    assert foreign.status_code == 404
    paths = client.get("/openapi.json").json()["paths"]
    assert "/master-data/people" in paths
    assert "/master-data/calendars/{entity_id}/windows" in paths
    assert "/master-data/plant" in paths
