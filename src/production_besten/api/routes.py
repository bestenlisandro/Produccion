from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from production_besten.api.context import RequestContext, require_plant
from production_besten.api.dependencies import ApiContainer, get_container, get_idempotency_key, get_request_context
from production_besten.api.mappers import remaining_command
from production_besten.api.schemas import *
from production_besten.api.project_intake_schemas import IntakeProject
from production_besten.api.project_intake_routes import service as intake_service, execute as execute_intake
from production_besten.application.execution_services import FinishOperationService, RegisterExecutionSegmentService, StartOperationService
from production_besten.application.product_definition_services import (
    CreateProductDefinitionRevisionService, CreateProductionBatchService, CreateProjectService,
    CreateRequiredOperationPhaseService, CreateRequiredOperationService, DefineBatchRouteService,
)
from production_besten.application.update_remaining_estimate import UpdateRemainingEstimateService
from production_besten.application.replanning_services import (
    AcceptReplanService, MoveScheduledActivityService, RejectReplanService,
    ReplanService, ResizeScheduledActivityService,
)
from production_besten.domain.execution import FinishOperation, HumanUsage, PhysicalOccupation, PhysicalUsage, RegisterExecutionSegment, StartOperation
from production_besten.domain.product_definition import (
    CreateProductDefinitionRevision, CreateProductionBatch, CreateProject, CreateRequiredOperation,
    CreateRequiredOperationPhase, DefineBatchRoute, LaborRequirement, OperationGate, PhysicalRequirement,
)
from production_besten.domain.replanning import (
    AcceptReplan, MoveScheduledActivity, RejectReplan, ReplanRequest,
    ResizeScheduledActivity,
)
from production_besten.persistence.execution_uow import PostgresExecutionUnitOfWorkFactory
from production_besten.persistence.product_definition_uow import PostgresProductDefinitionUnitOfWorkFactory
from production_besten.persistence.remaining_estimate_uow import PostgresUnitOfWorkFactory
from production_besten.persistence.scheduling_uow import PostgresSchedulingUnitOfWorkFactory

router = APIRouter(responses={
    400: {"description": "Semantically invalid request"},
    404: {"description": "Resource not found or inaccessible in tenant"},
    409: {"description": "State, concurrency, availability, gate or idempotency conflict"},
    422: {"description": "Structurally invalid path, header or body"},
    500: {"description": "Unexpected internal error without implementation details"},
    503: {"description": "Required infrastructure or identity provider unavailable"},
})


def _product_factory(container: ApiContainer):
    return PostgresProductDefinitionUnitOfWorkFactory(container.engine, failpoint=container.failpoints.get("product"))


def _execution_factory(container: ApiContainer):
    return PostgresExecutionUnitOfWorkFactory(container.engine, failpoint=container.failpoints.get("execution"))


def _scheduling_factory(container: ApiContainer):
    return PostgresSchedulingUnitOfWorkFactory(
        container.engine, failpoint=container.failpoints.get("scheduling")
    )


def _mutation(value) -> MutationResponse:
    return MutationResponse(id=value.entity_id, planning_state_revision_id=value.planning_state_revision_id,
        planning_state_revision_number=value.planning_state_revision_no, idempotent_replay=value.idempotent_replay)


@router.get("/health", response_model=HealthResponse, tags=["system"], summary="Process liveness")
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/ready", response_model=HealthResponse, tags=["system"], summary="PostgreSQL readiness")
def ready(container: ApiContainer = Depends(get_container)) -> HealthResponse:
    container.queries.ready()
    return HealthResponse(status="ready")


@router.post("/projects", response_model=IntakeProject, status_code=status.HTTP_201_CREATED,
             tags=["projects"], summary="Create a project")
def create_project(body: CreateProjectRequest, context: RequestContext = Depends(get_request_context),
                   key: UUID = Depends(get_idempotency_key), container: ApiContainer = Depends(get_container)):
    return execute_intake(container,context,key,"create",body)["project"]


