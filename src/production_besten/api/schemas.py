from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateProjectRequest(ApiModel):
    customer_id: UUID
    priority_id: UUID
    code: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    committed_date: date | None = None
    desired_start_at: datetime | None = None
    status: Literal["draft", "active", "inactive", "archived"] = "draft"


class ProjectResponse(ApiModel):
    id: UUID
    code: str
    name: str
    description: str | None
    status: str
    customer_id: UUID
    priority_id: UUID
    plant_id: UUID
    committed_date: date | None
    desired_start_at: datetime | None


class CreateBatchRequest(ApiModel):
    code: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str | None = None
    sequence_no: int | None = Field(default=None, gt=0)
    quantity: float | None = Field(default=None, gt=0)
    unit: str | None = None
    status: Literal["draft", "active", "inactive", "archived"] = "draft"
    hardware_status: Literal["unknown", "pending", "partial", "ready", "not_required"] = "unknown"
    hardware_available_at: datetime | None = None


class BatchResponse(ApiModel):
    id: UUID
    project_id: UUID
    code: str
    name: str
    description: str | None
    sequence_no: int
    quantity: float | None
    unit: str | None
    status: str
    hardware_status: str
    hardware_available_at: datetime | None


class DefineRouteRequest(ApiModel):
    route_version_id: UUID
    effective_at: datetime
    reason: str | None = None


class MutationResponse(ApiModel):
    id: UUID
    planning_state_revision_id: UUID | None = None
    planning_state_revision_number: int | None = None
    idempotent_replay: bool = False


class CreateOperationRequest(ApiModel):
    operation_definition_id: UUID
    route_step_id: UUID | None = None
    code: str = Field(min_length=1)
    name: str = Field(min_length=1)
    operation_kind: str = "production"
    status: Literal["draft", "active", "inactive", "archived"] = "draft"
    earliest_start_at: datetime | None = None
    settings: dict[str, Any] = Field(default_factory=dict)
    predecessor_operation_ids: list[UUID] = Field(default_factory=list)
    successor_operation_ids: list[UUID] = Field(default_factory=list)
    precedence_type: Literal["finish_start", "start_start", "finish_finish"] = "finish_start"
    lag_minutes: int = 0


class LaborRequirementRequest(ApiModel):
    skill_id: UUID
    min_people: int = Field(ge=1)
    max_people: int = Field(ge=1)
    work_minutes: int = Field(ge=0)
    productivity_curve: dict[str, Any] = Field(default_factory=dict)
    is_mandatory: bool = True


class PhysicalRequirementRequest(ApiModel):
    quantity: float = Field(gt=0)
    capacity_units: float = Field(gt=0)
    usage_mode: Literal["active_use", "occupation"]
    physical_resource_type_id: UUID | None = None
    physical_resource_group_id: UUID | None = None
    work_center_id: UUID | None = None
    is_mandatory: bool = True

    @model_validator(mode="after")
    def selector_required(self):
        if not any((self.physical_resource_type_id, self.physical_resource_group_id, self.work_center_id)):
            raise ValueError("a physical selector is required")
        return self


class GateRequest(ApiModel):
    timing: Literal["before_start", "before_finish"]
    gate_type: str = Field(min_length=1)
    material_requirement_id: UUID | None = None
    drawing_package_id: UUID | None = None
    hardware_project_lot_id: UUID | None = None
    milestone_definition_id: UUID | None = None
    available_at: datetime | None = None
    config: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def one_target(self):
        values = (self.material_requirement_id, self.drawing_package_id,
                  self.hardware_project_lot_id, self.milestone_definition_id,
                  self.available_at)
        if sum(value is not None for value in values) != 1:
            raise ValueError("exactly one gate target is required")
        return self


