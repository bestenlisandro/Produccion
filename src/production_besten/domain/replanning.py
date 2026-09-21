from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from production_besten.domain.errors import InvalidSchedulingInput


@dataclass(frozen=True)
class ReplanRequest:
    organization_id: UUID
    plant_id: UUID
    actor_id: UUID
    idempotency_key: str
    code: str
    name: str
    cutoff_at: datetime
    horizon_end: datetime
    product_definition_revision_id: UUID
    planning_state_revision_id: UUID
    base_plan_version_id: UUID
    trigger_operation_id: UUID | None = None
    project_id: UUID | None = None
    parameters: dict[str, Any] | None = None

    def validate(self) -> None:
        if (self.trigger_operation_id is None) == (self.project_id is None):
            raise InvalidSchedulingInput(
                "exactly one of trigger_operation_id or project_id is required"
            )
        if not self.idempotency_key.strip() or not self.code.strip() or not self.name.strip():
            raise InvalidSchedulingInput("idempotency key, scenario code and name are required")
        for value, label in ((self.cutoff_at, "cutoff_at"), (self.horizon_end, "horizon_end")):
            if value.tzinfo is None or value.utcoffset() is None:
                raise InvalidSchedulingInput(f"{label} must include a timezone")
        if self.cutoff_at >= self.horizon_end:
            raise InvalidSchedulingInput("replan horizon must have positive duration")
        if self.parameters is not None and not isinstance(self.parameters, dict):
            raise InvalidSchedulingInput("parameters must be an object")

    @property
    def command_name(self) -> str:
        return "REPLAN_FROM_OPERATION" if self.trigger_operation_id else "REPLAN_PROJECT"


@dataclass(frozen=True)
class ReplanResult:
    scenario_id: UUID
    solution_id: UUID
    status: str
    complete: bool
    frontier_project_ids: tuple[UUID, ...]
    frontier_operation_ids: tuple[UUID, ...]
    changed_operations: int
    customer_date_alerts: int
    solution_sha256: str | None
    elapsed_ms: int
    idempotent_replay: bool = False


@dataclass(frozen=True)
class RejectReplan:
    organization_id: UUID
    plant_id: UUID
    actor_id: UUID
    scenario_id: UUID
    expected_row_version: int
    reason: str

    def validate(self) -> None:
        if self.expected_row_version < 1:
            raise InvalidSchedulingInput("expected_row_version must be positive")
        if not self.reason.strip():
            raise InvalidSchedulingInput("rejection reason is required")


@dataclass(frozen=True)
class RejectReplanResult:
    scenario_id: UUID
    status: str
    row_version: int
    idempotent_replay: bool = False
