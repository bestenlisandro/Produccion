from __future__ import annotations

from production_besten.api.schemas import UpdateRemainingEstimateRequest
from production_besten.domain.errors import InvalidEstimate
from production_besten.domain.remaining_estimate import (
    RemainingDimension,
    RemainingResourceInput,
    UpdateRemainingEstimate,
)


def remaining_command(body: UpdateRemainingEstimateRequest, context: dict, *, organization_id,
                      actor_id) -> UpdateRemainingEstimate:
    resources: list[RemainingResourceInput] = []
    for item in body.remaining:
        phase_id = item.phase_id or context["phase_id"]
        skill_id, minimum, maximum = item.skill_id, item.min_people, item.max_people
        requirement_id = item.physical_requirement_id
        if item.dimension == "LABOR_WORK" and (skill_id is None or minimum is None or maximum is None):
            labor = context["labor_requirements"]
            if len(labor) != 1:
                raise InvalidEstimate("labor skill/team must be specified when the phase does not have exactly one mandatory labor requirement")
            skill_id, minimum, maximum = labor[0]["skill_id"], labor[0]["min_people"], labor[0]["max_people"]
        if item.dimension == "ACTIVE_PHYSICAL_USE" and requirement_id is None:
            physical = [value for value in context["physical_requirements"] if value["usage_mode"] == "active_use"]
            if len(physical) != 1:
                raise InvalidEstimate("physical_requirement_id must be specified when active use is ambiguous")
            requirement_id = physical[0]["id"]
        resources.append(RemainingResourceInput(
            phase_id=phase_id,
            dimension=RemainingDimension(item.dimension),
            remaining_minutes=item.minutes,
            expected_release_at=item.expected_release_at,
            skill_id=skill_id,
            min_people=minimum,
            max_people=maximum,
            physical_requirement_id=requirement_id,
            physical_resource_id=item.physical_resource_id,
            capacity_units=item.capacity_units,
            details=item.details,
        ))
    remaining_labor = sum(value.remaining_minutes or 0 for value in resources
                          if value.dimension is RemainingDimension.LABOR_WORK)
    return UpdateRemainingEstimate(
        organization_id=organization_id,
        operation_execution_id=context["execution_id"],
        expected_revision_no=context["revision_no"],
        cutoff_at=body.cutoff_at,
        remaining_labor_minutes=remaining_labor,
        resources=tuple(resources),
        input_mode=body.input_mode,
        raw_input=body.model_dump(mode="json"),
        reason=body.reason,
        actor_id=actor_id,
        source_system="api",
    )
