from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Any
from uuid import UUID

from production_besten.domain.errors import InvalidSchedulingInput


@dataclass(frozen=True)
class GenerateSchedule:
    organization_id: UUID
    plant_id: UUID
    actor_id: UUID
    code: str
    name: str
    horizon_start: datetime
    horizon_end: datetime
    product_definition_revision_id: UUID
    planning_state_revision_id: UUID
    project_ids: tuple[UUID, ...] = ()
    parameters: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if not self.code.strip() or not self.name.strip():
            raise InvalidSchedulingInput("scenario code and name are required")
        for value, label in ((self.horizon_start, "horizon_start"), (self.horizon_end, "horizon_end")):
            if value.tzinfo is None or value.utcoffset() is None:
                raise InvalidSchedulingInput(f"{label} must include a timezone")
        if self.horizon_start >= self.horizon_end:
            raise InvalidSchedulingInput("horizon must have positive duration")
        if len(set(self.project_ids)) != len(self.project_ids):
            raise InvalidSchedulingInput("project_ids cannot be repeated")
        if not isinstance(self.parameters, dict):
            raise InvalidSchedulingInput("parameters must be an object")


@dataclass(frozen=True)
class ScheduleGenerationResult:
    scenario_id: UUID
    solution_id: UUID
    status: str
    complete: bool
    planned_phases: int
    blocked_phases: int
    out_of_horizon_phases: int
    solution_sha256: str | None
    elapsed_ms: int
    failed_reason: str | None = None


@dataclass(frozen=True)
class TimeWindow:
    start: datetime
    end: datetime


@dataclass(frozen=True)
class CapacityUsage:
    window: TimeWindow
    capacity_units: float


@dataclass(frozen=True)
class CalendarInterval:
    weekday: int
    local_start: time
    local_end: time
    valid_from: date | None
    valid_to: date | None
    capacity_factor: float = 1.0


@dataclass(frozen=True)
class CalendarException:
    date: date
    effect: str
    start: datetime | None
    end: datetime | None
    capacity_factor: float | None = None


@dataclass(frozen=True)
class CalendarData:
    id: UUID
    timezone: str
    intervals: tuple[CalendarInterval, ...]
    exceptions: tuple[CalendarException, ...]


@dataclass(frozen=True)
class EmployeeData:
    id: UUID
    code: str
    calendar_id: UUID
    skills: frozenset[UUID]


@dataclass(frozen=True)
class ResourceData:
    id: UUID
    code: str
    calendar_id: UUID
    resource_type_id: UUID
    work_center_id: UUID
    group_ids: frozenset[UUID]
    scheduling_mode: str
    capacity_units: float


@dataclass(frozen=True)
class WorkCenterData:
    id: UUID
    code: str
    calendar_id: UUID
    capacity_units: float


@dataclass(frozen=True)
class LaborNeed:
    skill_id: UUID
    min_people: int
    max_people: int
    work_minutes: int


@dataclass(frozen=True)
class PhysicalNeed:
    id: UUID
    resource_type_id: UUID | None
    resource_group_id: UUID | None
    work_center_id: UUID | None
    quantity: float
    capacity_units: float
    usage_mode: str


@dataclass(frozen=True)
class GateData:
    gate_type: str
    release_at: datetime | None
    blocker: str | None


@dataclass(frozen=True)
class PhaseData:
    id: UUID
    operation_id: UUID
    project_id: UUID
    project_code: str
    lot_id: UUID | None
    lot_code: str | None
    lot_sequence: int
    operation_code: str
    sequence_no: int
    code: str
    original_minutes: int
    estimate_kind: str
    split_policy: str
    earliest_start: datetime | None
    scalable_labor: bool
    labor: tuple[LaborNeed, ...]
    physical: tuple[PhysicalNeed, ...]
    gates: tuple[GateData, ...]
    manual_intent_priority: bool = False
    requested_resource_id: UUID | None = None


@dataclass(frozen=True)
class ProjectData:
    id: UUID
    code: str
    priority_code: str
    priority_rank: int
    committed_date: date | None


@dataclass(frozen=True)
class PrecedenceData:
    predecessor_operation_id: UUID
    successor_operation_id: UUID
    precedence_type: str
    lag_minutes: int


@dataclass(frozen=True)
class OvertimeData:
    id: UUID
    start: datetime
    end: datetime
    project_id: UUID | None
    employee_id: UUID | None
    resource_id: UUID | None
    work_center_id: UUID | None
    max_minutes: int | None


@dataclass(frozen=True)
class SchedulingInput:
    organization_id: UUID
    plant_id: UUID
    plant_calendar_id: UUID
    horizon_start: datetime
    horizon_end: datetime
    product_definition_revision_id: UUID
    planning_state_revision_id: UUID
    base_plan_version_id: UUID | None
    projects: tuple[ProjectData, ...]
    phases: tuple[PhaseData, ...]
    precedences: tuple[PrecedenceData, ...]
    calendars: dict[UUID, CalendarData]
    employees: tuple[EmployeeData, ...]
    resources: tuple[ResourceData, ...]
    unavailability: dict[UUID, tuple[TimeWindow, ...]]
    actual_occupations: dict[UUID, tuple[TimeWindow, ...]]
    actual_capacity_usage: dict[UUID, tuple[CapacityUsage, ...]]
    overtime: tuple[OvertimeData, ...]
    work_centers: dict[UUID, WorkCenterData] = field(default_factory=dict)


@dataclass(frozen=True)
class PlannedSegment:
    start: datetime
    end: datetime
    work_minutes: int
    employee_ids: tuple[UUID, ...]
    resource_ids: tuple[UUID, ...]
    occupation_resource_ids: tuple[UUID, ...]
    resource_capacity_units: tuple[tuple[UUID, float], ...] = ()
    overtime_minutes: int = 0
    employee_overtime: tuple[tuple[UUID, UUID | None], ...] = ()
    resource_overtime: tuple[tuple[UUID, UUID | None], ...] = ()


@dataclass(frozen=True)
class PhaseOutcome:
    phase_id: UUID
    status: str
    planned_work_minutes: int
    remaining_work_minutes: int
    segments: tuple[PlannedSegment, ...]
    blockers: tuple[str, ...]
    ready_at: datetime


@dataclass(frozen=True)
class SchedulingOutput:
    status: str
    complete: bool
    outcomes: tuple[PhaseOutcome, ...]
    failed_reason: str | None = None
