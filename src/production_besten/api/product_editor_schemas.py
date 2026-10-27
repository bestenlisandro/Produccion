from typing import Literal
from uuid import UUID
from pydantic import ConfigDict, Field, model_validator
from production_besten.api.schemas import ApiModel, LaborRequirementRequest, PhysicalRequirementRequest


class EditorPhysicalRequirement(PhysicalRequirementRequest):
    quantity: float = Field(gt=0, allow_inf_nan=False)
    capacity_units: float = Field(gt=0, allow_inf_nan=False)


class EditorItem(ApiModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class EditorPhase(EditorItem):
    id: UUID | None = None
    code: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=200)
    estimate_kind: Literal['elapsed', 'labor'] = 'elapsed'
    original_estimate_minutes: int = Field(default=60, ge=0)
    split_policy: Literal['splittable', 'non_splittable', 'continuous'] = 'splittable'
    labor_requirements: list[LaborRequirementRequest] = Field(default_factory=list)
    physical_requirements: list[EditorPhysicalRequirement] = Field(default_factory=list)


class EditorOperation(EditorItem):
    @model_validator(mode="before")
    @classmethod
    def ignore_presentation_metadata(cls, value):
        # Read-only fields may be round-tripped by existing clients; the catalog is authoritative.
        if isinstance(value, dict):
            return {k:v for k,v in value.items() if k not in {"stage_code","stage_name","stage_order","operation_order"}}
        return value

    id: UUID | None = None
    code: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=200)
    operation_definition_id: UUID
    operation_kind: Literal['production', 'installation'] = 'production'
    predecessor_codes: list[str] = Field(default_factory=list)
    phases: list[EditorPhase] = Field(default_factory=list, max_length=200)


class EditorLot(EditorItem):
    id: UUID | None = None
    code: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    quantity: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    unit: str | None = Field(default=None, max_length=40)
    route_version_id: UUID | None = None
    operations: list[EditorOperation] = Field(default_factory=list, max_length=200)


class EditorSave(ApiModel):
    expected_row_version: int = Field(ge=1)
    lots: list[EditorLot] = Field(default_factory=list, max_length=100)


class EditorAction(ApiModel):
    expected_row_version: int = Field(ge=1)
    reason: str = Field(default='Definición productiva desde interfaz', min_length=1, max_length=1000)


class EditorRevision(ApiModel):
    id: UUID
    revision_no: int
    created_at: str
    lot_count: int
    operation_count: int
    snapshot: dict


class EditorOperationView(EditorOperation):
    # Override the input-only round-trip filter for response serialization.
    @model_validator(mode="before")
    @classmethod
    def ignore_presentation_metadata(cls, value):
        return value

    # Audit replays recorded before M12 lack this additive presentation metadata.
    stage_code: str | None = None
    stage_name: str | None = None
    stage_order: int | None = None
    operation_order: int | None = None


class EditorLotView(EditorLot):
    operations: list[EditorOperationView]


class EditorDefinition(ApiModel):
    project_id: UUID
    row_version: int
    draft_id: UUID | None
    status: Literal['empty', 'draft', 'frozen']
    lots: list[EditorLotView]
    errors: list[str]
    revisions: list[EditorRevision]
    idempotent_replay: bool = False


class EditorOption(ApiModel):
    id: UUID
    code: str
    name: str


class EditorStageOption(EditorOption):
    display_order: int
    status: str


class EditorOptions(ApiModel):
    operations: list[EditorStageOption]
    skills: list[EditorOption]
    centers: list[EditorOption]
    resource_types: list[EditorOption]
    resource_groups: list[EditorOption]
    routes: list[EditorOption]
