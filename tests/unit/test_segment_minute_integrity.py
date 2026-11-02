from dataclasses import replace
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from production_besten.domain.scheduling.engine import GreedyFiniteCapacityScheduler
from production_besten.domain.scheduling.models import CalendarData, CalendarInterval
from tests.unit.test_cumulative_scheduler import _input, _phase


@pytest.mark.parametrize("minutes,hour,minute,expected", [
    (20, 15, 8, [20]),
    (120, 16, 28, [31, 89]),
    (180, 9, 28, [151, 29]),
])
def test_exact_total_carried_across_calendar_segments(minutes, hour, minute, expected):
    phase = replace(_phase("A", minutes, 1), estimate_kind="elapsed")
    value = _input([phase])
    zone = ZoneInfo("America/Argentina/Cordoba")
    start = datetime(2026, 10, 27, hour, minute, 45, 231477, tzinfo=zone)
    calendar = CalendarData(value.plant_calendar_id, str(zone), tuple(
        CalendarInterval(day, a, b, date(2026, 1, 1), date(2027, 1, 1))
        for day in range(1, 6) for a, b in [(time(8), time(12)), (time(12,45), time(17))]
    ), ())
    value = replace(value, horizon_start=start, horizon_end=start+timedelta(days=3),
                    calendars={calendar.id: calendar})
    result = GreedyFiniteCapacityScheduler().schedule(value)
    outcome = result.outcomes[0]
    assert result.complete and outcome.status == "planned"
    assert outcome.planned_work_minutes == minutes
    assert outcome.remaining_work_minutes == 0
    assert [segment.work_minutes for segment in outcome.segments] == expected
    assert sum((s.end-s.start for s in outcome.segments), timedelta()) == timedelta(minutes=minutes)
    assert outcome.segments[0].start == start
    if minutes == 120:
        assert outcome.segments[0].end == start.replace(hour=17, minute=0, second=0, microsecond=0)
        assert outcome.segments[1].start == (start+timedelta(days=1)).replace(hour=8, minute=0, second=0, microsecond=0)
    if minutes == 180:
        assert outcome.segments[0].end == start.replace(hour=12, minute=0, second=0, microsecond=0)
        assert outcome.segments[1].start == start.replace(hour=12, minute=45, second=0, microsecond=0)
