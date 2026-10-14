from production_besten.application.ports import UnitOfWorkFactory
from production_besten.domain.replanning import (
    AcceptReplan,
    AcceptReplanResult,
    ManualScheduleResult,
    MoveScheduledActivity,
    RejectReplan,
    RejectReplanResult,
    ReplanRequest,
    ReplanResult,
    ResizeScheduledActivity,
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


class AcceptReplanService:
    def __init__(self, unit_of_work_factory: UnitOfWorkFactory) -> None:
        self._factory = unit_of_work_factory

    def execute(self, command: AcceptReplan) -> AcceptReplanResult:
        command.validate()
        with self._factory() as unit_of_work:
            return unit_of_work.accept_replan(command)


class MoveScheduledActivityService:
    def __init__(self, unit_of_work_factory: UnitOfWorkFactory) -> None:
        self._factory = unit_of_work_factory

    def execute(self, command: MoveScheduledActivity) -> ManualScheduleResult:
        command.validate()
        with self._factory() as unit_of_work:
            return unit_of_work.move_scheduled_activity(command)


class ResizeScheduledActivityService:
    def __init__(self, unit_of_work_factory: UnitOfWorkFactory) -> None:
        self._factory = unit_of_work_factory

    def execute(self, command: ResizeScheduledActivity) -> ManualScheduleResult:
        command.validate()
        with self._factory() as unit_of_work:
            return unit_of_work.resize_scheduled_activity(command)