@router.get("/projects/{project_id}", response_model=IntakeProject, tags=["projects"], summary="Get a project")
def get_project(project_id: UUID, context: RequestContext = Depends(get_request_context),
                container: ApiContainer = Depends(get_container)) -> ProjectResponse:
    return intake_service(container).detail(context.organization_id,require_plant(context),project_id)


@router.post("/projects/{project_id}/batches", response_model=BatchResponse, status_code=status.HTTP_201_CREATED,
             tags=["batches"], summary="Create a project production batch")
def create_batch(project_id: UUID, body: CreateBatchRequest, command_id: UUID = Depends(get_idempotency_key),
                 context: RequestContext = Depends(get_request_context), container: ApiContainer = Depends(get_container)) -> BatchResponse:
    container.queries.project(context.organization_id, project_id, context.plant_id)
    result = CreateProductionBatchService(_product_factory(container)).execute(CreateProductionBatch(
        context.organization_id, project_id, body.code, body.name, context.user_id, command_id,
        body.description, body.sequence_no, body.quantity, body.unit, body.status,
        body.hardware_status, body.hardware_available_at, "api"))
    row = next(value for value in container.queries.batches(context.organization_id, project_id, context.plant_id) if value["id"] == result.entity_id)
    return BatchResponse.model_validate(row)


@router.get("/projects/{project_id}/batches", response_model=list[BatchResponse], tags=["batches"], summary="List project batches")
def list_batches(project_id: UUID, context: RequestContext = Depends(get_request_context),
                 container: ApiContainer = Depends(get_container)) -> list[BatchResponse]:
    return [BatchResponse.model_validate(value) for value in container.queries.batches(context.organization_id, project_id, context.plant_id)]


@router.post("/batches/{batch_id}/route", response_model=MutationResponse, status_code=status.HTTP_201_CREATED,
             tags=["definition"], summary="Assign a published route to a batch")
def define_route(batch_id: UUID, body: DefineRouteRequest, command_id: UUID = Depends(get_idempotency_key),
                 context: RequestContext = Depends(get_request_context), container: ApiContainer = Depends(get_container)) -> MutationResponse:
    container.queries.batch(context.organization_id, batch_id, context.plant_id)
    return _mutation(DefineBatchRouteService(_product_factory(container)).execute(DefineBatchRoute(
        context.organization_id, batch_id, body.route_version_id, body.effective_at,
        context.user_id, command_id, body.reason, "api")))


@router.post("/batches/{batch_id}/operations", response_model=MutationResponse, status_code=status.HTTP_201_CREATED,
             tags=["definition"], summary="Create required operation demand")
def create_operation(batch_id: UUID, body: CreateOperationRequest, command_id: UUID = Depends(get_idempotency_key),
                     context: RequestContext = Depends(get_request_context), container: ApiContainer = Depends(get_container)) -> MutationResponse:
    batch = container.queries.batch(context.organization_id, batch_id, context.plant_id)
    return _mutation(CreateRequiredOperationService(_product_factory(container)).execute(CreateRequiredOperation(
        context.organization_id, batch["project_id"], body.operation_definition_id, body.code, body.name,
        context.user_id, command_id, batch_id, body.route_step_id, body.operation_kind, body.status,
        body.earliest_start_at, body.settings, tuple(body.predecessor_operation_ids),
        tuple(body.successor_operation_ids), body.precedence_type, body.lag_minutes, "api")))


@router.post("/operations/{operation_id}/phases", response_model=MutationResponse, status_code=status.HTTP_201_CREATED,
             tags=["definition"], summary="Create an operation phase and its requirements")
