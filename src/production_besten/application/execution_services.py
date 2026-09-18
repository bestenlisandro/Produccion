from production_besten.application.ports import UnitOfWorkFactory
from production_besten.domain.execution import (
    FinishOperation,
    FinishOperationResult,
    RegisterExecutionSegment,
    RegisterExecutionSegmentResult,
    StartOperation,
    StartOperationResult,
)


class StartOperationService:
    def __init__(self, unit_of_work_factory: UnitOfWorkFactory) -> None:
        self._factory = unit_of_work_factory

    def execute(self, command: StartOperation) -> StartOperationResult:
        command.validate()
        with self._factory() as unit_of_work:
            return unit_of_work.start_operation(command)


class RegisterExecutionSegmentService:
    def __init__(self, unit_of_work_factory: UnitOfWorkFactory) -> None:
        self._factory = unit_of_work_factory

    def execute(
        self, command: RegisterExecutionSegment
    ) -> RegisterExecutionSegmentResult:
        command.validate()
        with self._factory() as unit_of_work:
            return unit_of_work.register_execution_segment(command)


class FinishOperationService:
    def __init__(self, unit_of_work_factory: UnitOfWorkFactory) -> None:
        self._factory = unit_of_work_factory

    def execute(self, command: FinishOperation) -> FinishOperationResult:
        command.validate()
        with self._factory() as unit_of_work:
            return unit_of_work.finish_operation(command)
