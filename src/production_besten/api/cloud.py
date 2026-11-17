from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import UUID
from zoneinfo import ZoneInfo

import httpx
import jwt
from fastapi import FastAPI, HTTPException, Request
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import Engine, text
from starlette.concurrency import run_in_threadpool
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from starlette.staticfiles import StaticFiles

from production_besten.api.app import create_app
from production_besten.api.context import RequestContext
from production_besten.api.dependencies import get_request_context
from production_besten.persistence.database import create_database_engine


class CloudSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    database_url: SecretStr
    public_origin: str
    supabase_url: str
    supabase_publishable_key: SecretStr
    production_plant_id: UUID
    web_dist: Path = Path("frontend/dist")


SESSION_COOKIE = "__Host-besten-session"


class SupabaseIdentity:
    def __init__(self, settings: CloudSettings, engine: Engine) -> None:
        if not re.fullmatch(r"https://[a-z0-9]+\.supabase\.co", settings.supabase_url):
            raise ValueError("SUPABASE_URL must be the HTTPS origin of the Supabase project")
        if not settings.supabase_publishable_key.get_secret_value().startswith("sb_publishable_"):
            raise ValueError("SUPABASE_PUBLISHABLE_KEY must be a publishable key")
        public = urlsplit(settings.public_origin)
        if (public.scheme != "https" or not public.hostname or public.netloc != public.hostname
                or public.path or public.query or public.fragment):
            raise ValueError("PUBLIC_ORIGIN must be an HTTPS origin without a path")
        self.settings = settings
        self.engine = engine
        self.host = public.hostname
        self.issuer = settings.supabase_url + "/auth/v1"
        self.keys = jwt.PyJWKClient(self.issuer + "/.well-known/jwks.json", timeout=4)

    def verify_origin(self, request: Request) -> None:
        if request.headers.get("host") != self.host:
            raise HTTPException(403, "Dominio de acceso no autorizado.")
        if (request.method not in {"GET", "HEAD", "OPTIONS"}
                and request.headers.get("origin") != self.settings.public_origin):
            raise HTTPException(403, "Origen de la operación no autorizado.")

    def __call__(self, request: Request) -> RequestContext:
        self.verify_origin(request)
        return self.verify_session(request.cookies.get(SESSION_COOKIE))

    def verify_session(self, token: str | None) -> RequestContext:
        if not token or len(token) > 8192:
            raise HTTPException(401, "Iniciá sesión para acceder a Producción Besten.")
        try:
            header = jwt.get_unverified_header(token)
            if header.get("alg") not in {"ES256", "RS256"} or not isinstance(header.get("kid"), str):
                raise jwt.InvalidTokenError()
            key = self.keys.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token, key.key, algorithms=["ES256", "RS256"], issuer=self.issuer,
                audience="authenticated",
                options={"require": ["exp", "iat", "iss", "aud", "sub", "role"]},
            )
            subject = str(UUID(claims["sub"]))
        except jwt.PyJWKClientConnectionError as exc:
            raise HTTPException(503, "El servicio de identidad no está disponible.") from exc
        except (jwt.PyJWTError, ValueError) as exc:
            raise HTTPException(401, "La sesión no es válida o venció.") from exc
        if claims["role"] != "authenticated" or claims.get("is_anonymous"):
            raise HTTPException(401, "Se requiere una sesión de usuario.")

        with self.engine.connect() as conn:
            plant = conn.execute(text("""
                SELECT p.organization_id, p.timezone
                FROM core.plants p JOIN core.organizations o ON o.id=p.organization_id
                WHERE p.id=:plant AND p.status='active' AND o.status='active'
            """), {"plant": self.settings.production_plant_id}).mappings().one_or_none()
            actor = None if plant is None else conn.scalar(text("""
                SELECT u.id FROM core.user_profiles u
                WHERE u.auth_subject=:subject AND u.status='active' AND u.organization_id=:org
                  AND EXISTS (
                    SELECT 1 FROM core.user_roles r
                    WHERE r.organization_id=u.organization_id AND r.user_profile_id=u.id
                      AND r.role_code='admin' AND (r.plant_id IS NULL OR r.plant_id=:plant)
                      AND r.valid_during @> CAST(:day AS date)
                  )
            """), {"subject": subject, "org": plant["organization_id"],
                   "plant": self.settings.production_plant_id,
                   "day": datetime.now(ZoneInfo(plant["timezone"])).date()})
        if actor is None:
            raise HTTPException(403, "Tu usuario no está habilitado para esta planta.")
        return RequestContext(actor, plant["organization_id"], self.settings.production_plant_id)

    async def sign_in(self, email: str, password: str) -> tuple[str, int]:
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                result = await client.post(
                    self.issuer + "/token",
                    params={"grant_type": "password"},
                    headers={"apikey": self.settings.supabase_publishable_key.get_secret_value()},
                    json={"email": email, "password": password},
                )
        except httpx.RequestError as exc:
            raise HTTPException(503, "El servicio de identidad no está disponible.") from exc
        if result.status_code == 429:
            raise HTTPException(429, "Demasiados intentos. Probá más tarde.")
        if result.status_code in {400, 401, 403}:
            raise HTTPException(401, "Revisá el correo y la contraseña.")
        try:
            result.raise_for_status()
            data = result.json()
            token, expires = data["access_token"], min(int(data["expires_in"]), 3600)
            if expires <= 0 or not isinstance(token, str) or len(token) > 3800:
                raise ValueError()
        except (httpx.HTTPStatusError, KeyError, ValueError, TypeError) as exc:
            raise HTTPException(503, "El servicio de identidad no está disponible.") from exc
        await run_in_threadpool(self.verify_session, token)
        return token, expires