def create_phase(operation_id: UUID, body: CreatePhaseRequest, command_id: UUID = Depends(get_idempotency_key),
                 context: RequestContext = Depends(get_request_context), container: ApiContainer = Depends(get_container)) -> MutationResponse:
    container.queries.operation(context.organization_id, operation_id, context.plant_id)
    labor = tuple(LaborRequirement(x.skill_id, x.min_people, x.max_people, x.work_minutes, x.productivity_curve, x.is_mandatory) for x in body.labor_requirements)
    physical = tuple(PhysicalRequirement(x.quantity, x.capacity_units, x.usage_mode, x.physical_resource_type_id, x.physical_resource_group_id, x.work_center_id, x.is_mandatory) for x in body.physical_requirements)
    gates = tuple(OperationGate(x.timing, x.gate_type, x.material_requirement_id, x.drawing_package_id, x.hardware_project_lot_id, x.milestone_definition_id, x.available_at, x.config) for x in body.gates)
    return _mutation(CreateRequiredOperationPhaseService(_product_factory(container)).execute(CreateRequiredOperationPhase(
        context.organization_id, operation_id, body.sequence_no, body.code, body.name, body.estimate_kind,
        body.original_estimate_minutes, body.split_policy, context.user_id, command_id,
        body.route_step_phase_template_id, body.status, body.earliest_start_at, labor, physical, gates, "api", required_people=body.required_people)))


@router.post("/projects/{project_id}/product-definition-revisions", response_model=ProductDefinitionRevisionResponse,
             status_code=status.HTTP_201_CREATED, tags=["definition"], summary="Freeze the plant product definition")
def freeze_definition(project_id: UUID, body: FreezeDefinitionRequest, response: Response,
                      command_id: UUID = Depends(get_idempotency_key), context: RequestContext = Depends(get_request_context),
                      container: ApiContainer = Depends(get_container)) -> ProductDefinitionRevisionResponse:
    project = container.queries.project(context.organization_id, project_id, context.plant_id)
    result = CreateProductDefinitionRevisionService(_product_factory(container)).execute(CreateProductDefinitionRevision(
        context.organization_id, project["plant_id"], context.user_id, command_id, body.reason, "api"))
    if result.semantic_duplicate or result.idempotent_replay:
        response.status_code = status.HTTP_200_OK
    return ProductDefinitionRevisionResponse(revision_id=result.revision_id, revision_number=result.revision_no,
        snapshot_hash=result.snapshot_sha256, created_at=container.queries.revision_created_at(context.organization_id, result.revision_id),
        reused_existing_revision=result.semantic_duplicate, idempotent_replay=result.idempotent_replay,
        planning_state_revision_id=result.planning_state_revision_id,
        planning_state_revision_number=result.planning_state_revision_no)


@router.post("/operations/{operation_id}/start", response_model=StartOperationResponse, status_code=status.HTTP_201_CREATED,
             tags=["execution"], summary="Start planned or unplanned execution")
def start_operation(operation_id: UUID, body: StartOperationRequest, response: Response,
                    command_id: UUID = Depends(get_idempotency_key), context: RequestContext = Depends(get_request_context),
                    container: ApiContainer = Depends(get_container)) -> StartOperationResponse:
    container.queries.operation(context.organization_id, operation_id, context.plant_id)
    result = StartOperationService(_execution_factory(container)).execute(StartOperation(context.organization_id,
        operation_id, body.phase_id, body.started_at, context.user_id, command_id,
        body.origin_plan_version_id, body.origin_operation_plan_result_id, "api"))
    if result.idempotent_replay:
        response.status_code = status.HTTP_200_OK
    return StartOperationResponse(execution_id=result.operation_execution_id, event_id=result.event_id,
        planning_state_revision_id=result.planning_state_revision_id,
        planning_state_revision_number=result.planning_state_revision_no,
        remaining_estimate_revision_id=result.remaining_estimate_revision_id,
        idempotent_replay=result.idempotent_replay)


@router.post("/executions/{execution_id}/segments", response_model=SegmentResponse, status_code=status.HTTP_201_CREATED,
             tags=["execution"], summary="Register an actual execution segment")
