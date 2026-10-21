from __future__ import annotations

from datetime import date, time
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MasterModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MasterMutationResponse(MasterModel):
    entity: dict[str, Any]
    current_usage_count: int = 0
    plan_requires_reconciliation: bool = False
    idempotent_replay: bool = False


class MasterDataSnapshotResponse(MasterModel):
    people: list[dict[str, Any]]
    skills: list[dict[str, Any]]
    work_centers: list[dict[str, Any]]
    resource_types: list[dict[str, Any]]
    resources: list[dict[str, Any]]
    calendars: list[dict[str, Any]]
    calendar_windows: list[dict[str, Any]]
    calendar_exceptions: list[dict[str, Any]]
    plant: dict[str, Any]
    dev_only: bool


class PersonInput(MasterModel):
    code: str = Field(min_length=1, max_length=80)
    display_name: str = Field(min_length=1, max_length=200)
    base_calendar_id: UUID
    default_work_center_id: UUID | None = None


class PersonUpdate(PersonInput):
    expected_row_version: int = Field(ge=1)


class SkillInput(MasterModel):
    code: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    category: str | None = Field(default=None, max_length=100)


class SkillUpdate(SkillInput):
    expected_row_version: int = Field(ge=1)


class WorkCenterInput(MasterModel):
    code: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=200)
    capacity_mode: Literal["exclusive", "cumulative"]
    aggregate_capacity: Decimal | None = Field(default=None, gt=0)
    capacity_unit: str | None = Field(default=None, max_length=40)
    base_calendar_id: UUID | None = None

    @model_validator(mode="after")
    def cumulative_requires_capacity(self):
        if self.capacity_mode == "cumulative" and self.aggregate_capacity is None:
            raise ValueError("aggregate_capacity is required for cumulative centers")
        return self


class WorkCenterUpdate(WorkCenterInput):
    expected_row_version: int = Field(ge=1)


class ResourceInput(MasterModel):
    code: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=200)
    work_center_id: UUID
    resource_type_id: UUID
    scheduling_mode: Literal["exclusive", "cumulative"]
    capacity_units: Decimal = Field(gt=0)
    capacity_unit: str | None = Field(default=None, max_length=40)
    is_mobile: bool = False
    base_calendar_id: UUID


class ResourceUpdate(ResourceInput):
    expected_row_version: int = Field(ge=1)


class CalendarInput(MasterModel):
    code: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=200)
    timezone: str = Field(min_length=3, max_length=100)
    calendar_kind: str = Field(min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=1000)


class CalendarUpdate(CalendarInput):
    expected_row_version: int = Field(ge=1)


class CalendarWindowInput(MasterModel):
    weekday: int = Field(ge=1, le=7)
    local_start: time
    local_end: time
    shift_code: str | None = Field(default=None, max_length=80)
    capacity_factor: Decimal = Field(default=Decimal("1"), gt=0)

    @model_validator(mode="after")
    def valid_order(self):
        if self.local_start >= self.local_end:
            raise ValueError("local_start must be before local_end")
        return self


class DefineCalendarWindowsInput(MasterModel):
    expected_row_version: int = Field(ge=1)
    effective_from: date
    windows: list[CalendarWindowInput]


class CalendarExceptionInput(MasterModel):
    calendar_id: UUID
    exception_date: date
    effect: Literal["add", "remove", "replace"]
    local_start: time | None = None
    local_end: time | None = None
    capacity_factor: Decimal | None = Field(default=None, gt=0)
    reason: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def valid_range(self):
        if (self.local_start is None) != (self.local_end is None):
            raise ValueError("local_start and local_end must be supplied together")
        if self.local_start is not None and self.local_start >= self.local_end:
            raise ValueError("local_start must be before local_end")
        return self


class CalendarExceptionUpdate(CalendarExceptionInput):
    expected_row_version: int = Field(ge=1)


class StatusInput(MasterModel):
    status: Literal["active", "inactive"]
    expected_row_version: int = Field(ge=1)


class PersonSkillInput(MasterModel):
    valid_from: date | None = None
    valid_to: date | None = None
    level: Decimal | None = Field(default=None, ge=0)


class PlantUpdate(MasterModel):
    code: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=200)
    timezone: str = Field(min_length=3, max_length=100)
    base_calendar_id: UUID
    communication_threshold_business_days: int = Field(ge=0, le=365)
    expected_row_version: int = Field(ge=1)