class CreatePhaseRequest(ApiModel):
    required_people: int = Field(default=0, ge=0, le=32767)
    sequence_no: int = Field(gt=0)
    code: str = Field(min_length=1)
    name: str = Field(min_length=1)
    estimate_kind: str
    original_estimate_minutes: int = Field(ge=0)
    split_policy: Literal["non_splittable", "splittable", "continuous"]
    route_step_phase_template_id: UUID | None = None
    status: Literal["draft", "active", "inactive", "archived"] = "draft"
    earliest_start_at: datetime | None = None
    labor_requirements: list[LaborRequirementRequest] = Field(default_factory=list)
    physical_requirements: list[PhysicalRequirementRequest] = Field(default_factory=list)
    gates: list[GateRequest] = Field(default_factory=list)


class FreezeDefinitionRequest(ApiModel):
    reason: str = Field(min_length=1)


class ProductDefinitionRevisionResponse(ApiModel):
    revision_id: UUID
    revision_number: int
    snapshot_hash: str
    created_at: datetime
    reused_existing_revision: bool
    idempotent_replay: bool
    planning_state_revision_id: UUID | None = None
    planning_state_revision_number: int | None = None


class StartOperationRequest(ApiModel):
    phase_id: UUID
    started_at: datetime
    origin_plan_version_id: UUID | None = None
    origin_operation_plan_result_id: UUID | None = None


class StartOperationResponse(ApiModel):
    execution_id: UUID
    event_id: UUID
    planning_state_revision_id: UUID
    planning_state_revision_number: int
    remaining_estimate_revision_id: UUID
    idempotent_replay: bool


class HumanUsageRequest(ApiModel):
    employee_id: UUID
    work_minutes: int = Field(gt=0)


class PhysicalUsageRequest(ApiModel):
    physical_resource_id: UUID
    work_minutes: int = Field(ge=0)
    capacity_units: float = Field(default=1, gt=0)


class PhysicalOccupationRequest(ApiModel):
    physical_resource_id: UUID
    started_at: datetime
    ended_at: datetime


class RegisterSegmentRequest(ApiModel):
    phase_id: UUID
    started_at: datetime
    ended_at: datetime
    work_minutes: int = Field(ge=0)
    humans: list[HumanUsageRequest] = Field(default_factory=list)
    physical_usages: list[PhysicalUsageRequest] = Field(default_factory=list)
    occupations: list[PhysicalOccupationRequest] = Field(default_factory=list)
    origin_assignment_segment_id: UUID | None = None


class SegmentResponse(ApiModel):
    segment_id: UUID
    segment_number: int
    event_id: UUID
    planning_state_revision_id: UUID
    planning_state_revision_number: int
    idempotent_replay: bool


class FinishOperationRequest(ApiModel):
    phase_id: UUID
    completed_at: datetime


class FinishOperationResponse(ApiModel):
    execution_id: UUID
    phase_id: UUID
    operation_completed: bool
    event_id: UUID
    planning_state_revision_id: UUID
    planning_state_revision_number: int
    original_labor_minutes: int
    actual_labor_minutes: int
    variance_labor_minutes: int
    idempotent_replay: bool


class RemainingInputRequest(ApiModel):
    dimension: Literal["LABOR_WORK", "ACTIVE_PHYSICAL_USE", "PHYSICAL_OCCUPATION"]
    minutes: int | None = Field(default=None, ge=0)
    expected_release_at: datetime | None = None
    phase_id: UUID | None = None
    skill_id: UUID | None = None
    min_people: int | None = Field(default=None, ge=1)
    max_people: int | None = Field(default=None, ge=1)
    physical_requirement_id: UUID | None = None
    physical_resource_id: UUID | None = None
    capacity_units: float | None = Field(default=None, gt=0)
    details: dict[str, Any] | None = None


class UpdateRemainingEstimateRequest(ApiModel):
    cutoff_at: datetime
    reason: str | None = None
    remaining: list[RemainingInputRequest] = Field(min_length=1)
    input_mode: Literal["delta", "remaining_duration", "expected_finish"] = "remaining_duration"


class RemainingEstimateResponse(ApiModel):
    revision_id: UUID
    revision_number: int
    original_minutes: int
    executed_minutes: int
    remaining_minutes: int
    updated_total_minutes: int
    planning_state_revision_id: UUID
    planning_state_revision_number: int
    effective_event_id: UUID
    current_plan_version_id: UUID | None