def register_segment(execution_id: UUID, body: RegisterSegmentRequest, response: Response,
                     command_id: UUID = Depends(get_idempotency_key), context: RequestContext = Depends(get_request_context),
                     container: ApiContainer = Depends(get_container)) -> SegmentResponse:
    container.queries.execution(context.organization_id, execution_id, context.plant_id)
    result = RegisterExecutionSegmentService(_execution_factory(container)).execute(RegisterExecutionSegment(
        context.organization_id, execution_id, body.phase_id, body.started_at, body.ended_at,
        body.work_minutes, context.user_id, command_id,
        tuple(HumanUsage(x.employee_id, x.work_minutes) for x in body.humans),
        tuple(PhysicalUsage(x.physical_resource_id, x.work_minutes, x.capacity_units) for x in body.physical_usages),
        tuple(PhysicalOccupation(x.physical_resource_id, x.started_at, x.ended_at) for x in body.occupations),
        body.origin_assignment_segment_id, "api"))
    if result.idempotent_replay:
        response.status_code = status.HTTP_200_OK
    return SegmentResponse(segment_id=result.segment_id, segment_number=result.segment_no, event_id=result.event_id,
        planning_state_revision_id=result.planning_state_revision_id,
        planning_state_revision_number=result.planning_state_revision_no,
        idempotent_replay=result.idempotent_replay)


@router.post("/operations/{operation_id}/finish", response_model=FinishOperationResponse,
             tags=["execution"], summary="Finish an operation phase")
def finish_operation(operation_id: UUID, body: FinishOperationRequest, command_id: UUID = Depends(get_idempotency_key),
                     context: RequestContext = Depends(get_request_context), container: ApiContainer = Depends(get_container)) -> FinishOperationResponse:
    execution_id = container.queries.execution_for_operation(context.organization_id, operation_id, context.plant_id, require_active=False)
    result = FinishOperationService(_execution_factory(container)).execute(FinishOperation(
        context.organization_id, execution_id, body.phase_id, body.completed_at, context.user_id, command_id, "api"))
    return FinishOperationResponse(execution_id=result.operation_execution_id, phase_id=result.phase_id,
        operation_completed=result.operation_completed, event_id=result.event_id,
        planning_state_revision_id=result.planning_state_revision_id,
        planning_state_revision_number=result.planning_state_revision_no,
        original_labor_minutes=result.original_labor_minutes, actual_labor_minutes=result.actual_labor_minutes,
        variance_labor_minutes=result.variance_labor_minutes, idempotent_replay=result.idempotent_replay)


@router.post("/operations/{operation_id}/remaining-estimate", response_model=RemainingEstimateResponse,
             tags=["execution"], summary="Update the current remaining estimate")
def update_remaining(operation_id: UUID, body: UpdateRemainingEstimateRequest,
                     context: RequestContext = Depends(get_request_context), container: ApiContainer = Depends(get_container)) -> RemainingEstimateResponse:
    value = container.queries.remaining_context(context.organization_id, operation_id, context.plant_id)
    result = UpdateRemainingEstimateService(PostgresUnitOfWorkFactory(container.engine)).execute(
        remaining_command(body, value, organization_id=context.organization_id, actor_id=context.user_id))
    return RemainingEstimateResponse(revision_id=result.revision_id, revision_number=result.revision_no,
        original_minutes=result.original_labor_minutes, executed_minutes=result.executed_labor_minutes,
        remaining_minutes=result.remaining_labor_minutes, updated_total_minutes=result.updated_total_labor_minutes,
        planning_state_revision_id=result.planning_state_revision_id,
        planning_state_revision_number=result.planning_state_revision_no,
        effective_event_id=result.effective_event_id, current_plan_version_id=result.current_plan_version_id)


@router.post("/scenarios/{scenario_id}/accept", response_model=AcceptReplanResponse,
             status_code=status.HTTP_201_CREATED, tags=["planning"],
             summary="Atomically promote a ready replan scenario")
