from __future__ import annotations
from datetime import datetime
from typing import Callable

from fastapi import FastAPI
from sqlalchemy import Engine

from production_besten.api.context import DevRequestContextProvider
from production_besten.api.dependencies import ApiContainer
from production_besten.api.errors import install_error_handlers
from production_besten.api.master_data_routes import router as master_data_router
from production_besten.api.routes import router
from production_besten.api.project_intake_routes import router as project_intake_router
from production_besten.api.product_editor_routes import router as product_editor_router
from production_besten.api.production_readiness_routes import router as production_readiness_router
from production_besten.infrastructure.settings import Settings
from production_besten.persistence.database import create_database_engine


def create_app(*, engine: Engine | None = None, enable_dev_context: bool | None = None,
               failpoints: dict[str, str] | None = None,
               clock: Callable[[], datetime] | None = None) -> FastAPI:
    if engine is None:
        settings = Settings()
        engine = create_database_engine(settings.sqlalchemy_database_url())
        enabled = settings.app_env in {"development", "testing"}
    else:
        enabled = True
    if enable_dev_context is not None:
        enabled = enable_dev_context
    app = FastAPI(title="Producción Besten API", version="1.0.0",
                  description="API interna mínima sobre servicios de dominio validados.")
    app.state.container = ApiContainer(engine, DevRequestContextProvider(enabled=enabled), failpoints or {}, clock)
    install_error_handlers(app)
    from production_besten.api.installation_routes import router as installation_router
    app.include_router(installation_router)
    app.include_router(production_readiness_router)
    app.include_router(router)
    app.include_router(master_data_router)
    app.include_router(project_intake_router)
    app.include_router(product_editor_router)
    return app
