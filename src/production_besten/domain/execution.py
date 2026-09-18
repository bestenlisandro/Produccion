from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from .errors import InvalidEstimate


def _require_aware(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise InvalidEstimate(f"{field} must include a timezone")


@dataclass(frozen=True)
class StartOperation:
    organization_id: UUID
    required_operation_id: UUID
    phase_id: UUID
    started_at: datetime
    actor_id: UUID
    command_id: UUID
    origin_plan_version_id: UUID | None = None
    origin_operation_plan_result_id: UUID | None = None
    source_system: str = "backend"

    def validate(self) -> None:
        _require_aware(self.started_at, "started_at")


@dataclass(frozen=True)
class HumanUsage:
    employee_id: UUID
    work_minutes: int

    def validate(self) -> None:
        if self.work_minutes <= 0:
            raise InvalidEstimate("human work_minutes must be positive")


@dataclass(frozen=True)
class PhysicalUsage:
    physical_resource_id: UUID
    work_minutes: int
    capacity_units: float = 1

    def validate(self) -> None:
        if self.work_minutes < 0 or self.capacity_units <= 0:
            raise InvalidEstimate("invalid physical active use")


@dataclass(frozen=True)
class PhysicalOccupation:
    physical_resource_id: UUID
    started_at: datetime
    ended_at: datetime

    def validate(self) -> None:
        _require_aware(self.started_at, "occupation.started_at")
        _require_aware(self.ended_at, "occupation.ended_at")
        if self.started_at >= self.ended_at:
            raise InvalidEstimate("physical occupation must have positive duration")


@dataclass(frozen=True)
class RegisterExecutionSegment:
    organization_id: UUID
    operation_execution_id: UUID
    phase_id: UUID
    started_at: datetime
    ended_at: datetime
    work_minutes: int
    actor_id: UUID
    command_id: UUID
    humans: tuple[HumanUsage, ...] = ()
    physical_usages: tuple[PhysicalUsage, ...] = ()
    occupations: tuple[PhysicalOccupation, ...] = ()
    origin_assignment_segment_id: UUID | None = None
    source_system: str = "backend"

    def validate(self) -> None:
        _require_aware(self.started_at, "started_at")
        _require_aware(self.ended_at, "ended_at")
        if self.started_at >= self.ended_at:
            raise InvalidEstimate("execution segment must have positive duration")
        if self.work_minutes < 0:
            raise InvalidEstimate("segment work_minutes cannot be negative")
        if not self.humans and not self.physical_usages:
            raise InvalidEstimate("work segment requires real human or physical usage")
        if len({item.employee_id for item in self.humans}) != len(self.humans):
            raise InvalidEstimate("employee cannot be repeated in one segment")
        if len({item.physical_resource_id for item in self.physical_usages}) != len(self.physical_usages):
            raise InvalidEstimate("physical resource cannot be repeated in one segment")
        for value in (*self.humans, *self.physical_usages, *self.occupations):
            value.validate()


@dataclass(frozen=True)
class FinishOperation:
    organization_id: UUID
    operation_execution_id: UUID
    phase_id: UUID
    completed_at: datetime
    actor_id: UUID
    command_id: UUID
    source_system: str = "backend"

    def validate(self) -> None:
        _require_aware(self.completed_at, "completed_at")


@dataclass(frozen=True)
class StartOperationResult:
    operation_execution_id: UUID
    event_id: UUID
    planning_state_revision_id: UUID
    planning_state_revision_no: int
    remaining_estimate_revision_id: UUID
    idempotent_replay: bool = False


@dataclass(frozen=True)
class RegisterExecutionSegmentResult:
    segment_id: UUID
    segment_no: int
    event_id: UUID
    planning_state_revision_id: UUID
    planning_state_revision_no: int
    idempotent_replay: bool = False


@dataclass(frozen=True)
class FinishOperationResult:
    operation_execution_id: UUID
    phase_id: UUID
    operation_completed: bool
    event_id: UUID
    planning_state_revision_id: UUID
    planning_state_revision_no: int
    original_labor_minutes: int
    actual_labor_minutes: int
    variance_labor_minutes: int
    idempotent_replay: bool = False