def accept_replan(scenario_id: UUID, body: AcceptReplanRequest, response: Response,
                  command_id: UUID = Depends(get_idempotency_key),
                  context: RequestContext = Depends(get_request_context),
                  container: ApiContainer = Depends(get_container)) -> AcceptReplanResponse:
    plant_id = require_plant(context)
    result = AcceptReplanService(_scheduling_factory(container)).execute(AcceptReplan(
        context.organization_id, plant_id, context.user_id, command_id, scenario_id,
        body.expected_promotion_lock_version, body.reason,
    ))
    if result.idempotent_replay:
        response.status_code = status.HTTP_200_OK
    return AcceptReplanResponse(
        scenario_id=result.scenario_id,
        schedule_solution_id=result.schedule_solution_id,
        previous_plan_version_id=result.previous_plan_version_id,
        plan_version_id=result.plan_version_id,
        plan_version_number=result.plan_version_no,
        promotion_lock_version=result.promotion_lock_version,
        promoted_at=result.promoted_at,
        communication_recommended=result.communication_recommended,
        idempotent_replay=result.idempotent_replay,
    )


@router.get("/scenarios/{scenario_id}", response_model=ScenarioResponse,
            tags=["planning"], summary="Read scenario promotion and stale state")
def get_scenario(scenario_id: UUID,
                 context: RequestContext = Depends(get_request_context),
                 container: ApiContainer = Depends(get_container)) -> ScenarioResponse:
    return ScenarioResponse.model_validate(container.queries.scenario(
        context.organization_id, scenario_id, context.plant_id
    ))


@router.get("/planning/current/day", response_model=DailyBoardResponse,
            tags=["planning"], summary="Read the current production schedule for one day")
def get_daily_board(day: date = Query(alias="date"), context: RequestContext = Depends(get_request_context),
                    container: ApiContainer = Depends(get_container)) -> DailyBoardResponse:
    plant_id = require_plant(context)
    return DailyBoardResponse(date=day, operations=[DailyOperationResponse.model_validate(row)
        for row in container.queries.daily_board(context.organization_id, plant_id, day)])


@router.get("/planning/current/gantt", response_model=GanttResponse,
            tags=["planning"], summary="Read the current plan and optional scenario as a timeline")
def get_current_gantt(
    range_from: datetime = Query(alias="from"),
    range_to: datetime = Query(alias="to"),
    group_by: Literal["center", "resource", "person", "project"] = "center",
    scenario_id: UUID | None = None,
    context: RequestContext = Depends(get_request_context),
    container: ApiContainer = Depends(get_container),
) -> GanttResponse:
    plant_id = require_plant(context)
    return GanttResponse.model_validate(container.queries.gantt(
        context.organization_id, plant_id, range_from, range_to,
        group_by, scenario_id,
    ))


@router.get("/operations/{operation_id}", response_model=OperationDetailResponse,
            tags=["execution"], summary="Read the current operational view of an operation")
def get_operation_detail(operation_id: UUID, context: RequestContext = Depends(get_request_context),
                         container: ApiContainer = Depends(get_container)) -> OperationDetailResponse:
    return OperationDetailResponse.model_validate(container.queries.operation_detail(
        context.organization_id, context.plant_id, operation_id))


@router.post("/operations/{operation_id}/replan", response_model=ReplanResponse,
             status_code=status.HTTP_201_CREATED, tags=["planning"],
             summary="Simulate replanning from an operation")
def replan_from_operation(operation_id: UUID, body: ReplanFromOperationRequest, response: Response,
                          command_id: UUID = Depends(get_idempotency_key),
                          context: RequestContext = Depends(get_request_context),
                          container: ApiContainer = Depends(get_container)) -> ReplanResponse:
    plant_id = require_plant(context)
    container.queries.operation(context.organization_id, operation_id, plant_id)
    base = container.queries.replan_context(context.organization_id, plant_id)
    result = ReplanService(_scheduling_factory(container)).execute(ReplanRequest(
        context.organization_id, plant_id, context.user_id, str(command_id),
        f"RP-{command_id.hex[:12]}", body.reason or "Reprogramación operativa",
        body.cutoff_at, body.horizon_end, base["definition_id"], base["state_id"],
        base["plan_id"], trigger_operation_id=operation_id,
        parameters={"source": "daily-board"},
    ))
    if result.idempotent_replay:
        response.status_code = status.HTTP_200_OK
    return ReplanResponse(scenario_id=result.scenario_id, status=result.status,
        complete=result.complete, changed_operations=result.changed_operations,
        affected_projects=len(result.frontier_project_ids),
        customer_date_alerts=result.customer_date_alerts,
        communication_recommended=result.customer_date_alerts > 0,
        idempotent_replay=result.idempotent_replay)


