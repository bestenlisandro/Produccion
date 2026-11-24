from datetime import datetime
from uuid import UUID
from pydantic import BaseModel


class ExecutionChoice(BaseModel):
    id: UUID
    name: str


class ExecutionUsage(ExecutionChoice):
    minutes: int


class ExecutionPhase(ExecutionChoice):
    original_estimate_minutes: int
    required_people: int
    started: bool
    completed: bool


class ExecutionSegment(BaseModel):
    id: UUID
    phase_id: UUID
    phase_name: str
    started_at: datetime
    ended_at: datetime
    work_minutes: int
    people: list[ExecutionUsage]
    resources: list[ExecutionUsage]


class OperationExecutionResponse(BaseModel):
    timezone: str
    execution_id: UUID | None
    execution_status: str | None
    started_at: datetime | None
    completed_at: datetime | None
    remaining_revision_no: int | None
    remaining_minutes: int | None
    can_execute: bool
    blockers: list[str]
    phases: list[ExecutionPhase]
    people: list[ExecutionChoice]
    resources: list[ExecutionChoice]
    segments: list[ExecutionSegment]
