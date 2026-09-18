from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from production_besten.api.app import create_app

from .execution_helpers import create_unstarted_case


def _headers(case, *, organization_id=None, key=None):
    value = {
        "X-Dev-User-Id": str(case.actor_id),
        "X-Dev-Organization-Id": str(organization_id or case.organization_id),
        "X-Dev-Plant-Id": str(case.plant_id),
    }
    if key is not False:
        value["Idempotency-Key"] = str(key or uuid4())
    return value


def _client(engine, *, failpoints=None, enabled=True):
    return TestClient(create_app(engine=engine, enable_dev_context=enabled, failpoints=failpoints),
                      raise_server_exceptions=False)


def _project_refs(engine, case):
    with engine.connect() as conn:
        return conn.execute(text("SELECT customer_id,priority_id FROM core.projects WHERE id=:id"), {"id": case.project_id}).mappings().one()


def _seed_route(engine, case, *, status="published"):
    template, version, step = uuid4(), uuid4(), uuid4()
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO production.route_templates(id,organization_id,code,name,status) VALUES (:id,:org,:code,'Route','active')"), {"id": template, "org": case.organization_id, "code": f"R-{version.hex[:8]}"})
        conn.execute(text("INSERT INTO production.route_versions(id,organization_id,route_template_id,version_no,status,published_at,published_by) VALUES (:id,:org,:template,1,:status,CASE WHEN :status='published' THEN now() END,:actor)"), {"id": version, "org": case.organization_id, "template": template, "status": status, "actor": case.actor_id})
        conn.execute(text("INSERT INTO production.route_steps(id,organization_id,route_version_id,operation_definition_id,code,name,sequence_hint) VALUES (:id,:org,:version,:definition,'CUT','Cut',1)"), {"id": step, "org": case.organization_id, "version": version, "definition": case.operation_definition_id})
    return version, step


def _start_http(client, case, execution_case, *, key=None):
    return client.post(f"/operations/{execution_case.operation_id}/start", headers=_headers(case, key=key), json={
        "phase_id": str(execution_case.phase_ids[0]), "started_at": execution_case.started_at.isoformat()
    })


def test_health_is_public_and_alive(engine):
    response = _client(engine).get("/health")
    assert response.status_code == 200 and response.json() == {"status": "ok"}


def test_ready_checks_postgresql(engine):
    response = _client(engine).get("/ready")
    assert response.status_code == 200 and response.json() == {"status": "ready"}


def test_openapi_is_valid_and_does_not_put_tenant_in_project_body(engine):
    document = _client(engine).get("/openapi.json").json()
    assert document["info"]["title"] == "Producción Besten API"
    schema = document["components"]["schemas"]["CreateProjectRequest"]
    assert "organization_id" not in schema["properties"] and "/projects" in document["paths"]


def test_dev_context_is_explicitly_disabled_for_production_mode(engine, seeded_case):
    response = _client(engine, enabled=False).get(f"/projects/{seeded_case.project_id}", headers=_headers(seeded_case, key=False))
    assert response.status_code == 503 and response.json()["detail"]["code"] == "AUTH_PROVIDER_NOT_CONFIGURED"


def test_missing_dev_identity_is_structural_422(engine, seeded_case):
    assert _client(engine).get(f"/projects/{seeded_case.project_id}").status_code == 422


def test_create_project_uses_context_tenant_and_plant(engine, seeded_case):
    refs = _project_refs(engine, seeded_case)
    response = _client(engine).post("/projects", headers=_headers(seeded_case, key=False), json={
        "customer_id": str(refs["customer_id"]), "priority_id": str(refs["priority_id"]),
        "code": f"API-{uuid4().hex[:8]}", "name": "API project"
    })
    assert response.status_code == 201
    assert response.json()["plant_id"] == str(seeded_case.plant_id)


def test_get_project(engine, seeded_case):
    response = _client(engine).get(f"/projects/{seeded_case.project_id}", headers=_headers(seeded_case, key=False))
    assert response.status_code == 200 and response.json()["id"] == str(seeded_case.project_id)


def test_cross_tenant_project_is_indistinguishable_from_missing(engine, seeded_case):
    client = _client(engine)
    foreign = client.get(f"/projects/{seeded_case.project_id}", headers=_headers(seeded_case, organization_id=seeded_case.other_organization_id, key=False))
    missing = client.get(f"/projects/{uuid4()}", headers=_headers(seeded_case, key=False))
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json() == {"error": {"code": "RESOURCE_NOT_FOUND", "message": "resource not found"}}


