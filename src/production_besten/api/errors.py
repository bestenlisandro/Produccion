from __future__ import annotations

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
    RevisionConflict,
    StructuralAvailabilityConflict,
)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
        if isinstance(exc, EntityNotFound):
            status, code, message = 404, "RESOURCE_NOT_FOUND", "resource not found"
        elif isinstance(exc, (RevisionConflict, ProductDefinitionConflict, PrecedenceCycle, IdempotencyConflict,
                              ExecutionAlreadyActive, ExecutionAlreadyCompleted,
                              InvalidExecutionState, GateBlocked, StructuralAvailabilityConflict)):
            status, code, message = 409, _code(exc), str(exc)
        elif isinstance(exc, (InvalidEstimate, InvalidProductDefinition)):
            status, code, message = 400, _code(exc), str(exc)
        else:
            status, code, message = 400, "DOMAIN_ERROR", str(exc)
        return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})

    @app.exception_handler(IntegrityError)
    async def integrity_error_handler(request: Request, exc: IntegrityError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"error": {"code": "PERSISTENCE_CONFLICT", "message": "the request conflicts with persisted data"}})

    @app.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=500, content={"error": {"code": "INTERNAL_ERROR", "message": "an unexpected internal error occurred"}})


def _code(exc: Exception) -> str:
    name = type(exc).__name__
    return "".join(("_" + char if char.isupper() else char) for char in name).lstrip("_").upper()
