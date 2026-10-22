from typing import Literal
from datetime import datetime
from uuid import UUID
from pydantic import Field
from production_besten.api.schemas import ApiModel


class ReadinessItem(ApiModel):
    code: str
    label: str
    satisfied: bool
    applicable: bool = True
    detail: str


class ProductionReadiness(ApiModel):
    project_id: UUID
    row_version: int
    evaluation_token: str
    evaluated_at: str
    state: Literal['not_ready','ready','released','blocked']
    ready: bool
    released: bool
    eligible: bool
    definition_revision_id: UUID | None
    definition_revision_no: int | None
    released_at: str | None
    items: list[ReadinessItem]
    history: list[dict]
    idempotent_replay: bool = False


class ReleaseProjectRequest(ApiModel):
    expected_row_version: int = Field(ge=1)
    evaluation_token: str = Field(pattern=r'^[a-f0-9]{64}$')
    reason: str = Field(min_length=1,max_length=1000)


class ProductionSimulationRequest(ReleaseProjectRequest):
    horizon_start: datetime
    horizon_end: datetime


class ProductionSimulation(ApiModel):
    scenario_id: UUID
    solution_id: UUID
    status: str
    complete: bool
    planned_phases: int
    blocked_phases: int
    out_of_horizon_phases: int = 0
    solution_sha256: str | None = None
    elapsed_ms: int = 0
    failed_reason: str | None = None
    idempotent_replay: bool = False
