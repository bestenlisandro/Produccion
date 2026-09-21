from production_besten.application.ports import UnitOfWorkFactory
from production_besten.domain.replanning import (
    RejectReplan,
    RejectReplanResult,
    ReplanRequest,
    ReplanResult,
)


class ReplanService:
    def __init__(self, unit_of_work_factory: UnitOfWorkFactory) -> None:
        self._factory = unit_of_work_factory

    def execute(self, command: ReplanRequest) -> ReplanResult:
        command.validate()
        with self._factory() as unit_of_work:
            return unit_of_work.replan(command)


class RejectReplanService:
    def __init__(self, unit_of_work_factory: UnitOfWorkFactory) -> None:
        self._factory = unit_of_work_factory

    def execute(self, command: RejectReplan) -> RejectReplanResult:
        command.validate()
        with self._factory() as unit_of_work:
            return unit_of_work.reject_replan(command)
