from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from production_besten.domain.errors import DomainError


class InvalidMasterData(DomainError):
    """A master-data command violates an operational invariant."""


class MasterDataConflict(DomainError):
    """A master record changed concurrently or conflicts with existing data."""


MasterEntity = Literal[
    "person", "skill", "work_center", "resource", "calendar",
    "calendar_exception", "plant", "person_skill", "calendar_windows",
]


@dataclass(frozen=True)
class MasterDataCommand:
    command_id: UUID
    organization_id: UUID
    plant_id: UUID
    actor_id: UUID
    action: str
    entity_type: MasterEntity
    payload: dict[str, Any]
    entity_id: UUID | None = None
    expected_row_version: int | None = None

    def __post_init__(self) -> None:
        if not self.action.strip():
            raise InvalidMasterData("action is required")
        if self.expected_row_version is not None and self.expected_row_version < 1:
            raise InvalidMasterData("expected_row_version must be positive")


@dataclass(frozen=True)
class MasterDataResult:
    entity: dict[str, Any]
    current_usage_count: int = 0
    plan_requires_reconciliation: bool = False
    idempotent_replay: bool = False
