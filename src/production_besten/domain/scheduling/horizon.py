from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

from production_besten.domain.errors import InvalidSchedulingInput


def local_scheduling_horizon(start: date | datetime, end: date | datetime,
                             plant_timezone: str, now: datetime) -> tuple[datetime, datetime]:
    """Date-only values are plant-local days; end remains an exclusive boundary."""
    zone=ZoneInfo(plant_timezone)

    def instant(value):
        if isinstance(value,datetime):
            if value.tzinfo is None or value.utcoffset() is None:
                raise InvalidSchedulingInput('El horizonte debe indicar fecha local o un instante con zona horaria.')
            return value.astimezone(timezone.utc)
        return datetime.combine(value,time.min,zone).astimezone(timezone.utc)

    if now.tzinfo is None or now.utcoffset() is None:
        raise InvalidSchedulingInput('El reloj de planificación debe incluir zona horaria.')
    selected_start,finish=instant(start),instant(end)
    effective_start=max(selected_start,now.astimezone(timezone.utc))
    if finish<=effective_start:
        raise InvalidSchedulingInput('El fin del horizonte debe ser posterior al inicio efectivo y al instante actual.')
    return effective_start,finish
