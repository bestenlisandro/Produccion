from uuid import UUID
from fastapi import APIRouter,Depends
from production_besten.api.context import require_plant
from production_besten.api.dependencies import get_container,get_request_context,get_idempotency_key
from production_besten.api.production_readiness_schemas import ProductionReadiness,ReleaseProjectRequest,ProductionSimulationRequest,ProductionSimulation
from production_besten.application.production_release_services import ProductionReleaseService
from production_besten.persistence.production_release_uow import PostgresProductionReleaseUnitOfWork
router=APIRouter(tags=['production-readiness'])


def service(container):
    return ProductionReleaseService(lambda:PostgresProductionReleaseUnitOfWork(container.engine,failpoint=container.failpoints.get('production_release'),clock=container.clock))


@router.get('/projects/production-readiness',response_model=list[ProductionReadiness])
def readiness_list(context=Depends(get_request_context),container=Depends(get_container)):
    return list(service(container).read(context.organization_id,require_plant(context)).values())


@router.get('/projects/{project_id}/production-readiness',response_model=ProductionReadiness)
def readiness(project_id:UUID,context=Depends(get_request_context),container=Depends(get_container)):
    return service(container).read(context.organization_id,require_plant(context),project_id)


@router.post('/projects/{project_id}/release',response_model=ProductionReadiness)
def release(project_id:UUID,body:ReleaseProjectRequest,key=Depends(get_idempotency_key),context=Depends(get_request_context),container=Depends(get_container)):
    return service(container).execute(context.organization_id,require_plant(context),context.user_id,key,project_id,'release',body.model_dump())


@router.post('/projects/{project_id}/unrelease',response_model=ProductionReadiness)
def unrelease(project_id:UUID,body:ReleaseProjectRequest,key=Depends(get_idempotency_key),context=Depends(get_request_context),container=Depends(get_container)):
    return service(container).execute(context.organization_id,require_plant(context),context.user_id,key,project_id,'unrelease',body.model_dump())


@router.post('/projects/{project_id}/simulations',response_model=ProductionSimulation)
def simulate(project_id:UUID,body:ProductionSimulationRequest,key=Depends(get_idempotency_key),context=Depends(get_request_context),container=Depends(get_container)):
    return service(container).execute(context.organization_id,require_plant(context),context.user_id,key,project_id,'simulate',body.model_dump())
