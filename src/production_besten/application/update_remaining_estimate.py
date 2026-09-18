from production_besten.domain.remaining_estimate import (
    RemainingEstimateResult,
    UpdateRemainingEstimate,
)

from .ports import UnitOfWorkFactory


class UpdateRemainingEstimateService:
    def __init__(self, unit_of_work_factory: UnitOfWorkFactory) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    def execute(self, command: UpdateRemainingEstimate) -> RemainingEstimateResult:
        command.validate()
        with self._unit_of_work_factory() as unit_of_work:
            return unit_of_work.update_remaining_estimate(command)
