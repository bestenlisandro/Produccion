from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from fastapi import Header, HTTPException


@dataclass(frozen=True)
class RequestContext:
    user_id: UUID
    organization_id: UUID
    plant_id: UUID | None = None
    capabilities: frozenset[str] = frozenset()


class RequestContextProvider(Protocol):
    def __call__(self, *args, **kwargs) -> RequestContext: ...


class DevRequestContextProvider:
    """DEV ONLY. Trusts explicit headers and must never be production authentication."""

    def __init__(self, *, enabled: bool) -> None:
        self.enabled = enabled

    def __call__(
        self,
        user_id: UUID = Header(alias="X-Dev-User-Id"),
        organization_id: UUID = Header(alias="X-Dev-Organization-Id"),
        plant_id: UUID | None = Header(default=None, alias="X-Dev-Plant-Id"),
    ) -> RequestContext:
        if not self.enabled:
            raise HTTPException(status_code=503, detail={"code": "AUTH_PROVIDER_NOT_CONFIGURED", "message": "production identity provider is not configured"})
        return RequestContext(user_id, organization_id, plant_id)


def require_plant(context: RequestContext) -> UUID:
    if context.plant_id is None:
        raise HTTPException(status_code=400, detail={"code": "PLANT_CONTEXT_REQUIRED", "message": "X-Dev-Plant-Id is required for this operation"})
    return context.plant_id
