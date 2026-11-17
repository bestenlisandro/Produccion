"""Calendar and overtime data shared with the scheduling engine."""
from collections import defaultdict

from sqlalchemy import text

from production_besten.domain.scheduling.models import (
    CalendarData, CalendarException, CalendarInterval, OvertimeData,
)


def load_calendars(conn, org, calendar_ids):
    if not calendar_ids:
        return {}
    calendar_rows = conn.execute(text("SELECT id,timezone FROM capacity.calendars WHERE organization_id=:org AND id=ANY(:ids) AND status='active'"), {"org": org, "ids": list(calendar_ids)}).mappings().all()
    interval_rows = conn.execute(text("SELECT calendar_id,weekday,local_start,local_end,valid_during,capacity_factor FROM capacity.calendar_working_intervals WHERE organization_id=:org AND calendar_id=ANY(:ids) ORDER BY calendar_id,weekday,local_start"), {"org": org, "ids": list(calendar_ids)}).mappings().all()
    exception_rows = conn.execute(text("SELECT calendar_id,exception_date,effect,lower(time_range) AS start_at,upper(time_range) AS end_at,capacity_factor FROM capacity.calendar_exceptions WHERE organization_id=:org AND calendar_id=ANY(:ids) ORDER BY calendar_id,exception_date"), {"org": org, "ids": list(calendar_ids)}).mappings().all()
    intervals, exceptions = defaultdict(list), defaultdict(list)
    for row in interval_rows:
        range_value = row["valid_during"]
        intervals[row["calendar_id"]].append(CalendarInterval(row["weekday"], row["local_start"], row["local_end"], range_value.lower, range_value.upper, float(row["capacity_factor"])))
    for row in exception_rows:
        exceptions[row["calendar_id"]].append(CalendarException(row["exception_date"], row["effect"], row["start_at"], row["end_at"], float(row["capacity_factor"]) if row["capacity_factor"] is not None else None))
    calendars = {row["id"]: CalendarData(row["id"], row["timezone"], tuple(intervals[row["id"]]), tuple(exceptions[row["id"]])) for row in calendar_rows}
    return calendars


def load_overtime(conn, org, plant, start, end, scenario_id):
    overtime_rows = conn.execute(text("""
        SELECT id,lower(time_range) AS start_at,upper(time_range) AS end_at,project_id,employee_id,physical_resource_id,work_center_id,max_minutes
        FROM capacity.overtime_authorizations WHERE organization_id=:org AND plant_id=:plant AND revoked_at IS NULL
          AND time_range && tstzrange(:start,:finish,'[)') AND (scenario_id IS NULL OR scenario_id=:scenario)
        ORDER BY start_at,id
    """), {"org": org, "plant": plant, "start": start, "finish": end, "scenario": scenario_id}).mappings().all()
    overtime = tuple(OvertimeData(row["id"], row["start_at"], row["end_at"], row["project_id"], row["employee_id"], row["physical_resource_id"], row["work_center_id"], row["max_minutes"]) for row in overtime_rows)
    return overtime
