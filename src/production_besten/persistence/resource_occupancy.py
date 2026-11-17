"""Read model for resource occupancy in the published plan."""

from collections import defaultdict
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import text

from production_besten.domain.errors import EntityNotFound
from production_besten.domain.scheduling.models import TimeWindow
from production_besten.domain.scheduling.occupancy import resource_days
from production_besten.persistence.capacity_queries import load_calendars, load_overtime


def read_resource_occupancy(engine, org, plant, now):
    with engine.connect() as conn:
        conn.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        params = {"org": org, "plant": plant}
        plan = conn.execute(text("""
            SELECT p.name AS plant_name,p.timezone,p.base_calendar_id,v.id AS plan_version_id,
                   v.version_no AS plan_version_number,v.schedule_solution_id,v.source_scenario_id
            FROM core.plants p
            LEFT JOIN planning.plan_versions v ON v.organization_id=p.organization_id
                AND v.plant_id=p.id AND v.id=p.current_plan_version_id AND v.status='published'
            WHERE p.organization_id=:org AND p.id=:plant
        """), params).mappings().one_or_none()
        if plan is None:
            raise EntityNotFound("plant not found")

        zone = ZoneInfo(plan["timezone"])
        today = now.astimezone(zone).date()
        dates = [today + timedelta(days=offset) for offset in range(31)]
        boundaries = [datetime.combine(day, time.min, zone).astimezone(timezone.utc) for day in dates]
        result = {
            "plant_name": plan["plant_name"], "timezone": plan["timezone"],
            "plan_version_number": plan["plan_version_number"], "dates": dates[:-1], "resources": [],
        }
        if plan["plan_version_id"] is None:
            return result
        days = [(day, TimeWindow(start, end)) for day, start, end in
                zip(dates, boundaries, boundaries[1:])]
        params.update(start=boundaries[0], finish=boundaries[-1],
                      solution=plan["schedule_solution_id"], plan=plan["plan_version_id"])
        resources = conn.execute(text("""
            SELECT e.id,e.display_name AS name,'people' AS group_key,'Personas' AS group_name,
                   e.base_calendar_id AS calendar_id,NULL::uuid AS center_id,
                   NULL::uuid AS center_calendar_id
            FROM capacity.employees e
            WHERE e.organization_id=:org AND e.plant_id=:plant AND e.status='active'
            UNION ALL
            SELECT r.id,r.name,t.id::text,t.name,r.base_calendar_id,r.work_center_id,
                   COALESCE(w.base_calendar_id,:base_calendar)
            FROM capacity.physical_resources r
            JOIN capacity.physical_resource_types t
                ON t.organization_id=r.organization_id AND t.id=r.resource_type_id
            JOIN capacity.work_centers w ON w.organization_id=r.organization_id AND w.id=r.work_center_id
            WHERE r.organization_id=:org AND r.plant_id=:plant AND r.status='active'
                  AND t.status='active' AND w.status='active'
            ORDER BY group_name,group_key,name,id
        """), {**params, "base_calendar": plan["base_calendar_id"]}).mappings().all()
        calendar_ids = {plan["base_calendar_id"]}
        for resource in resources:
            calendar_ids.update((resource["calendar_id"], resource["center_calendar_id"]))
        calendars = load_calendars(conn, org, calendar_ids - {None})
        overtime = load_overtime(conn, org, plant, boundaries[0], boundaries[-1], plan["source_scenario_id"])
        blocks = _read_blocks(conn, params)
        bookings = _read_bookings(conn, params)
        result["resources"] = [
            {
                **{key: resource[key] for key in ("id", "name", "group_key", "group_name")},
                "days": resource_days(
                    resource, days, calendars, plan["base_calendar_id"], overtime,
                    blocks[resource["id"]], bookings[resource["id"]],
                ),
            }
            for resource in sorted(resources, key=lambda row: row["group_key"] != "people")
        ]
        return result


def _read_blocks(conn, params):
    rows = conn.execute(text("""
        SELECT COALESCE(u.employee_id,u.physical_resource_id) AS owner,
               lower(u.time_range) AS start_at,upper(u.time_range) AS end_at
        FROM capacity.resource_unavailabilities u
        WHERE u.organization_id=:org AND u.time_range && tstzrange(:start,:finish,'[)')
          AND NOT EXISTS (SELECT 1 FROM capacity.resource_unavailabilities next
                          WHERE next.organization_id=u.organization_id AND next.supersedes_id=u.id)
        UNION ALL
        SELECT COALESCE(l.employee_id,l.physical_resource_id),
               lower(l.valid_during),upper(l.valid_during)
        FROM planning.planning_locks l
        WHERE l.organization_id=:org AND l.plant_id=:plant AND l.released_at IS NULL
          AND (l.employee_id IS NOT NULL OR l.physical_resource_id IS NOT NULL)
          AND l.assignment_segment_id IS NULL AND l.required_operation_id IS NULL
          AND l.required_operation_phase_id IS NULL AND l.source_execution_id IS NULL
          AND (l.plan_version_id IS NULL OR l.plan_version_id=:plan)
          AND (l.valid_during IS NULL OR l.valid_during && tstzrange(:start,:finish,'[)'))
    """), params).mappings()
    blocks = defaultdict(list)
    for row in rows:
        blocks[row["owner"]].append(TimeWindow(row["start_at"] or params["start"],
                                               row["end_at"] or params["finish"]))
    return blocks


