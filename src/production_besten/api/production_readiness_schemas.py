from typing import Literal
from datetime import date, datetime
from uuid import UUID
from pydantic import Field, field_validator
from production_besten.api.schemas import ApiModel


class ReadinessItem(ApiModel):
    code: str
    label: str
    satisfied: bool
    applicable: bool = True
    detail: str


class ProductionReadiness(ApiModel):
    project_id: UUID
    timezone: str
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
    horizon_start: date | datetime = Field(description='Fecha local de la planta; un timestamp explícito debe incluir timezone.')
    horizon_end: date | datetime = Field(description='Fin exclusivo: comienzo de la fecha local seleccionada, o timestamp con timezone.')

    @field_validator('horizon_start','horizon_end',mode='before')
    @classmethod
    def local_date_or_aware_timestamp(cls,value):
        if isinstance(value,str):
            value=date.fromisoformat(value) if len(value)==10 else datetime.fromisoformat(value.replace('Z','+00:00'))
        if isinstance(value,datetime) and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError('Indicá una fecha local o un timestamp con zona horaria.')
        return value


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