def test_create_and_list_batch(engine, seeded_case):
    client = _client(engine)
    response = client.post(f"/projects/{seeded_case.project_id}/batches", headers=_headers(seeded_case), json={
        "code": f"API-L-{uuid4().hex[:8]}", "name": "API lot", "quantity": 2, "unit": "unit"
    })
    assert response.status_code == 201 and response.json()["sequence_no"] == 2
    listed = client.get(f"/projects/{seeded_case.project_id}/batches", headers=_headers(seeded_case, key=False))
    assert listed.status_code == 200 and len(listed.json()) == 2


def test_define_route(engine, seeded_case):
    version, _ = _seed_route(engine, seeded_case)
    response = _client(engine).post(f"/batches/{seeded_case.project_lot_id}/route", headers=_headers(seeded_case), json={
        "route_version_id": str(version), "effective_at": datetime.now(timezone.utc).isoformat()
    })
    assert response.status_code == 201 and response.json()["planning_state_revision_number"]


def test_semantically_invalid_route_is_400(engine, seeded_case):
    version, _ = _seed_route(engine, seeded_case, status="draft")
    response = _client(engine).post(f"/batches/{seeded_case.project_lot_id}/route", headers=_headers(seeded_case), json={
        "route_version_id": str(version), "effective_at": datetime.now(timezone.utc).isoformat()
    })
    assert response.status_code == 400 and response.json()["error"]["code"] == "INVALID_PRODUCT_DEFINITION"


def test_create_required_operation(engine, seeded_case):
    response = _client(engine).post(f"/batches/{seeded_case.project_lot_id}/operations", headers=_headers(seeded_case), json={
        "operation_definition_id": str(seeded_case.operation_definition_id),
        "code": f"API-O-{uuid4().hex[:8]}", "name": "Cut"
    })
    assert response.status_code == 201 and UUID(response.json()["id"])


def test_create_phase_with_requirements(engine, seeded_case):
    client = _client(engine)
    operation = client.post(f"/batches/{seeded_case.project_lot_id}/operations", headers=_headers(seeded_case), json={
        "operation_definition_id": str(seeded_case.operation_definition_id), "code": f"API-O-{uuid4().hex[:8]}", "name": "Cut"
    }).json()["id"]
    response = client.post(f"/operations/{operation}/phases", headers=_headers(seeded_case), json={
        "sequence_no": 1, "code": "WORK", "name": "Work", "estimate_kind": "labor",
        "original_estimate_minutes": 120, "split_policy": "splittable",
        "labor_requirements": [{"skill_id": str(seeded_case.skill_id), "min_people": 1, "max_people": 2, "work_minutes": 120}],
        "physical_requirements": [{"physical_resource_type_id": str(seeded_case.resource_type_id), "quantity": 1, "capacity_units": 1, "usage_mode": "active_use"}]
    })
    assert response.status_code == 201


def test_freeze_definition_returns_metadata_not_snapshot_and_reuses_identical(engine, seeded_case):
    client, key = _client(engine), uuid4()
    url = f"/projects/{seeded_case.project_id}/product-definition-revisions"
    first = client.post(url, headers=_headers(seeded_case, key=key), json={"reason": "API freeze"})
    replay = client.post(url, headers=_headers(seeded_case, key=key), json={"reason": "API freeze"})
    duplicate = client.post(url, headers=_headers(seeded_case), json={"reason": "same definition"})
    assert first.status_code == 201 and replay.status_code == duplicate.status_code == 200
    assert "canonical_snapshot" not in first.json() and replay.json()["idempotent_replay"]
    assert duplicate.json()["reused_existing_revision"]


def test_start_unplanned_and_idempotent_replay(engine, seeded_case):
    case, client, key = create_unstarted_case(engine, seeded_case), _client(engine), uuid4()
    first, replay = _start_http(client, seeded_case, case, key=key), _start_http(client, seeded_case, case, key=key)
    assert first.status_code == 201 and replay.status_code == 200
    assert first.json()["execution_id"] == replay.json()["execution_id"] and replay.json()["idempotent_replay"]


def test_execution_idempotency_reuse_with_another_target_is_409(engine, seeded_case):
    first_case = create_unstarted_case(engine, seeded_case)
    second_case = create_unstarted_case(engine, seeded_case)
    client, key = _client(engine), uuid4()
    assert _start_http(client, seeded_case, first_case, key=key).status_code == 201
    response = _start_http(client, seeded_case, second_case, key=key)
    assert response.status_code == 409 and response.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


def test_register_actual_segment(engine, seeded_case):
    case, client = create_unstarted_case(engine, seeded_case), _client(engine)
    execution = _start_http(client, seeded_case, case).json()["execution_id"]
    response = client.post(f"/executions/{execution}/segments", headers=_headers(seeded_case), json={
        "phase_id": str(case.phase_ids[0]), "started_at": case.started_at.isoformat(),
        "ended_at": (case.started_at + timedelta(minutes=60)).isoformat(), "work_minutes": 60,
        "humans": [{"employee_id": str(case.actual_employee_id), "work_minutes": 60}],
        "physical_usages": [{"physical_resource_id": str(case.actual_resource_id), "work_minutes": 60}]
    })
    assert response.status_code == 201 and response.json()["segment_number"] == 1


