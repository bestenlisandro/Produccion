from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from production_besten.domain.errors import InvalidSchedulingInput, ScenarioExpired
from production_besten.domain.scenario_expiry import (
    PlannedOperationTiming, ensure_scenario_not_expired, scenario_expired,
)

NOW = datetime(2026, 10, 28, 14, 55, 28, tzinfo=ZoneInfo("America/Argentina/Cordoba"))


@pytest.mark.parametrize("start,end,expired", [
    (-120, -60, True), (-60, 0, True), (-20, 20, True),
    (0, 20, False), (20, 40, False), (None, None, False),
])
def test_unstarted_work_expiry_uses_aware_operation_times(start, end, expired):
    timing = PlannedOperationTiming(
        NOW + timedelta(minutes=start) if start is not None else None,
        NOW + timedelta(minutes=end) if end is not None else None, False,
    )
    assert scenario_expired([timing], NOW.astimezone(timezone.utc)) is expired
    if expired:
        with pytest.raises(ScenarioExpired, match="Generá una nueva simulación"):
            ensure_scenario_not_expired([timing], NOW)


def test_actual_started_work_does_not_expire_due_to_its_planned_past():
    assert not scenario_expired([PlannedOperationTiming(NOW-timedelta(hours=2), NOW, True)], NOW)


def test_unstarted_operation_still_expires_when_another_has_execution():
    assert scenario_expired([
        PlannedOperationTiming(NOW-timedelta(hours=2), NOW, True),
        PlannedOperationTiming(NOW-timedelta(minutes=1), NOW+timedelta(hours=1), False),
    ], NOW)


def test_naive_clock_and_naive_planned_dates_are_rejected():
    with pytest.raises(InvalidSchedulingInput):
        scenario_expired([], NOW.replace(tzinfo=None))
    with pytest.raises(InvalidSchedulingInput):
        scenario_expired([PlannedOperationTiming(NOW.replace(tzinfo=None), NOW, False)], NOW)
