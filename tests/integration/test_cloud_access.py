from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from sqlalchemy import text

from production_besten.api.cloud import SESSION_COOKIE, CloudSettings, create_cloud_app
from tests.integration.test_operational_frontend_api import _headers


def test_cloud_serves_spa_and_api_only_for_verified_plant_admin(engine, seeded_case, tmp_path, monkeypatch):
    case = seeded_case
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<html>Producción Besten</html>", encoding="utf-8")
    origin = "https://produccion-besten.onrender.com"
    supabase_url = "https://testbesten.supabase.co"
    issuer = supabase_url + "/auth/v1"
    subject = str(uuid4())
    settings = CloudSettings(database_url="unused", public_origin=origin, supabase_url=supabase_url,
                             supabase_publishable_key="sb_publishable_test", production_plant_id=case.plant_id,
                             web_dist=tmp_path)
    signing_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(jwt.PyJWKClient, "get_signing_key_from_jwt",
                        lambda self, token: SimpleNamespace(key=signing_key.public_key()))
    with engine.begin() as conn:
        conn.execute(text("UPDATE core.user_profiles SET auth_subject=:subject WHERE id=:actor"),
                     {"actor": case.actor_id, "subject": subject})

    def signed_token(**overrides):
        now = datetime.now(timezone.utc)
        claims = {
            "iss": issuer, "aud": "authenticated", "sub": subject,
            "role": "authenticated", "iat": now, "exp": now + timedelta(minutes=10), **overrides,
        }
        return jwt.encode(claims, signing_key, algorithm="RS256", headers={"kid": "test"})

    def signed_session(**overrides):
        return {"Cookie": f"{SESSION_COOKIE}={signed_token(**overrides)}"}

    async def fake_sign_in(self, url, *, params, headers, json):
        assert url == issuer + "/token"
        assert params == {"grant_type": "password"}
        assert headers == {"apikey": "sb_publishable_test"}
        assert json == {"email": "test@example.com", "password": "unit-test-password"}
        return httpx.Response(200, request=httpx.Request("POST", url),
                              json={"access_token": signed_token(), "expires_in": 600})

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_sign_in)

    app = create_cloud_app(settings=settings, engine=engine)
    with TestClient(app, base_url=origin) as client:
        assert client.get("/ready").status_code == 200
        signed_out = client.get("/planning/resource-occupancy", follow_redirects=False)
        assert signed_out.status_code == 303 and signed_out.headers["location"] == "/login"
        assert "Producción Besten" in client.get("/login").text
        assert client.get("/api/planning/current/resource-occupancy", headers=_headers(case)).status_code == 401
        assert client.get("/api/projects", headers=signed_session(aud=["wrong"])).status_code == 401
        assert client.get("/api/projects", headers=signed_session(exp=0)).status_code == 401
        assert client.get("/api/projects", headers=signed_session()).status_code == 403
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO core.user_roles(organization_id,user_profile_id,plant_id,role_code,valid_during,assigned_by)
                VALUES (:org,:actor,:plant,'admin',daterange(CURRENT_DATE-1,NULL,'[)'),:actor)
            """), {"org": case.organization_id, "actor": case.actor_id, "plant": case.plant_id})
        assert client.get("/api/projects", headers=signed_session(sub=str(uuid4()))).status_code == 403
        assert client.get("/api/projects", headers=signed_session(is_anonymous=True)).status_code == 401
        assert client.get("/api/openapi.json", headers=signed_session()).status_code == 404
        assert client.post("/api/projects", headers=signed_session()).status_code == 403
        assert client.post("/api/projects", headers={
            **signed_session(), "Origin": "https://otra.example.com",
        }).status_code == 403
        assert client.post("/api/projects", headers={**signed_session(), "Origin": origin}).status_code == 422
        shell = client.get("/planning/resource-occupancy", headers=signed_session())
        assert shell.status_code == 200
        assert "Producción Besten" in shell.text
        assert shell.headers["Cache-Control"] == "no-store"
        response = client.get("/api/planning/current/resource-occupancy", headers={
            **_headers(case, other=True), **signed_session(),
        })
        assert response.status_code == 200, response.text
        assert response.json()["plan_version_number"] == 1
        assert response.headers["Cache-Control"] == "no-store"
        assert client.get("/api/projects", headers={**signed_session(), "Host": "alternate.example.com"}).status_code == 403
        login = client.post("/login", headers={"Origin": origin}, follow_redirects=False,
                            data={"email": "test@example.com", "password": "unit-test-password"})
        assert login.status_code == 303
        assert "__Host-besten-session=" in login.headers["set-cookie"]
        assert "HttpOnly" in login.headers["set-cookie"] and "Secure" in login.headers["set-cookie"]
        assert client.get("/api/planning/current/resource-occupancy").status_code == 200
        assert client.post("/logout", headers={"Origin": origin}, follow_redirects=False).status_code == 303
        assert client.get("/api/planning/current/resource-occupancy").status_code == 401
