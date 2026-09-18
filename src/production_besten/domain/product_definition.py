from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any
from uuid import UUID

from .errors import InvalidProductDefinition


def _required(value: str, field_name: str) -> None:
    if not value or not value.strip():
        raise InvalidProductDefinition(f"{field_name} is required")


def _aware(value: datetime | None, field_name: str) -> None:
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise InvalidProductDefinition(f"{field_name} must include a timezone")


@dataclass(frozen=True)
class CreateProject:
    organization_id: UUID
    plant_id: UUID
    customer_id: UUID
    priority_id: UUID
    code: str
    name: str
    actor_id: UUID
    description: str | None = None
    committed_date: date | None = None
    desired_start_at: datetime | None = None
    status: str = "draft"

    def validate(self) -> None:
        _required(self.code, "code")
        _required(self.name, "name")
        _aware(self.desired_start_at, "desired_start_at")


@dataclass(frozen=True)
class CreateProductionBatch:
    """Creates the project-owned productive lot stored in core.project_lots."""

    organization_id: UUID
    project_id: UUID
    code: str
    name: str
    actor_id: UUID
    command_id: UUID
    description: str | None = None
    sequence_no: int | None = None
    quantity: float | None = None
    unit: str | None = None
    status: str = "draft"
    hardware_status: str = "unknown"
    hardware_available_at: datetime | None = None
    source_system: str = "backend"

    def validate(self) -> None:
        _required(self.code, "code")
        _required(self.name, "name")
        if self.sequence_no is not None and self.sequence_no <= 0:
            raise InvalidProductDefinition("sequence_no must be positive")
        if self.quantity is not None and self.quantity <= 0:
            raise InvalidProductDefinition("quantity must be positive")
        _aware(self.hardware_available_at, "hardware_available_at")


@dataclass(frozen=True)
class DefineBatchRoute:
    organization_id: UUID
    project_lot_id: UUID
    route_version_id: UUID
    effective_at: datetime
    actor_id: UUID
    command_id: UUID
    reason: str | None = None
    source_system: str = "backend"

    def validate(self) -> None:
        _aware(self.effective_at, "effective_at")


@dataclass(frozen=True)
class CreateRequiredOperation:
    organization_id: UUID
    project_id: UUID
    operation_definition_id: UUID
    code: str
    name: str
    actor_id: UUID
    command_id: UUID
    project_lot_id: UUID | None = None
    route_step_id: UUID | None = None
    operation_kind: str = "production"
    status: str = "draft"
    earliest_start_at: datetime | None = None
    settings: dict[str, Any] = field(default_factory=dict)
    predecessor_operation_ids: tuple[UUID, ...] = ()
    successor_operation_ids: tuple[UUID, ...] = ()
    precedence_type: str = "finish_start"
    lag_minutes: int = 0
    source_system: str = "backend"

    def validate(self) -> None:
        _required(self.code, "code")
        _required(self.name, "name")
        _aware(self.earliest_start_at, "earliest_start_at")
        if not isinstance(self.settings, dict):
            raise InvalidProductDefinition("settings must be an object")
        if self.precedence_type not in {"finish_start", "start_start", "finish_finish"}:
            raise InvalidProductDefinition("invalid precedence_type")
        if len(set(self.predecessor_operation_ids)) != len(self.predecessor_operation_ids):
            raise InvalidProductDefinition("predecessors cannot be repeated")
        if len(set(self.successor_operation_ids)) != len(self.successor_operation_ids):
            raise InvalidProductDefinition("successors cannot be repeated")


@dataclass(frozen=True)
class LaborRequirement:
    skill_id: UUID
    min_people: int
    max_people: int
    work_minutes: int
    productivity_curve: dict[str, Any] = field(default_factory=dict)
    is_mandatory: bool = True

    def validate(self) -> None:
        if self.min_people < 1 or self.max_people < self.min_people:
            raise InvalidProductDefinition("invalid labor team limits")
        if self.work_minutes < 0:
            raise InvalidProductDefinition("work_minutes cannot be negative")


@dataclass(frozen=True)
class PhysicalRequirement:
    quantity: float
    capacity_units: float
    usage_mode: str
    physical_resource_type_id: UUID | None = None
    physical_resource_group_id: UUID | None = None
    work_center_id: UUID | None = None
    is_mandatory: bool = True

    def validate(self) -> None:
        if self.quantity <= 0 or self.capacity_units <= 0:
            raise InvalidProductDefinition("physical requirement values must be positive")
        if self.usage_mode not in {"active_use", "occupation"}:
            raise InvalidProductDefinition("invalid physical usage_mode")
        if not any((self.physical_resource_type_id, self.physical_resource_group_id, self.work_center_id)):
            raise InvalidProductDefinition("physical requirement needs a selector")


@dataclass(frozen=True)
class OperationGate:
    timing: str
    gate_type: str
    material_requirement_id: UUID | None = None
    drawing_package_id: UUID | None = None
    hardware_project_lot_id: UUID | None = None
    milestone_definition_id: UUID | None = None
    available_at: datetime | None = None
    config: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if self.timing not in {"before_start", "before_finish"}:
            raise InvalidProductDefinition("invalid gate timing")
        _required(self.gate_type, "gate_type")
        targets = (self.material_requirement_id, self.drawing_package_id,
                   self.hardware_project_lot_id, self.milestone_definition_id,
                   self.available_at)
        if sum(value is not None for value in targets) != 1:
            raise InvalidProductDefinition("gate requires exactly one target")
        _aware(self.available_at, "gate.available_at")


@dataclass(frozen=True)
class CreateRequiredOperationPhase:
    organization_id: UUID
    required_operation_id: UUID
    sequence_no: int
    code: str
    name: str
    estimate_kind: str
    original_estimate_minutes: int
    split_policy: str
    actor_id: UUID
    command_id: UUID
    route_step_phase_template_id: UUID | None = None
    status: str = "draft"
    earliest_start_at: datetime | None = None
    labor_requirements: tuple[LaborRequirement, ...] = ()
    physical_requirements: tuple[PhysicalRequirement, ...] = ()
    gates: tuple[OperationGate, ...] = ()
    source_system: str = "backend"

    def validate(self) -> None:
        _required(self.code, "code")
        _required(self.name, "name")
        if self.sequence_no <= 0 or self.original_estimate_minutes < 0:
            raise InvalidProductDefinition("invalid phase sequence or estimate")
        if self.split_policy not in {"non_splittable", "splittable", "continuous"}:
            raise InvalidProductDefinition("invalid split_policy")
        _aware(self.earliest_start_at, "earliest_start_at")
        for item in (*self.labor_requirements, *self.physical_requirements, *self.gates):
            item.validate()


@dataclass(frozen=True)
class CreateProductDefinitionRevision:
    organization_id: UUID
    plant_id: UUID
    actor_id: UUID
    command_id: UUID
    reason: str
    source_system: str = "backend"

    def validate(self) -> None:
        _required(self.reason, "reason")


@dataclass(frozen=True)
class DefinitionMutationResult:
    entity_id: UUID
    planning_state_revision_id: UUID | None = None
    planning_state_revision_no: int | None = None
    idempotent_replay: bool = False


@dataclass(frozen=True)
class ProductDefinitionRevisionResult:
    revision_id: UUID
    revision_no: int
    snapshot_sha256: str
    planning_state_revision_id: UUID | None
    planning_state_revision_no: int | None
    semantic_duplicate: bool = False
    idempotent_replay: bool = False