def _manual_response(result) -> ManualScheduleResponse:
    return ManualScheduleResponse(
        scenario_id=result.scenario_id,
        schedule_solution_id=result.solution_id,
        status=result.status,
        requested_start=result.requested_start,
        requested_finish=result.requested_finish,
        proposed_start=result.proposed_start,
        proposed_finish=result.proposed_finish,
        exact_request_satisfied=result.exact_request_satisfied,
        changed_operations=result.changed_operations,
        affected_projects=result.affected_projects,
        customer_date_alerts=result.customer_date_alerts,
        communication_recommended=result.customer_date_alerts > 0,
        explanations=list(result.explanations),
        idempotent_replay=result.idempotent_replay,
    )


@router.post("/planning/activities/{operation_id}/move",
             response_model=ManualScheduleResponse,
             status_code=status.HTTP_201_CREATED, tags=["planning"],
             summary="Simulate a preferred start/resource without changing CURRENT")
def move_scheduled_activity(
    operation_id: UUID, body: MoveScheduledActivityRequest, response: Response,
    command_id: UUID = Depends(get_idempotency_key),
    context: RequestContext = Depends(get_request_context),
    container: ApiContainer = Depends(get_container),
) -> ManualScheduleResponse:
    plant_id = require_plant(context)
    base = container.queries.replan_context(context.organization_id, plant_id)
    result = MoveScheduledActivityService(_scheduling_factory(container)).execute(
        MoveScheduledActivity(
            context.organization_id, plant_id, context.user_id, command_id,
            operation_id, body.base_plan_version_id, base["definition_id"],
            base["state_id"], body.requested_start, body.cutoff_at,
            body.horizon_end, body.phase_id, body.requested_resource_id,
        )
    )
    if result.idempotent_replay:
        response.status_code = status.HTTP_200_OK
    return _manual_response(result)


@router.post("/planning/activities/{operation_id}/resize",
             response_model=ManualScheduleResponse,
             status_code=status.HTTP_201_CREATED, tags=["planning"],
             summary="Simulate a planned-duration hypothesis without changing reality")
def resize_scheduled_activity(
    operation_id: UUID, body: ResizeScheduledActivityRequest, response: Response,
    command_id: UUID = Depends(get_idempotency_key),
    context: RequestContext = Depends(get_request_context),
    container: ApiContainer = Depends(get_container),
) -> ManualScheduleResponse:
    plant_id = require_plant(context)
    base = container.queries.replan_context(context.organization_id, plant_id)
    result = ResizeScheduledActivityService(_scheduling_factory(container)).execute(
        ResizeScheduledActivity(
            context.organization_id, plant_id, context.user_id, command_id,
            operation_id, body.base_plan_version_id, base["definition_id"],
            base["state_id"], body.requested_duration_minutes, body.cutoff_at,
            body.horizon_end, body.phase_id,
        )
    )
    if result.idempotent_replay:
        response.status_code = status.HTTP_200_OK
    return _manual_response(result)


@router.post("/scenarios/{scenario_id}/reject", response_model=RejectReplanResponse,
             tags=["planning"], summary="Reject a replan proposal without reverting reality")
def reject_replan(scenario_id: UUID, body: RejectReplanRequest,
                  command_id: UUID = Depends(get_idempotency_key),
                  context: RequestContext = Depends(get_request_context),
                  container: ApiContainer = Depends(get_container)) -> RejectReplanResponse:
    del command_id  # transport-level requirement; domain idempotency is scenario lifecycle based
    plant_id = require_plant(context)
    result = RejectReplanService(_scheduling_factory(container)).execute(RejectReplan(
        context.organization_id, plant_id, context.user_id, scenario_id,
        body.expected_row_version, body.reason))
    return RejectReplanResponse(scenario_id=result.scenario_id, status=result.status,
        row_version=result.row_version, idempotent_replay=result.idempotent_replay)
