from uuid import UUID
from fastapi import APIRouter, Depends
from production_besten.api.context import require_plant
from production_besten.api.dependencies import get_container, get_request_context, get_idempotency_key
from production_besten.api.product_editor_schemas import EditorDefinition, EditorOptions, EditorSave, EditorAction
from production_besten.application.product_editor_services import ProductEditorService
from production_besten.persistence.product_editor_uow import PostgresProductEditorUnitOfWork

router = APIRouter(tags=['product-definition'])


def service(container):
    return ProductEditorService(lambda: PostgresProductEditorUnitOfWork(container.engine, failpoint=container.failpoints.get('product_editor')))


@router.get('/product-definition/options', response_model=EditorOptions)
def options(context=Depends(get_request_context), container=Depends(get_container)):
    return service(container).options(context.organization_id, require_plant(context))


@router.get('/projects/{project_id}/product-definition', response_model=EditorDefinition)
def detail(project_id: UUID, context=Depends(get_request_context), container=Depends(get_container)):
    return service(container).read(context.organization_id, require_plant(context), project_id)


@router.put('/projects/{project_id}/product-definition', response_model=EditorDefinition)
def save(project_id: UUID, body: EditorSave, key=Depends(get_idempotency_key), context=Depends(get_request_context), container=Depends(get_container)):
    return service(container).execute(context.organization_id, require_plant(context), context.user_id, key, project_id, 'save', body.model_dump())


@router.post('/projects/{project_id}/product-definition/{action}', response_model=EditorDefinition)
def action(project_id: UUID, action: str, body: EditorAction, key=Depends(get_idempotency_key), context=Depends(get_request_context), container=Depends(get_container)):
    return service(container).execute(context.organization_id, require_plant(context), context.user_id, key, project_id, action, body.model_dump())
