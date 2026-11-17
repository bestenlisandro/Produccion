from production_besten.domain.scheduling.engine import (
    _intersect, _merge, _subtract, calendar_windows, overtime_windows,
)
from production_besten.domain.scheduling.models import TimeWindow


def resource_days(resource, days, calendars, plant_calendar, overtime, blocks, bookings):
    calendar_ids = [plant_calendar, resource["calendar_id"]]
    if resource["center_id"] is not None:
        calendar_ids.append(resource["center_calendar_id"])
    configured = all(key in calendars for key in calendar_ids)
    horizon = TimeWindow(days[0][1].start, days[-1][1].end)
    base = {key: calendar_windows(calendars[key], horizon.start, horizon.end)
            for key in set(calendar_ids) if key in calendars}

    def shifts(project_id=None):
        if not configured:
            return []
        layers = [(plant_calendar, None, None),
                  (resource["calendar_id"], resource["id"], resource["center_id"])]
        if resource["center_id"] is not None:
            layers.append((resource["center_calendar_id"], resource["center_id"], resource["center_id"]))
        windows = [horizon]
        for calendar_id, owner_id, center_id in layers:
            extensions = overtime_windows(overtime, owner_id, center_id, project_id)
            windows = _intersect(windows, _merge([*base[calendar_id], *extensions]))
        return windows

    scheduled = _merge([
        *shifts(),
        *(window for project in {item.project_id for item in overtime if item.project_id is not None}
          for window in shifts(project)),
    ])
    available = _subtract(scheduled, blocks)
    project_availability = {
        project: _subtract(shifts(project), blocks)
        for project in {booking["project_id"] for booking in bookings}
    }
    booking_windows = [(item, TimeWindow(item["start_at"], item["end_at"] or horizon.end))
                       for item in bookings]
    result = []
    for date, day in days:
        day_available = _intersect([day], available)
        available_minutes = _minutes(day_available) if configured else None
        occupied = []
        detail = []
        visible = [(item, clipped[0]) for item, span in booking_windows
                   if (clipped := _intersect([day], [span]))]
        for index, (item, span) in enumerate(visible):
            inside = _intersect([span], project_availability[item["project_id"]])
            occupied.extend(inside)
            hold = item["kind"] != "work"
            # A continuous hold can intentionally cross an off-shift gap.
            expected = _intersect([span], scheduled) if hold else [span]
            alerts = []
            if configured and _subtract(expected, inside):
                alerts.append("outside_availability")
            if any(
                index != other_index and _intersect([span], [other_span])
                and not (hold and other["kind"] != "work" and item["phase_id"] == other["phase_id"])
                for other_index, (other, other_span) in enumerate(visible)
            ):
                alerts.append("overlap")
            detail.append({
                **{key: item[key] for key in ("id", "project_code", "project_name",
                                              "operation_name", "kind", "start_at", "end_at")},
                "minutes_in_day": _minutes([span]) if item["end_at"] is not None else None,
                "occupied_minutes": _minutes(inside) if configured else None,
                "alerts": alerts,
            })

        occupied_minutes = _minutes(_merge(occupied)) if configured else None
        if not configured:
            status = "missing_calendar"
        elif available_minutes:
            status = "available"
        elif _intersect([day], scheduled):
            status = "unavailable"
        else:
            status = "no_shift"
        result.append({
            "date": date, "status": status,
            "available_minutes": available_minutes, "occupied_minutes": occupied_minutes,
            "free_minutes": (max(0.0, available_minutes - occupied_minutes) if configured else None),
            "percent": (min(100.0, 100 * occupied_minutes / available_minutes)
                        if available_minutes else None),
            "bookings": detail,
        })
    return result


def _minutes(windows):
    return sum(((window.end - window.start).total_seconds() / 60 for window in windows), 0.0)
