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
        if self.parameters and self.parameters.get("manual_hypothesis"):
            return str(self.parameters["manual_hypothesis"]["type"])
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
class MoveScheduledActivity:
    organization_id: UUID
    plant_id: UUID
    actor_id: UUID
    command_id: UUID
    operation_id: UUID
    base_plan_version_id: UUID
    product_definition_revision_id: UUID
    planning_state_revision_id: UUID
    requested_start: datetime
    cutoff_at: datetime
    horizon_end: datetime
    phase_id: UUID | None = None
    requested_resource_id: UUID | None = None

    def validate(self) -> None:
        for value, label in ((self.requested_start, "requested_start"),
                             (self.cutoff_at, "cutoff_at"),
                             (self.horizon_end, "horizon_end")):
            if value.tzinfo is None or value.utcoffset() is None:
                raise InvalidSchedulingInput(f"{label} must include a timezone")
        if self.cutoff_at >= self.horizon_end:
            raise InvalidSchedulingInput("manual scheduling horizon must have positive duration")
        if not self.cutoff_at <= self.requested_start < self.horizon_end:
            raise InvalidSchedulingInput("requested_start must be inside the future horizon")


@dataclass(frozen=True)
class ResizeScheduledActivity:
    organization_id: UUID
    plant_id: UUID
    actor_id: UUID
    command_id: UUID
    operation_id: UUID
    base_plan_version_id: UUID
    product_definition_revision_id: UUID
    planning_state_revision_id: UUID
    requested_duration_minutes: int
    cutoff_at: datetime
    horizon_end: datetime
    phase_id: UUID | None = None

    def validate(self) -> None:
        for value, label in ((self.cutoff_at, "cutoff_at"),
                             (self.horizon_end, "horizon_end")):
            if value.tzinfo is None or value.utcoffset() is None:
                raise InvalidSchedulingInput(f"{label} must include a timezone")
        if self.cutoff_at >= self.horizon_end:
            raise InvalidSchedulingInput("manual scheduling horizon must have positive duration")
        if self.requested_duration_minutes <= 0:
            raise InvalidSchedulingInput("requested_duration_minutes must be positive")


@dataclass(frozen=True)
class ManualScheduleResult:
    scenario_id: UUID
    solution_id: UUID
    status: str
    requested_start: datetime
    requested_finish: datetime | None
    proposed_start: datetime | None
    proposed_finish: datetime | None
    exact_request_satisfied: bool
    changed_operations: int
    affected_projects: int
    customer_date_alerts: int
    explanations: tuple[str, ...]
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


@dataclass(frozen=True)
class AcceptReplan:
    organization_id: UUID
    plant_id: UUID
    actor_id: UUID
    command_id: UUID
    scenario_id: UUID
    expected_promotion_lock_version: int
    reason: str | None = None

    def validate(self) -> None:
        if self.expected_promotion_lock_version < 1:
            raise InvalidSchedulingInput(
                "expected_promotion_lock_version must be positive"
            )
        if self.reason is not None and not self.reason.strip():
            raise InvalidSchedulingInput("reason cannot be blank")


@dataclass(frozen=True)
class AcceptReplanResult:
    scenario_id: UUID
    schedule_solution_id: UUID
    previous_plan_version_id: UUID
    plan_version_id: UUID
    plan_version_no: int
    promotion_lock_version: int
    promoted_at: datetime
    communication_recommended: bool
    audit_entry_id: UUID
    outbox_message_id: UUID
    idempotent_replay: bool = False
