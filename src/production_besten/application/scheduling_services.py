from production_besten.application.ports import UnitOfWorkFactory
from production_besten.domain.scheduling.models import GenerateSchedule, ScheduleGenerationResult


class GenerateScheduleService:
    def __init__(self, unit_of_work_factory: UnitOfWorkFactory) -> None:
        self._factory = unit_of_work_factory

    def execute(self, command: GenerateSchedule) -> ScheduleGenerationResult:
        command.validate()
        with self._factory() as unit_of_work:
            return unit_of_work.generate_schedule(command)