class HealthResponse(ApiModel):
    status: str


class AcceptReplanRequest(ApiModel):
    expected_promotion_lock_version: int = Field(gt=0)
    reason: str | None = Field(default=None, min_length=1)


class AcceptReplanResponse(ApiModel):
    scenario_id: UUID
    schedule_solution_id: UUID
    previous_plan_version_id: UUID | None
    plan_version_id: UUID
    plan_version_number: int
    promotion_lock_version: int
    promoted_at: datetime
    communication_recommended: bool
    idempotent_replay: bool


class ScenarioResponse(ApiModel):
    id: UUID
    status: str
    base_plan_version_id: UUID | None
    base_state_revision_id: UUID
    base_product_definition_revision_id: UUID
    stale: bool
    rejected: bool
    promoted: bool
    promoted_plan_version_id: UUID | None
    row_version: int
    promotion_lock_version: int
    changed_operations: int = 0
    affected_projects: int = 0
    customer_date_alerts: int = 0
    communication_recommended: bool = False
    impacts: list[dict[str, Any]] = Field(default_factory=list)


class PersonDisplay(ApiModel):
    id: UUID
    name: str


class DailyOperationResponse(ApiModel):
    operation_id: UUID
    project_id: UUID
    project_code: str
    project_name: str
    lot_code: str | None
    lot_name: str | None
    operation_code: str
    operation_name: str
    phase_name: str | None
    planned_start: datetime
    planned_finish: datetime
    people: list[PersonDisplay] = Field(default_factory=list)
    work_center: str | None
    physical_resource: str | None
    priority: str
    priority_rank: int
    operational_status: str
    progress_percent: int | None
    executed_minutes: int
    remaining_minutes: int | None
    blocker_code: str | None


class DailyBoardResponse(ApiModel):
    date: date
    operations: list[DailyOperationResponse]


class OperationDetailResponse(DailyOperationResponse):
    phase_id: UUID | None
    original_estimate_minutes: int | None
    plan_requires_reconciliation: bool
    next_operation_name: str | None


class ReplanFromOperationRequest(ApiModel):
    cutoff_at: datetime
    horizon_end: datetime
    reason: str | None = None


class ReplanResponse(ApiModel):
    scenario_id: UUID
    status: str
    complete: bool
    changed_operations: int
    affected_projects: int
    customer_date_alerts: int
    communication_recommended: bool
    idempotent_replay: bool


class MoveScheduledActivityRequest(ApiModel):
    base_plan_version_id: UUID
    requested_start: datetime
    cutoff_at: datetime
    horizon_end: datetime
    phase_id: UUID | None = None
    requested_resource_id: UUID | None = None


class ResizeScheduledActivityRequest(ApiModel):
    base_plan_version_id: UUID
    requested_duration_minutes: int = Field(gt=0)
    cutoff_at: datetime
    horizon_end: datetime
    phase_id: UUID | None = None
    resize_kind: Literal["PLANNED_DURATION_HYPOTHESIS"]


class ManualScheduleResponse(ApiModel):
    scenario_id: UUID
    schedule_solution_id: UUID
    status: str
    requested_start: datetime
    requested_finish: datetime | None
    proposed_start: datetime | None
    proposed_finish: datetime | None
    exact_request_satisfied: bool
    changed_operations: int
    affected_projects: int
    customer_date_alerts: int
    communication_recommended: bool
    explanations: list[str]
    stale: bool = False
    idempotent_replay: bool


class RejectReplanRequest(ApiModel):
    expected_row_version: int = Field(gt=0)
    reason: str = Field(min_length=1)


class RejectReplanResponse(ApiModel):
    scenario_id: UUID
    status: str
    row_version: int
    idempotent_replay: bool


class TimelineEntity(ApiModel):
    id: UUID
    name: str


class GanttCenter(TimelineEntity):
    capacity_mode: str
    aggregate_capacity: float | None


class GanttResource(TimelineEntity):
    work_center_id: UUID
    scheduling_mode: str
    capacity_units: float