def login_page(status: int = 200, message: str = "") -> HTMLResponse:
    from html import escape

    return HTMLResponse(f"""<!doctype html>
<html lang="es-AR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Ingresar | Producción Besten</title>
<style>
body {{font:1rem system-ui,sans-serif; margin:0; background:#eef1f3; color:#182027}}
main {{max-width:24rem; margin:8vh auto; padding:1.5rem; background:white; border-radius:.5rem}}
label {{display:block; margin:.8rem 0; font-weight:600}}
input {{box-sizing:border-box; display:block; width:100%; padding:.7rem; margin-top:.2rem; font:inherit}}
button {{background:#075c49; color:white; font:inherit; border:0; border-radius:.25rem; padding:.7rem 1.2rem}}
[role=alert] {{color:#8e211e}}
</style></head>
<body><main><h1>Producción Besten</h1>
<p role="alert">{escape(message)}</p>
<form action="/login" method="post">
<label>Correo<input name="email" type="email" autocomplete="username" required maxlength="254"></label>
<label>Contraseña<input name="password" type="password" autocomplete="current-password" required maxlength="256"></label>
<button type="submit">Ingresar</button>
</form></main></body></html>""", status_code=status)


def create_cloud_app(*, settings: CloudSettings | None = None, engine: Engine | None = None) -> FastAPI:
    settings = settings or CloudSettings()
    engine = engine or create_database_engine(settings.database_url.get_secret_value())
    identity = SupabaseIdentity(settings, engine)
    index = settings.web_dist / "index.html"
    if not index.is_file():
        raise RuntimeError("Build the frontend before starting the production service")

    app = FastAPI(openapi_url=None)
    api = create_app(engine=engine, enable_dev_context=False, expose_docs=False)

    def api_context(request: Request) -> RequestContext:
        return request.state.production_context

    @api.middleware("http")
    async def authenticate_api(request: Request, call_next):
        try:
            request.state.production_context = await run_in_threadpool(identity, request)
        except HTTPException as exc:
            return JSONResponse(status_code=exc.status_code, content={
                "error": {"code": "ACCESS_DENIED", "message": exc.detail},
            })
        return await call_next(request)

    api.dependency_overrides[get_request_context] = api_context
    app.mount("/api", api)
    app.mount("/assets", StaticFiles(directory=settings.web_dist / "assets"))

    @app.middleware("http")
    async def response_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
            "object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
        if not request.url.path.startswith("/assets/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/ready")
    def ready():
        with engine.connect() as conn:
            if not conn.scalar(text("SELECT EXISTS(SELECT 1 FROM core.plants WHERE id=:plant AND status='active')"),
                               {"plant": settings.production_plant_id}):
                return JSONResponse(status_code=503, content={"status": "plant_not_configured"})
        return {"status": "ok"}

    @app.get("/login")
    def show_login(request: Request):
        identity.verify_origin(request)
        return login_page()

    @app.post("/login")
    async def login(request: Request):
        identity.verify_origin(request)
        if request.headers.get("content-type") != "application/x-www-form-urlencoded":
            return login_page(415, "Usá el formulario de ingreso.")
        payload = bytearray()
        async for chunk in request.stream():
            if len(payload) + len(chunk) > 4096:
                return login_page(413, "Los datos de ingreso superan el límite.")
            payload.extend(chunk)
        try:
            fields = parse_qs(payload.decode("utf-8"), strict_parsing=True, max_num_fields=2)
            email, = fields["email"]
            password, = fields["password"]
            if not email.strip() or len(email) > 254 or len(password) > 256:
                raise ValueError()
        except (KeyError, ValueError):
            return login_page(400, "Ingresá tu correo y contraseña.")
        try:
            token, expires = await identity.sign_in(email.strip(), password)
        except HTTPException as exc:
            return login_page(exc.status_code, exc.detail)
        response = RedirectResponse("/", status_code=303)
        response.set_cookie(SESSION_COOKIE, token, max_age=expires, secure=True,
                            httponly=True, samesite="lax")
        return response

    @app.post("/logout")
    def logout(request: Request):
        identity.verify_origin(request)
        response = RedirectResponse("/login", status_code=303)
        response.delete_cookie(SESSION_COOKIE, secure=True, httponly=True, samesite="lax")
        return response

    @app.get("/{path:path}")
    def frontend(path: str, request: Request):
        if path == "api" or "." in path.rsplit("/", 1)[-1]:
            raise HTTPException(404)
        try:
            identity(request)
        except HTTPException as exc:
            if exc.status_code == 401:
                return RedirectResponse("/login", status_code=303)
            raise
        return FileResponse(index)

    return app