def test_finish_operation(engine, seeded_case):
    case, client = create_unstarted_case(engine, seeded_case), _client(engine)
    execution = _start_http(client, seeded_case, case).json()["execution_id"]
    response = client.post(f"/operations/{case.operation_id}/finish", headers=_headers(seeded_case), json={
        "phase_id": str(case.phase_ids[0]), "completed_at": (case.started_at + timedelta(minutes=30)).isoformat()
    })
    assert response.status_code == 200 and response.json()["execution_id"] == execution
    assert response.json()["operation_completed"]


def test_simple_remaining_estimate_derives_phase_skill_team_and_revision(engine, seeded_case):
    case, client = create_unstarted_case(engine, seeded_case), _client(engine)
    _start_http(client, seeded_case, case)
    response = client.post(f"/operations/{case.operation_id}/remaining-estimate", headers=_headers(seeded_case, key=False), json={
        "cutoff_at": (case.started_at + timedelta(minutes=1)).isoformat(), "reason": "needs more time",
        "remaining": [{"dimension": "LABOR_WORK", "minutes": 300}]
    })
    assert response.status_code == 200
    assert response.json()["remaining_minutes"] == 300 and response.json()["revision_number"] == 2


@pytest.mark.parametrize("payload", [
    {"code": "", "name": "Bad", "quantity": 1},
    {"code": "BAD", "name": "Bad", "quantity": -1},
])
def test_invalid_structural_payload_is_422(engine, seeded_case, payload):
    response = _client(engine).post(f"/projects/{seeded_case.project_id}/batches", headers=_headers(seeded_case), json=payload)
    assert response.status_code == 422


def test_missing_idempotency_key_is_422(engine, seeded_case):
    response = _client(engine).post(f"/projects/{seeded_case.project_id}/batches", headers=_headers(seeded_case, key=False), json={"code": "NO-KEY", "name": "No key"})
    assert response.status_code == 422


def test_idempotency_reuse_with_incompatible_payload_is_409(engine, seeded_case):
    client, key = _client(engine), uuid4()
    url = f"/projects/{seeded_case.project_id}/batches"
    assert client.post(url, headers=_headers(seeded_case, key=key), json={"code": "IDEM-A", "name": "A"}).status_code == 201
    response = client.post(url, headers=_headers(seeded_case, key=key), json={"code": "IDEM-B", "name": "B"})
    assert response.status_code == 409 and response.json()["error"]["code"] == "PRODUCT_DEFINITION_CONFLICT"


def test_gate_block_is_centralized_as_409(engine, seeded_case):
    case, client = create_unstarted_case(engine, seeded_case), _client(engine)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO production.operation_gates(organization_id,required_operation_id,timing,gate_type,available_at) VALUES (:org,:operation,'before_start','NOT_BEFORE',:at)"), {"org": seeded_case.organization_id, "operation": case.operation_id, "at": case.started_at + timedelta(days=1)})
    response = _start_http(client, seeded_case, case)
    assert response.status_code == 409 and response.json()["error"]["code"] == "GATE_BLOCKED"


def test_concurrent_start_returns_one_created_and_one_conflict(engine, seeded_case):
    case = create_unstarted_case(engine, seeded_case)
    def invoke(_):
        with _client(engine) as client:
            return _start_http(client, seeded_case, case).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = sorted(pool.map(invoke, range(2)))
    assert statuses == [201, 409]


def test_http_rollback_hides_internal_failure_and_preserves_state(engine, seeded_case):
    client = _client(engine, failpoints={"product": "batch_after_insert"})
    with engine.connect() as conn:
        count = conn.scalar(text("SELECT count(*) FROM core.project_lots WHERE organization_id=:org AND project_id=:project"), {"org": seeded_case.organization_id, "project": seeded_case.project_id})
        state = conn.scalar(text("SELECT current_revision_no FROM planning.planning_state_heads WHERE organization_id=:org AND plant_id=:plant"), {"org": seeded_case.organization_id, "plant": seeded_case.plant_id})
    response = client.post(f"/projects/{seeded_case.project_id}/batches", headers=_headers(seeded_case), json={"code": "ROLLBACK", "name": "Rollback"})
    assert response.status_code == 500 and "SQL" not in response.text and "Traceback" not in response.text
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM core.project_lots WHERE organization_id=:org AND project_id=:project"), {"org": seeded_case.organization_id, "project": seeded_case.project_id}) == count
        assert conn.scalar(text("SELECT current_revision_no FROM planning.planning_state_heads WHERE organization_id=:org AND plant_id=:plant"), {"org": seeded_case.organization_id, "plant": seeded_case.plant_id}) == state
