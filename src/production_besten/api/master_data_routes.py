from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Response, status

from production_besten.api.context import RequestContext, require_plant
from production_besten.api.dependencies import (
    ApiContainer, get_container, get_idempotency_key, get_request_context,
)
from production_besten.api.master_data_schemas import *
from production_besten.application.master_data_services import (
    MasterDataCommandService, MasterDataQueryService,
)
from production_besten.domain.master_data import MasterDataCommand
from production_besten.persistence.master_data_uow import PostgresMasterDataUnitOfWorkFactory


router = APIRouter(prefix="/master-data", tags=["master-data"])


def _factory(container: ApiContainer):
    return PostgresMasterDataUnitOfWorkFactory(container.engine)


def _result(value) -> MasterMutationResponse:
    return MasterMutationResponse(
        entity=value.entity, current_usage_count=value.current_usage_count,
        plan_requires_reconciliation=value.plan_requires_reconciliation,
        idempotent_replay=value.idempotent_replay,
    )


def _execute(container, context, key, action, entity_type, body,
             entity_id=None, expected=None):
    plant = require_plant(context)
    command = MasterDataCommand(
        key, context.organization_id, plant, context.user_id, action, entity_type,
        body, entity_id, expected,
    )
    return _result(MasterDataCommandService(_factory(container)).execute(command))


@router.get("/snapshot", response_model=MasterDataSnapshotResponse)
def snapshot(context: RequestContext = Depends(get_request_context),
             container: ApiContainer = Depends(get_container)):
    return MasterDataQueryService(_factory(container)).snapshot(
        context.organization_id, require_plant(context)
    )


@router.post("/people", response_model=MasterMutationResponse,
             status_code=status.HTTP_201_CREATED)
def create_person(body: PersonInput, context=Depends(get_request_context),
                  key=Depends(get_idempotency_key), container=Depends(get_container)):
    return _execute(container, context, key, "create", "person", body.model_dump())


@router.patch("/people/{entity_id}", response_model=MasterMutationResponse)
def update_person(entity_id: UUID, body: PersonUpdate, context=Depends(get_request_context),
                  key=Depends(get_idempotency_key), container=Depends(get_container)):
    payload = body.model_dump(exclude={"expected_row_version"})
    return _execute(container, context, key, "update", "person", payload,
                    entity_id, body.expected_row_version)


@router.post("/people/{entity_id}/status", response_model=MasterMutationResponse)
def person_status(entity_id: UUID, body: StatusInput, context=Depends(get_request_context),
                  key=Depends(get_idempotency_key), container=Depends(get_container)):
    return _execute(container, context, key, "set_status", "person",
                    {"status": body.status}, entity_id, body.expected_row_version)


@router.put("/people/{entity_id}/skills/{skill_id}", response_model=MasterMutationResponse)
def assign_skill(entity_id: UUID, skill_id: UUID, body: PersonSkillInput,
                 context=Depends(get_request_context), key=Depends(get_idempotency_key),
                 container=Depends(get_container)):
    return _execute(container, context, key, "assign_skill", "person_skill",
                    {**body.model_dump(), "skill_id": skill_id}, entity_id)


@router.delete("/people/{entity_id}/skills/{skill_id}", response_model=MasterMutationResponse)
def remove_skill(entity_id: UUID, skill_id: UUID,
                 context=Depends(get_request_context), key=Depends(get_idempotency_key),
                 container=Depends(get_container)):
    return _execute(container, context, key, "remove_skill", "person_skill",
                    {"skill_id": skill_id}, entity_id)


@router.post("/skills", response_model=MasterMutationResponse,
             status_code=status.HTTP_201_CREATED)
def create_skill(body: SkillInput, context=Depends(get_request_context),
                 key=Depends(get_idempotency_key), container=Depends(get_container)):
    return _execute(container, context, key, "create", "skill", body.model_dump())


@router.patch("/skills/{entity_id}", response_model=MasterMutationResponse)
def update_skill(entity_id: UUID, body: SkillUpdate, context=Depends(get_request_context),
                 key=Depends(get_idempotency_key), container=Depends(get_container)):
    return _execute(container, context, key, "update", "skill",
                    body.model_dump(exclude={"expected_row_version"}), entity_id,
                    body.expected_row_version)


@router.post("/skills/{entity_id}/status", response_model=MasterMutationResponse)
def skill_status(entity_id: UUID, body: StatusInput, context=Depends(get_request_context),
                 key=Depends(get_idempotency_key), container=Depends(get_container)):
    return _execute(container, context, key, "set_status", "skill",
                    {"status": body.status}, entity_id, body.expected_row_version)


@router.post("/work-centers", response_model=MasterMutationResponse,
             status_code=status.HTTP_201_CREATED)
