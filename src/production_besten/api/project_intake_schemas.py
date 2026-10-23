from datetime import date, datetime
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field
from production_besten.api.production_readiness_schemas import ProductionReadiness


class IntakeModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IntakeOption(IntakeModel):
    id: UUID
    code: str | None = None
    name: str


class IntakeOptions(IntakeModel):
    customers: list[IntakeOption]
    priorities: list[IntakeOption]
    plant: IntakeOption
    timezone: str
    measurement_supported: bool
    replanteo_supported: bool


class IntakeMilestone(IntakeModel):
    supported: bool
    occurred_at: datetime | None = None
    notes: str | None = None


class InstallationLocation(IntakeModel):
    installation_site_name: str | None = Field(default=None, max_length=200)
    installation_address: str | None = Field(default=None, max_length=500)
    installation_locality: str | None = Field(default=None, max_length=200)
    installation_contact_name: str | None = Field(default=None, max_length=200)
    installation_contact_phone: str | None = Field(default=None, max_length=80)
    installation_access_notes: str | None = Field(default=None, max_length=2000)


class InstallationLocationUpdate(InstallationLocation):
    expected_row_version: int = Field(ge=1)


class ProjectCompletion(IntakeModel):
    expected_row_version: int = Field(ge=1)


class IntakeProject(InstallationLocation):
    id: UUID
    plant_id: UUID
    code: str
    name: str
    description: str | None
    customer_id: UUID
    customer_name: str
    customer_email: str | None
    customer_phone: str | None
    priority_id: UUID
    priority_code: str
    status: str
    committed_date: date | None
    desired_start_at: datetime | None
    estimated_date: date | None
    communicated_date: date | None
    row_version: int
    lot_count: int
    operation_count: int
    definition_revision_no: int | None
    ready_for_definition: bool
    plannable: bool
    overdue: bool
    plan_requires_reconciliation: bool
    communication_recommended: bool
    measurement: IntakeMilestone
    replanteo: IntakeMilestone
    operation_ids: list[UUID]
    planned_operation_ids: list[UUID] = Field(default_factory=list)
    production_readiness: ProductionReadiness | None = None


class ProjectIntakeUpdate(IntakeModel):
    name: str = Field(min_length=1, max_length=200)
    customer_id: UUID
    priority_id: UUID
    description: str | None = Field(default=None, max_length=4000)
    committed_date: date | None = None
    expected_row_version: int = Field(ge=1)


class ProjectIntakeStatus(IntakeModel):
    status: Literal["active", "inactive", "archived"]
    expected_row_version: int = Field(ge=1)


class ProjectMilestoneInput(IntakeModel):
    occurred_at: datetime
    notes: str | None = Field(default=None, max_length=2000)
    expected_row_version: int = Field(ge=1)


class IntakeMutation(IntakeModel):
    project: IntakeProject
    idempotent_replay: bool = False
