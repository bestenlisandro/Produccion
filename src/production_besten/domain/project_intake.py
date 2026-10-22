from dataclasses import dataclass
from typing import Any
from uuid import UUID
from production_besten.domain.errors import ProductDefinitionConflict


class ProjectIntakeVersionConflict(ProductDefinitionConflict):
    """The editor's optimistic version is stale."""


@dataclass(frozen=True)
class ProjectIntakeCommand:
    organization_id: UUID
    plant_id: UUID
    actor_id: UUID
    command_id: UUID
    action: str
    payload: dict[str, Any]
    project_id: UUID | None = None
    expected_row_version: int | None = None