def create_center(body: WorkCenterInput, context=Depends(get_request_context),
                  key=Depends(get_idempotency_key), container=Depends(get_container)):
    return _execute(container, context, key, "create", "work_center", body.model_dump())


@router.patch("/work-centers/{entity_id}", response_model=MasterMutationResponse)
def update_center(entity_id: UUID, body: WorkCenterUpdate, context=Depends(get_request_context),
                  key=Depends(get_idempotency_key), container=Depends(get_container)):
    return _execute(container, context, key, "update", "work_center",
                    body.model_dump(exclude={"expected_row_version"}), entity_id,
                    body.expected_row_version)


@router.post("/work-centers/{entity_id}/status", response_model=MasterMutationResponse)
def center_status(entity_id: UUID, body: StatusInput, context=Depends(get_request_context),
                  key=Depends(get_idempotency_key), container=Depends(get_container)):
    return _execute(container, context, key, "set_status", "work_center",
                    {"status": body.status}, entity_id, body.expected_row_version)


@router.post("/resources", response_model=MasterMutationResponse,
             status_code=status.HTTP_201_CREATED)
def create_resource(body: ResourceInput, context=Depends(get_request_context),
                    key=Depends(get_idempotency_key), container=Depends(get_container)):
    return _execute(container, context, key, "create", "resource", body.model_dump())


@router.patch("/resources/{entity_id}", response_model=MasterMutationResponse)
def update_resource(entity_id: UUID, body: ResourceUpdate, context=Depends(get_request_context),
                    key=Depends(get_idempotency_key), container=Depends(get_container)):
    return _execute(container, context, key, "update", "resource",
                    body.model_dump(exclude={"expected_row_version"}), entity_id,
                    body.expected_row_version)


@router.post("/resources/{entity_id}/status", response_model=MasterMutationResponse)
def resource_status(entity_id: UUID, body: StatusInput, context=Depends(get_request_context),
                    key=Depends(get_idempotency_key), container=Depends(get_container)):
    return _execute(container, context, key, "set_status", "resource",
                    {"status": body.status}, entity_id, body.expected_row_version)


@router.post("/calendars", response_model=MasterMutationResponse,
             status_code=status.HTTP_201_CREATED)
def create_calendar(body: CalendarInput, context=Depends(get_request_context),
                    key=Depends(get_idempotency_key), container=Depends(get_container)):
    return _execute(container, context, key, "create", "calendar", body.model_dump())


@router.patch("/calendars/{entity_id}", response_model=MasterMutationResponse)
def update_calendar(entity_id: UUID, body: CalendarUpdate, context=Depends(get_request_context),
                    key=Depends(get_idempotency_key), container=Depends(get_container)):
    return _execute(container, context, key, "update", "calendar",
                    body.model_dump(exclude={"expected_row_version"}), entity_id,
                    body.expected_row_version)


@router.put("/calendars/{entity_id}/windows", response_model=MasterMutationResponse)
def define_windows(entity_id: UUID, body: DefineCalendarWindowsInput,
                   context=Depends(get_request_context), key=Depends(get_idempotency_key),
                   container=Depends(get_container)):
    return _execute(container, context, key, "define_windows", "calendar_windows",
                    body.model_dump(exclude={"expected_row_version"}), entity_id,
                    body.expected_row_version)


@router.post("/calendars/{entity_id}/status", response_model=MasterMutationResponse)
def calendar_status(entity_id: UUID, body: StatusInput, context=Depends(get_request_context),
                    key=Depends(get_idempotency_key), container=Depends(get_container)):
    return _execute(container, context, key, "set_status", "calendar",
                    {"status": body.status}, entity_id, body.expected_row_version)


@router.post("/calendar-exceptions", response_model=MasterMutationResponse,
             status_code=status.HTTP_201_CREATED)
def create_exception(body: CalendarExceptionInput, context=Depends(get_request_context),
                     key=Depends(get_idempotency_key), container=Depends(get_container)):
    return _execute(container, context, key, "create", "calendar_exception", body.model_dump())


@router.patch("/calendar-exceptions/{entity_id}", response_model=MasterMutationResponse)
def update_exception(entity_id: UUID, body: CalendarExceptionUpdate,
                     context=Depends(get_request_context), key=Depends(get_idempotency_key),
                     container=Depends(get_container)):
    return _execute(container, context, key, "update", "calendar_exception",
                    body.model_dump(exclude={"expected_row_version"}), entity_id,
                    body.expected_row_version)


@router.patch("/plant", response_model=MasterMutationResponse)
def update_plant(body: PlantUpdate, context=Depends(get_request_context),
                 key=Depends(get_idempotency_key), container=Depends(get_container)):
    plant = require_plant(context)
    return _execute(container, context, key, "update", "plant",
                    body.model_dump(exclude={"expected_row_version"}), plant,
                    body.expected_row_version)
