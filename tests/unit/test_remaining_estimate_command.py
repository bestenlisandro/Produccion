from datetime import datetime, timezone
from uuid import uuid4

import pytest

from production_besten.domain.errors import InvalidEstimate
from production_besten.domain.remaining_estimate import (
    RemainingDimension,
    RemainingResourceInput,
    UpdateRemainingEstimate,
)


def test_requires_explicit_resource_dimensions() -> None:
    command = UpdateRemainingEstimate(
        organization_id=uuid4(),
        operation_execution_id=uuid4(),
        expected_revision_no=1,
        cutoff_at=datetime.now(timezone.utc),
        remaining_labor_minutes=60,
        resources=(),
    )

    with pytest.raises(InvalidEstimate, match="resource dimension"):
        command.validate()


def test_dimensions_are_not_collapsed_into_generic_duration() -> None:
    phase_id, skill_id, requirement_id, resource_id = (uuid4() for _ in range(4))
    values = (
        RemainingResourceInput(
            phase_id=phase_id,
            dimension=RemainingDimension.LABOR_WORK,
            remaining_minutes=120,
            skill_id=skill_id,
            min_people=1,
            max_people=2,
        ),
        RemainingResourceInput(
            phase_id=phase_id,
            dimension=RemainingDimension.ACTIVE_PHYSICAL_USE,
            remaining_minutes=90,
            physical_requirement_id=requirement_id,
        ),
        RemainingResourceInput(
            phase_id=phase_id,
            dimension=RemainingDimension.PHYSICAL_OCCUPATION,
            remaining_minutes=600,
            physical_resource_id=resource_id,
        ),
    )
    command = UpdateRemainingEstimate(
        organization_id=uuid4(),
        operation_execution_id=uuid4(),
        expected_revision_no=1,
        cutoff_at=datetime.now(timezone.utc),
        remaining_labor_minutes=120,
        resources=values,
    )

    command.validate()
    assert {item.dimension for item in values} == set(RemainingDimension)