class GanttGroupResponse(ApiModel):
    id: str
    label: str
    kind: Literal["center", "resource", "person", "project"]
    capacity_mode: str | None = None
    capacity: float | None = None


class GanttActualSegmentResponse(ApiModel):
    id: UUID
    started_at: datetime
    ended_at: datetime
    work_minutes: int


class GanttPlannedSegmentResponse(ApiModel):
    started_at: datetime
    ended_at: datetime
    phase_name: str | None = None


class GanttOperationResponse(ApiModel):
    operation_id: UUID
    project_id: UUID
    project_code: str
    project_name: str
    lot_code: str | None
    lot_name: str | None
    operation_code: str
    operation_name: str
    duration_minutes: int | None = None
    predecessors: list[TimelineEntity] = Field(default_factory=list)
    phase_id: UUID | None
    phase_name: str | None
    planned_start: datetime | None
    planned_finish: datetime | None
    group_ids: list[str]
    people: list[PersonDisplay] = Field(default_factory=list)
    centers: list[GanttCenter] = Field(default_factory=list)
    resources: list[GanttResource] = Field(default_factory=list)
    priority: str
    priority_rank: int
    operational_status: str
    executed_minutes: int
    remaining_minutes: int | None
    blocker_code: str | None
    actual_segments: list[GanttActualSegmentResponse] = Field(default_factory=list)
    planned_segments: list[GanttPlannedSegmentResponse] = Field(default_factory=list)
    stage_name: str | None = None
    stage_order: int | None = None
    operation_order: int | None = None
    committed_date: date | None = None
    split_policy: str | None = None
    skill_codes: list[str] = Field(default_factory=list)


class GanttOccupationResponse(ApiModel):
    id: UUID
    project_name: str
    lot_name: str | None
    resource_id: UUID
    resource_name: str
    group_id: str
    started_at: datetime
    ended_at: datetime
    source_kind: Literal["planned", "actual"]


class GanttWorkingWindowResponse(ApiModel):
    started_at: datetime
    ended_at: datetime
    kind: Literal["regular", "exception"]
    label: str | None = None


class GanttScenarioOptionResponse(ApiModel):
    id: UUID
    code: str
    name: str
    status: str
    stale: bool
    created_at: datetime
    scenario_kind: str = 'replan'
    expired: bool = False
    origin_plan_version_number: int | None = None


class GanttScenarioOperationResponse(ApiModel):
    operation_id: UUID
    planned_start: datetime | None
    planned_finish: datetime | None
    difference: Literal[
        "UNCHANGED", "SHIFTED", "ADVANCED", "DELAYED",
        "OUT_OF_HORIZON", "NEWLY_PLANNED",
    ]
    delta_minutes: int | None = None


class GanttScenarioResponse(ApiModel):
    id: UUID
    code: str
    name: str
    status: str
    scenario_kind: str = 'replan'
    solution_id: UUID | None = None
    complete: bool = True
    expired: bool = False
    origin_plan_version_number: int | None = None
    stale: bool
    row_version: int
    promotion_lock_version: int
    changed_operations: int
    affected_projects: int
    customer_date_alerts: int
    communication_recommended: bool
    project_finish_changes: list[dict[str, Any]] = Field(default_factory=list)
    operations: list[GanttScenarioOperationResponse] = Field(default_factory=list)
    manual_intent: dict[str, Any] | None = None


class GanttResponse(ApiModel):
    plant_name: str | None = None
    plan_version_id: UUID | None
    plan_version_number: int | None
    planning_state_revision_id: UUID
    timezone: str
    range_from: datetime
    range_to: datetime
    generated_at: datetime
    group_by: Literal["center", "resource", "person", "project"]
    groups: list[GanttGroupResponse]
    operations: list[GanttOperationResponse]
    occupations: list[GanttOccupationResponse]
    working_windows: list[GanttWorkingWindowResponse]
    available_scenarios: list[GanttScenarioOptionResponse]
    scenario: GanttScenarioResponse | None = None
