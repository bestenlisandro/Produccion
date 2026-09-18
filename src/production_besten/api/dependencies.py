from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from fastapi import Header, Request
from sqlalchemy import Engine

from production_besten.api.context import DevRequestContextProvider, RequestContext
from production_besten.persistence.api_queries import PostgresApiQueries


@dataclass
class ApiContainer:
    engine: Engine
    context_provider: DevRequestContextProvider
    failpoints: dict[str, str] = field(default_factory=dict)

    @property
    def queries(self) -> PostgresApiQueries:
        return PostgresApiQueries(self.engine)


def get_container(request: Request) -> ApiContainer:
    return request.app.state.container


def get_request_context(
    request: Request,
    user_id: UUID = Header(alias="X-Dev-User-Id"),
    organization_id: UUID = Header(alias="X-Dev-Organization-Id"),
    plant_id: UUID | None = Header(default=None, alias="X-Dev-Plant-Id"),
) -> RequestContext:
    provider = request.app.state.container.context_provider
    return provider(user_id, organization_id, plant_id)


def get_idempotency_key(value: UUID = Header(alias="Idempotency-Key")) -> UUID:
    return value
