from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

from tests.integration.scheduling_helpers import generate, prepare_basic


@pytest.mark.parametrize("minutes,hour,minute,expected", [
    (20, 15, 8, [20]), (120, 16, 28, [31, 89]), (180, 9, 28, [151, 29]),
])
def test_persisted_totals_match_exact_segment_duration(engine, seeded_case, minutes, hour, minute, expected):
    case = seeded_case
    prepare_basic(engine, case, minutes=minutes)
    with engine.begin() as conn:
        conn.execute(text("UPDATE capacity.calendars SET timezone='America/Argentina/Cordoba' WHERE id=:id"), {"id": case.calendar_id})
        conn.execute(text("DELETE FROM capacity.calendar_working_intervals WHERE calendar_id=:id"), {"id": case.calendar_id})
        for day in range(1, 6):
            for a, b in [(time(8), time(12)), (time(12,45), time(17))]:
                conn.execute(text("""INSERT INTO capacity.calendar_working_intervals
                    (organization_id,calendar_id,weekday,local_start,local_end,valid_during)
                    VALUES (:org,:calendar,:day,:a,:b,daterange('2026-01-01','2027-01-01','[)'))"""),
                    {"org": case.organization_id, "calendar": case.calendar_id, "day": day, "a": a, "b": b})
    start = datetime(2026, 10, 27, hour, minute, 45, 231477, tzinfo=ZoneInfo("America/Argentina/Cordoba"))
    result = generate(engine, case, start=start)
    with engine.connect() as conn:
        phase = conn.execute(text("SELECT planned_work_minutes,remaining_work_minutes FROM planning.phase_plan_results WHERE schedule_solution_id=:id"), {"id": result.solution_id}).one()
        assignment = conn.scalar(text("SELECT work_minutes FROM planning.planned_phase_assignments WHERE schedule_solution_id=:id"), {"id": result.solution_id})
        segments = conn.execute(text("SELECT lower(time_range),upper(time_range),work_minutes FROM planning.assignment_segments WHERE schedule_solution_id=:id ORDER BY segment_no"), {"id": result.solution_id}).all()
        diagnostics = conn.scalar(text("SELECT diagnostics FROM planning.schedule_solutions WHERE id=:id"), {"id": result.solution_id})
    assert phase == (minutes, 0)
    assert assignment == minutes
    assert [s[2] for s in segments] == expected
    assert sum((s[1]-s[0] for s in segments), timedelta()) == timedelta(minutes=minutes)
    assert diagnostics['complete'] is True and result.complete
