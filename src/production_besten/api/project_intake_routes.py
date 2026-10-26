from datetime import date
from uuid import UUID
from fastapi import APIRouter, Depends, Query
from production_besten.api.context import require_plant
from production_besten.api.dependencies import get_container, get_request_context, get_idempotency_key
from production_besten.api.project_intake_schemas import (
    IntakeProject, IntakeMutation, IntakeOptions, ProjectIntakeUpdate, ProjectIntakeStatus, ProjectMilestoneInput,
    CustomerCreate, CustomerMutation,
)
from production_besten.application.project_intake_services import ProjectIntakeService
from production_besten.domain.project_intake import ProjectIntakeCommand
from production_besten.persistence.project_intake_uow import PostgresProjectIntakeUnitOfWorkFactory

router=APIRouter(tags=["projects"])


def service(container):
    return ProjectIntakeService(PostgresProjectIntakeUnitOfWorkFactory(container.engine,failpoint=container.failpoints.get("project_intake")))


def execute(container,context,key,action,body,project=None):
    payload=body.model_dump(exclude={"expected_row_version"})
    return service(container).execute(ProjectIntakeCommand(context.organization_id,require_plant(context),context.user_id,key,
        action,payload,project,getattr(body,"expected_row_version",None)))


@router.get("/projects",response_model=list[IntakeProject])
def list_projects(search:str=Query(default="",max_length=200),status:str|None=None,priority:str|None=None,
                  customer_id:UUID|None=None,committed_from:date|None=None,committed_to:date|None=None,
                  context=Depends(get_request_context),container=Depends(get_container)):
    return service(container).list(context.organization_id,require_plant(context),search=search,status=status,priority=priority,
        customer_id=customer_id,committed_from=committed_from,committed_to=committed_to)


@router.get("/project-intake/options",response_model=IntakeOptions)
def options(context=Depends(get_request_context),container=Depends(get_container)):
    return service(container).options(context.organization_id,require_plant(context))


@router.patch("/projects/{project_id}",response_model=IntakeMutation)
def update(project_id:UUID,body:ProjectIntakeUpdate,key=Depends(get_idempotency_key),context=Depends(get_request_context),container=Depends(get_container)):
    return execute(container,context,key,"update",body,project_id)


@router.post('/customers', response_model=CustomerMutation, status_code=201)
def create_customer(body: CustomerCreate, key=Depends(get_idempotency_key), context=Depends(get_request_context), container=Depends(get_container)):
    return execute(container, context, key, 'create_customer', body)


@router.post("/projects/{project_id}/status",response_model=IntakeMutation)
def set_status(project_id:UUID,body:ProjectIntakeStatus,key=Depends(get_idempotency_key),context=Depends(get_request_context),container=Depends(get_container)):
    return execute(container,context,key,"status",body,project_id)


@router.post("/projects/{project_id}/measurement",response_model=IntakeMutation)
def measurement(project_id:UUID,body:ProjectMilestoneInput,key=Depends(get_idempotency_key),context=Depends(get_request_context),container=Depends(get_container)):
    return execute(container,context,key,"measurement",body,project_id)


@router.post("/projects/{project_id}/replanteo",response_model=IntakeMutation)
def replanteo(project_id:UUID,body:ProjectMilestoneInput,key=Depends(get_idempotency_key),context=Depends(get_request_context),container=Depends(get_container)):
    return execute(container,context,key,"replanteo",body,project_id)


from production_besten.api.project_intake_schemas import InstallationLocationUpdate, ProjectCompletion


@router.patch('/projects/{project_id}/installation-location', response_model=IntakeMutation)
def location(project_id: UUID, body: InstallationLocationUpdate, key=Depends(get_idempotency_key), context=Depends(get_request_context), container=Depends(get_container)):
    return execute(container, context, key, 'location', body, project_id)


@router.post('/projects/{project_id}/complete', response_model=IntakeMutation)
def complete(project_id: UUID, body: ProjectCompletion, key=Depends(get_idempotency_key), context=Depends(get_request_context), container=Depends(get_container)):
    return execute(container, context, key, 'complete', body, project_id)
