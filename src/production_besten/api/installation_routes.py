from datetime import date, datetime
from typing import Literal
from uuid import UUID
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from production_besten.api.context import require_plant, require_execution_permission
from production_besten.api.dependencies import get_container, get_request_context
from production_besten.api.project_intake_schemas import InstallationLocation
from production_besten.persistence.installation_queries import installation_overview

router = APIRouter(tags=['installations'])


class InstallationPerson(BaseModel):
    id: UUID
    name: str


class InstallationOperation(BaseModel):
    operation_id: UUID
    operation_name: str
    phase_id: UUID | None
    phase_name: str | None
    execution_id: UUID | None
    state: Literal['not_ready','ready','scheduled','running','finished','blocked']
    ready_to_schedule: bool
    ready_to_start: bool
    blockers: list[str]
    planned_start: datetime | None
    planned_finish: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    last_segment_end: datetime | None
    duration_minutes: int
    required_people: int
    people: list[InstallationPerson]
    resources: list[InstallationPerson]
    executed_minutes: int
    remaining_minutes: int | None
    remaining_revision_no: int | None
    overdue: bool
    scheduled_dates: list[date] = Field(default_factory=list)


class InstallationProject(InstallationLocation):
    project_id: UUID
    project_code: str
    project_name: str
    customer_name: str
    row_version: int
    timezone: str
    committed_date: date | None = None
    desired_start_at: datetime | None = None
    required: bool
    can_complete: bool
    completed: bool
    installations: list[InstallationOperation]


@router.get('/installations', response_model=list[InstallationProject])
def agenda(context=Depends(get_request_context), container=Depends(get_container)):
    with container.engine.connect() as conn:
        return [p for p in installation_overview(conn, context.organization_id, require_plant(context)) if p['required']]


@router.get('/projects/{project_id}/installations', response_model=InstallationProject)
def detail(project_id: UUID, context=Depends(get_request_context), container=Depends(get_container)):
    with container.engine.connect() as conn:
        return installation_overview(conn, context.organization_id, require_plant(context), project_id)[0]


from production_besten.api.dependencies import get_idempotency_key
from production_besten.api.schemas import ReplanFromOperationRequest, ReplanResponse, UpdateRemainingEstimateRequest


@router.post('/projects/{project_id}/installation-plan', response_model=ReplanResponse)
def plan(project_id: UUID, body: ReplanFromOperationRequest, key=Depends(get_idempotency_key), context=Depends(get_request_context), container=Depends(get_container)):
    from production_besten.domain.replanning import ReplanRequest
    from production_besten.application.replanning_services import ReplanService
    from production_besten.persistence.scheduling_uow import PostgresSchedulingUnitOfWorkFactory
    plant = require_plant(context)
    container.queries.project(context.organization_id, project_id, plant)
    base = container.queries.replan_context(context.organization_id, plant)
    r = ReplanService(PostgresSchedulingUnitOfWorkFactory(container.engine)).execute(ReplanRequest(
        context.organization_id,plant,context.user_id,str(key),'INSTALL-'+key.hex,body.reason or 'Planificación de instalación',
        body.cutoff_at,body.horizon_end,base['definition_id'],base['state_id'],base['plan_id'],project_id=project_id,
        parameters={'source':'installations'}))
    return ReplanResponse(scenario_id=r.scenario_id,status=r.status,complete=r.complete,changed_operations=r.changed_operations,
                          affected_projects=len(r.frontier_project_ids),customer_date_alerts=r.customer_date_alerts,
                          communication_recommended=r.customer_date_alerts>0,idempotent_replay=r.idempotent_replay)


class InstallationRemaining(UpdateRemainingEstimateRequest):
    expected_revision_no: int = Field(ge=1)


class InstallationRemainingResult(BaseModel):
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
    idempotent_replay: bool


@router.post('/installations/{operation_id}/remaining-estimate', response_model=InstallationRemainingResult)
def remaining(operation_id: UUID, body: InstallationRemaining, key=Depends(get_idempotency_key), context=Depends(get_request_context), container=Depends(get_container)):
    return save_remaining(operation_id, body, key, context, container, installation_only=True)


@router.post('/operations/{operation_id}/execution/remaining-estimate', response_model=InstallationRemainingResult, tags=['execution'])
def production_remaining(operation_id: UUID, body: InstallationRemaining, key=Depends(get_idempotency_key), context=Depends(get_request_context), container=Depends(get_container)):
    return save_remaining(operation_id, body, key, context, container, installation_only=False)


def save_remaining(operation_id, body, key, context, container, *, installation_only):
    require_execution_permission(context)
    from dataclasses import asdict, replace
    import hashlib,json
    from sqlalchemy import text
    from production_besten.domain.errors import EntityNotFound,IdempotencyConflict
    from production_besten.api.mappers import remaining_command
    from production_besten.persistence.remaining_estimate_uow import PostgresRemainingEstimateUnitOfWork
    plant=require_plant(context)
    hash_name = 'installation_remaining_hash' if installation_only else 'production_remaining_hash'
    action_code = 'INSTALLATION_REMAINING_UPDATED' if installation_only else 'PRODUCTION_REMAINING_UPDATED'
    with container.engine.begin() as conn:
        conn.execute(text('SELECT id FROM core.organizations WHERE id=:org FOR UPDATE'),{'org':context.organization_id})
        operation=conn.scalar(text("SELECT o.id FROM production.required_operations o JOIN core.projects p ON p.organization_id=o.organization_id AND p.id=o.project_id WHERE o.organization_id=:org AND p.plant_id=:plant AND o.id=:id AND (NOT :installation_only OR o.operation_kind='installation')"),{'org':context.organization_id,'plant':plant,'id':operation_id,'installation_only':installation_only})
        if not operation:raise EntityNotFound()
        digest=hashlib.sha256(json.dumps([str(plant),str(operation_id),str(context.user_id),body.model_dump(mode='json')],sort_keys=True).encode()).hexdigest()
        replay=conn.execute(text('SELECT metadata,after_data FROM audit.audit_entries WHERE organization_id=:org AND request_id=:key LIMIT 1'),{'org':context.organization_id,'key':key}).mappings().one_or_none()
        if replay:
            if replay['metadata'].get(hash_name)!=digest:raise IdempotencyConflict('La clave corresponde a otra intención.')
            return replay['after_data']|{'idempotent_replay':True}
        value=container.queries.remaining_context(context.organization_id,operation_id,plant)
        command=replace(remaining_command(body,value,organization_id=context.organization_id,actor_id=context.user_id),expected_revision_no=body.expected_revision_no)
        command.validate()
        adapter=PostgresRemainingEstimateUnitOfWork(None);adapter._connection=conn
        result=json.loads(json.dumps(asdict(adapter.update_remaining_estimate(command)),default=str))
        conn.execute(text("INSERT INTO audit.audit_entries(organization_id,actor_user_id,action_code,entity_type,entity_id,request_id,transaction_key,after_data,metadata) VALUES (:org,:actor,:action,'required_operation',:id,:key,:key,CAST(:after AS jsonb),CAST(:meta AS jsonb))"),{'org':context.organization_id,'actor':context.user_id,'id':operation_id,'key':key,'action':action_code,'after':json.dumps(result),'meta':json.dumps({hash_name:digest})})
        return result|{'idempotent_replay':False}
