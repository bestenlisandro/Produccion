from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from .errors import InvalidEstimate


class RemainingDimension(StrEnum):
    LABOR_WORK = "LABOR_WORK"
    ACTIVE_PHYSICAL_USE = "ACTIVE_PHYSICAL_USE"
    PHYSICAL_OCCUPATION = "PHYSICAL_OCCUPATION"


@dataclass(frozen=True)
class RemainingResourceInput:
    phase_id: UUID
    dimension: RemainingDimension
    remaining_minutes: int | None = None
    expected_release_at: datetime | None = None
    skill_id: UUID | None = None
    min_people: int | None = None
    max_people: int | None = None
    physical_requirement_id: UUID | None = None
    physical_resource_id: UUID | None = None
    capacity_units: float | None = None
    details: dict[str, Any] | None = None

    def validate(self) -> None:
        if self.remaining_minutes is not None and self.remaining_minutes < 0:
            raise InvalidEstimate("remaining_minutes cannot be negative")
        if self.capacity_units is not None and self.capacity_units <= 0:
            raise InvalidEstimate("capacity_units must be positive")
        if self.dimension is RemainingDimension.LABOR_WORK:
            if (
                self.skill_id is None
                or self.min_people is None
                or self.max_people is None
                or self.min_people < 1
                or self.max_people < self.min_people
                or self.physical_requirement_id is not None
                or self.expected_release_at is not None
            ):
                raise InvalidEstimate("invalid LABOR_WORK dimension")
        elif self.dimension is RemainingDimension.ACTIVE_PHYSICAL_USE:
            if (
                self.physical_requirement_id is None
                or self.remaining_minutes is None
                or self.skill_id is not None
                or self.expected_release_at is not None
            ):
                raise InvalidEstimate("invalid ACTIVE_PHYSICAL_USE dimension")
        elif self.dimension is RemainingDimension.PHYSICAL_OCCUPATION:
            if (
                self.physical_resource_id is None
                or (self.remaining_minutes is None and self.expected_release_at is None)
                or self.skill_id is not None
            ):
                raise InvalidEstimate("invalid PHYSICAL_OCCUPATION dimension")


@dataclass(frozen=True)
class UpdateRemainingEstimate:
    organization_id: UUID
    operation_execution_id: UUID
    expected_revision_no: int
    cutoff_at: datetime
    remaining_labor_minutes: int
    resources: tuple[RemainingResourceInput, ...]
    input_mode: str = "remaining_duration"
    raw_input: dict[str, Any] | None = None
    reason: str | None = None
    actor_id: UUID | None = None
    source_system: str = "backend"

    def validate(self) -> None:
        if self.expected_revision_no < 1:
            raise InvalidEstimate("expected_revision_no must be positive")
        if self.remaining_labor_minutes < 0:
            raise InvalidEstimate("remaining_labor_minutes cannot be negative")
        if self.input_mode not in {"delta", "remaining_duration", "expected_finish"}:
            raise InvalidEstimate("unsupported input_mode")
        if not self.resources:
            raise InvalidEstimate("at least one resource dimension is required")
        for resource in self.resources:
            resource.validate()
        labor = [r for r in self.resources if r.dimension is RemainingDimension.LABOR_WORK]
        if not labor or sum(r.remaining_minutes or 0 for r in labor) != self.remaining_labor_minutes:
            raise InvalidEstimate("LABOR_WORK must add up to remaining_labor_minutes")


@dataclass(frozen=True)
class RemainingEstimateResult:
    revision_id: UUID
    revision_no: int
    planning_state_revision_id: UUID
    planning_state_revision_no: int
    effective_event_id: UUID
    original_labor_minutes: int
    executed_labor_minutes: int
    remaining_labor_minutes: int
    updated_total_labor_minutes: int
    current_plan_version_id: UUID | None
