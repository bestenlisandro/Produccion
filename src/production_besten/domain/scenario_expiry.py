from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from production_besten.domain.errors import InvalidSchedulingInput, ScenarioExpired


EXPIRY_MESSAGE = (
    "Esta simulación quedó desactualizada porque contiene operaciones planificadas "
    "en el pasado. Generá una nueva simulación antes de confirmar el plan."
)


@dataclass(frozen=True)
class PlannedOperationTiming:
    start: datetime | None
    end: datetime | None
    execution_started: bool


def scenario_expired(operations: Iterable[PlannedOperationTiming], now: datetime) -> bool:
    def aware(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise InvalidSchedulingInput("scenario expiry requires timezone-aware timestamps")
        return value

    aware(now)
    for operation in operations:
        if operation.execution_started:
            continue
        start = aware(operation.start) if operation.start is not None else None
        end = aware(operation.end) if operation.end is not None else None
        if (start is not None and start < now) or (end is not None and end <= now):
            return True
    return False


def ensure_scenario_not_expired(operations: Iterable[PlannedOperationTiming], now: datetime) -> None:
    if scenario_expired(operations, now):
        raise ScenarioExpired(EXPIRY_MESSAGE)
