from __future__ import annotations

import logging
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from production_besten.domain.errors import (
    DomainError,
    EntityNotFound,
    ExecutionAlreadyActive,
    ExecutionAlreadyCompleted,
    GateBlocked,
    IdempotencyConflict,
    InvalidEstimate,
    InvalidExecutionState,
    InvalidProductDefinition,
    PrecedenceCycle,
    ProductDefinitionConflict,
    ReplanConflict,
    RevisionConflict,
    StructuralAvailabilityConflict,
    SchedulingBaseStale,
)
from production_besten.domain.master_data import InvalidMasterData, MasterDataConflict

logger = logging.getLogger(__name__)


def error_response(request: Request, status: int, code: str, message: str,
                   exc: Exception) -> JSONResponse:
    request_id = str(uuid4())
    logger.log(logging.ERROR if status >= 500 else logging.WARNING,
               'API error request_id=%s code=%s status=%s method=%s path=%s detail=%s',
               request_id, code, status, request.method, request.url.path, str(exc),
               exc_info=(type(exc), exc, exc.__traceback__) if status >= 500 else None)
    return JSONResponse(status_code=status, headers={'X-Request-Id': request_id},
                        content={'error': {'code': code, 'message': message,
                                           'request_id': request_id}})


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
        if isinstance(exc, EntityNotFound):
            status, code, message = 404, "RESOURCE_NOT_FOUND", "resource not found"
        elif isinstance(exc, (RevisionConflict, ProductDefinitionConflict, PrecedenceCycle, IdempotencyConflict,
                              ExecutionAlreadyActive, ExecutionAlreadyCompleted,
                              InvalidExecutionState, GateBlocked, StructuralAvailabilityConflict,
                              ReplanConflict, SchedulingBaseStale)):
            status, code, message = 409, _code(exc), str(exc)
        elif isinstance(exc, (InvalidEstimate, InvalidProductDefinition)):
            status, code, message = 400, _code(exc), str(exc)
        elif isinstance(exc, MasterDataConflict):
            status, code, message = 409, _code(exc), str(exc)
        elif isinstance(exc, InvalidMasterData):
            status, code, message = 400, _code(exc), str(exc)
        else:
            status, code, message = 400, "DOMAIN_ERROR", str(exc)
        return error_response(request, status, code, message, exc)

    @app.exception_handler(IntegrityError)
    async def integrity_error_handler(request: Request, exc: IntegrityError) -> JSONResponse:
        return error_response(request, 409, 'PERSISTENCE_CONFLICT',
                              'the request conflicts with persisted data', exc)

    @app.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
        return error_response(request, 500, 'INTERNAL_ERROR',
                              'an unexpected internal error occurred', exc)


def _code(exc: Exception) -> str:
    name = type(exc).__name__
    return "".join(("_" + char if char.isupper() else char) for char in name).lstrip("_").upper()