def _read_bookings(conn, params):
    rows = conn.execute(text("""
        WITH holds AS (
            SELECT h.id,h.physical_resource_id AS owner,h.required_operation_phase_id AS phase_id,
                   lower(h.time_range) AS start_at,
                   CASE WHEN h.source_kind='actual' THEN COALESCE(h.actual_released_at,upper(h.time_range))
                        ELSE COALESCE(upper(h.time_range),h.planned_release_at) END AS end_at,
                   p.id AS project_id,p.code AS project_code,p.name AS project_name,
                   o.name AS operation_name,
                   CASE WHEN h.source_kind='actual' THEN 'actual_hold' ELSE 'hold' END AS kind
            FROM planning.physical_occupations h
            JOIN production.required_operation_phases f
                ON f.organization_id=h.organization_id AND f.id=h.required_operation_phase_id
            JOIN production.required_operations o
                ON o.organization_id=f.organization_id AND o.id=f.required_operation_id
            JOIN core.projects p ON p.organization_id=o.organization_id AND p.id=o.project_id
            WHERE h.organization_id=:org AND p.plant_id=:plant AND h.is_effective
              AND h.time_range && tstzrange(:start,:finish,'[)')
              AND (h.schedule_solution_id=:solution OR h.source_kind='actual')
        ), segments AS (
            SELECT a.id,a.employee_id AS owner,a.assignment_segment_id,a.time_range,'work' AS kind
            FROM planning.human_segment_assignments a
            WHERE a.organization_id=:org AND a.schedule_solution_id=:solution
              AND a.time_range && tstzrange(:start,:finish,'[)')
            UNION ALL
            SELECT a.id,a.physical_resource_id,a.assignment_segment_id,a.time_range,a.usage_mode
            FROM planning.physical_resource_reservations a
            WHERE a.organization_id=:org AND a.schedule_solution_id=:solution
              AND a.time_range && tstzrange(:start,:finish,'[)')
        )
        SELECT s.id,s.owner,f.id AS phase_id,lower(s.time_range) AS start_at,upper(s.time_range) AS end_at,
               p.id AS project_id,COALESCE(p.code,b.code) AS project_code,
               COALESCE(p.name,b.name) AS project_name,COALESCE(o.name,d.name) AS operation_name,
               'work' AS kind
        FROM segments s
        JOIN planning.assignment_segments a ON a.organization_id=:org AND a.id=s.assignment_segment_id
        JOIN planning.planned_phase_assignments pa
            ON pa.organization_id=a.organization_id AND pa.id=a.planned_phase_assignment_id
        LEFT JOIN planning.phase_plan_results pr
            ON pr.organization_id=pa.organization_id AND pr.id=pa.phase_plan_result_id
        LEFT JOIN production.required_operation_phases f
            ON f.organization_id=pr.organization_id AND f.id=pr.required_operation_phase_id
        LEFT JOIN production.required_operations o ON o.organization_id=f.organization_id AND o.id=f.required_operation_id
        LEFT JOIN core.projects p ON p.organization_id=o.organization_id AND p.id=o.project_id
        LEFT JOIN production.production_batch_versions bv
            ON bv.organization_id=pa.organization_id AND bv.id=pa.production_batch_version_id
        LEFT JOIN production.production_batches b ON b.organization_id=bv.organization_id AND b.id=bv.production_batch_id
        LEFT JOIN production.operation_definitions d
            ON d.organization_id=b.organization_id AND d.id=b.operation_definition_id
        WHERE COALESCE(p.plant_id,b.plant_id)=:plant
          AND NOT (s.kind='occupation' AND EXISTS (
              SELECT 1 FROM holds h WHERE h.owner=s.owner AND h.phase_id=f.id
                AND tstzrange(h.start_at,h.end_at,'[)') @> s.time_range))
        UNION ALL
        SELECT * FROM holds WHERE end_at IS NULL OR end_at > GREATEST(start_at,:start)
        ORDER BY start_at,id
    """), params).mappings()
    bookings = defaultdict(list)
    for row in rows:
        bookings[row["owner"]].append(row)
    return bookings
