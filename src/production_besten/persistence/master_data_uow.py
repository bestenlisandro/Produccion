from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, time, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4, uuid5
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import Engine, text

from production_besten.domain.errors import EntityNotFound, IdempotencyConflict
from production_besten.domain.master_data import (
    InvalidMasterData, MasterDataCommand, MasterDataConflict, MasterDataResult,
)


class PostgresMasterDataUnitOfWork:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.conn = None
        self.transaction = None

    def __enter__(self) -> "PostgresMasterDataUnitOfWork":
        self.conn = self.engine.connect()
        self.transaction = self.conn.begin()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        assert self.conn is not None and self.transaction is not None
        if exc_type is None:
            self.transaction.commit()
        else:
            self.transaction.rollback()
        self.conn.close()

    def snapshot(self, organization_id: UUID, plant_id: UUID) -> dict[str, Any]:
        plant = self._plant(organization_id, plant_id)
        local_day = datetime.now(ZoneInfo(plant["timezone"])).date()
        people = self.conn.execute(text("""
            SELECT e.id,e.code,e.display_name,e.status,e.plant_id,e.base_calendar_id,
                   c.name AS calendar_name,e.default_work_center_id,w.name AS work_center_name,
                   e.row_version,
                   (SELECT count(DISTINCT h.assignment_segment_id)
                      FROM planning.human_segment_assignments h
                     WHERE h.organization_id=e.organization_id AND h.employee_id=e.id
                       AND h.schedule_solution_id=(SELECT pv.schedule_solution_id
                         FROM core.plants cp JOIN planning.plan_versions pv
                           ON pv.organization_id=cp.organization_id AND pv.id=cp.current_plan_version_id
                        WHERE cp.organization_id=e.organization_id AND cp.id=e.plant_id)) AS current_usage_count,
                   COALESCE((SELECT jsonb_agg(jsonb_build_object('id',s.id,'code',s.code,'name',s.name)
                     ORDER BY s.name) FROM capacity.employee_skills es
                     JOIN capacity.skills s ON s.organization_id=es.organization_id AND s.id=es.skill_id
                    WHERE es.organization_id=e.organization_id AND es.employee_id=e.id AND es.enabled
                      AND es.valid_during @> CAST(:day AS date)), '[]'::jsonb) AS skills
              FROM capacity.employees e
              JOIN capacity.calendars c ON c.organization_id=e.organization_id AND c.id=e.base_calendar_id
              LEFT JOIN capacity.work_centers w ON w.organization_id=e.organization_id AND w.id=e.default_work_center_id
             WHERE e.organization_id=:org AND e.plant_id=:plant ORDER BY e.display_name,e.id
        """), {"org": organization_id, "plant": plant_id, "day": local_day}).mappings().all()
        skills = self.conn.execute(text("""
            SELECT s.id,s.code,s.name,s.description,s.category,s.status,s.row_version,
                   (SELECT count(*) FROM capacity.employee_skills es
                     JOIN capacity.employees e ON e.organization_id=es.organization_id AND e.id=es.employee_id
                    WHERE es.organization_id=s.organization_id AND es.skill_id=s.id AND es.enabled
                      AND es.valid_during @> CAST(:day AS date) AND e.plant_id=:plant) AS people_count
              FROM capacity.skills s WHERE s.organization_id=:org ORDER BY s.name,s.id
        """), {"org": organization_id, "plant": plant_id, "day": local_day}).mappings().all()
        centers = self.conn.execute(text("""
            SELECT w.id,w.code,w.name,w.capacity_mode,w.aggregate_capacity,w.capacity_unit,
                   w.base_calendar_id,c.name AS calendar_name,w.status,w.row_version,
                   (SELECT count(*) FROM capacity.physical_resources r WHERE r.organization_id=w.organization_id AND r.work_center_id=w.id) AS resource_count,
                   (SELECT count(DISTINCT rr.assignment_segment_id)
                      FROM planning.physical_resource_reservations rr
                      JOIN capacity.physical_resources pr ON pr.organization_id=rr.organization_id AND pr.id=rr.physical_resource_id
                     WHERE rr.organization_id=w.organization_id AND pr.work_center_id=w.id
                       AND rr.schedule_solution_id=(SELECT pv.schedule_solution_id
                         FROM core.plants cp JOIN planning.plan_versions pv
                           ON pv.organization_id=cp.organization_id AND pv.id=cp.current_plan_version_id
                        WHERE cp.organization_id=w.organization_id AND cp.id=w.plant_id)) AS current_usage_count
              FROM capacity.work_centers w LEFT JOIN capacity.calendars c
                ON c.organization_id=w.organization_id AND c.id=w.base_calendar_id
             WHERE w.organization_id=:org AND w.plant_id=:plant ORDER BY w.name,w.id
        """), {"org": organization_id, "plant": plant_id}).mappings().all()
        resource_types = self.conn.execute(text("""
            SELECT id,code,name,resource_kind,default_scheduling_mode,default_capacity_unit,status,row_version
              FROM capacity.physical_resource_types WHERE organization_id=:org ORDER BY name,id
        """), {"org": organization_id}).mappings().all()
        resources = self.conn.execute(text("""
            SELECT r.id,r.code,r.name,r.work_center_id,w.name AS work_center_name,
                   r.resource_type_id,t.name AS resource_type_name,r.scheduling_mode,
                   r.capacity_units,r.capacity_unit,r.status,r.is_mobile,r.base_calendar_id,
                   c.name AS calendar_name,r.row_version,
                   (SELECT count(DISTINCT rr.assignment_segment_id)
                      FROM planning.physical_resource_reservations rr
                     WHERE rr.organization_id=r.organization_id AND rr.physical_resource_id=r.id
                       AND rr.schedule_solution_id=(SELECT pv.schedule_solution_id
                         FROM core.plants cp JOIN planning.plan_versions pv
                           ON pv.organization_id=cp.organization_id AND pv.id=cp.current_plan_version_id
                        WHERE cp.organization_id=r.organization_id AND cp.id=r.plant_id)) AS current_usage_count
              FROM capacity.physical_resources r
              JOIN capacity.work_centers w ON w.organization_id=r.organization_id AND w.id=r.work_center_id
              JOIN capacity.physical_resource_types t ON t.organization_id=r.organization_id AND t.id=r.resource_type_id
              JOIN capacity.calendars c ON c.organization_id=r.organization_id AND c.id=r.base_calendar_id
             WHERE r.organization_id=:org AND r.plant_id=:plant ORDER BY r.name,r.id
        """), {"org": organization_id, "plant": plant_id}).mappings().all()
        calendars = self.conn.execute(text("""
            SELECT id,code,name,timezone,calendar_kind,description,status,row_version
              FROM capacity.calendars WHERE organization_id=:org ORDER BY name,id
        """), {"org": organization_id}).mappings().all()
        intervals = self.conn.execute(text("""
            SELECT id,calendar_id,weekday,local_start,local_end,shift_code,capacity_factor,
                   lower(valid_during) AS valid_from,upper(valid_during) AS valid_to,row_version
              FROM capacity.calendar_working_intervals
             WHERE organization_id=:org
             ORDER BY calendar_id,weekday,local_start,id
        """), {"org": organization_id}).mappings().all()
        exceptions = self.conn.execute(text("""
            SELECT id,calendar_id,exception_date,effect,lower(time_range) AS start_at,
                   upper(time_range) AS end_at,capacity_factor,reason,row_version
              FROM capacity.calendar_exceptions WHERE organization_id=:org
             ORDER BY exception_date,id
        """), {"org": organization_id}).mappings().all()
        usage_counts = self._usage_counts(organization_id, plant_id)
        for entity_type, records in (("person", people), ("skill", skills),
                                     ("work_center", centers), ("resource", resources),
                                     ("calendar", calendars)):
            records[:] = [dict(row, current_usage_count=usage_counts.get(
                (entity_type, row["id"]), 0)) for row in records]
        return {
            "people": _rows(people), "skills": _rows(skills), "work_centers": _rows(centers),
            "resource_types": _rows(resource_types), "resources": _rows(resources),
            "calendars": _rows(calendars), "calendar_windows": _rows(intervals),
            "calendar_exceptions": _rows(exceptions), "plant": _plain(plant),
            "stages": _rows(self.conn.execute(text("SELECT id,code,name,display_order,status,row_version FROM production.operation_definitions WHERE organization_id=:org ORDER BY display_order,code,id"), {"org":organization_id}).mappings().all()),
            "dev_only": True,
        }

    def execute(self, command: MasterDataCommand) -> MasterDataResult:
        self._plant(command.organization_id, command.plant_id)
        # Common order with planning: serialize state before changing capacity.
        self.conn.execute(text("SELECT id FROM core.plants WHERE organization_id=:org ORDER BY id FOR UPDATE"),
                          {"org": command.organization_id}).all()
        self.conn.execute(text("SELECT plant_id FROM planning.planning_state_heads "
                               "WHERE organization_id=:org ORDER BY plant_id FOR UPDATE"),
                          {"org": command.organization_id}).all()
        self.conn.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
                          {"key": str(command.command_id)})
        entity_id = (UUID(str(command.entity_id)) if command.entity_id is not None
                     else uuid5(command.command_id, command.entity_type))
        digest = _digest(command, entity_id)
        replay = self._replay(command, digest)
        if replay is not None:
            return replay
        before = None
        if command.action == "create":
            entity = self._create(command, entity_id)
        elif command.action == "assign_skill":
            before = self._skill_history(command, entity_id)
            entity = self._assign_skill(command, entity_id)
        elif command.action == "remove_skill":
            before = self._skill_history(command, entity_id)
            entity = self._remove_skill(command, entity_id)
        elif command.action == "define_windows":
            entity = self._define_windows(command, entity_id)
        else:
            before = self._entity(command.entity_type, command.organization_id, command.plant_id, entity_id, lock=True)
            entity = self._update(command, entity_id, before)
        usage_id = entity["calendar_id"] if command.entity_type == "calendar_exception" else entity_id
        usage = self._current_usage(command.organization_id, command.plant_id,
                                    command.entity_type, usage_id, command.payload.get("skill_id"))
        if command.entity_type == "calendar_exception" and before and before["calendar_id"] != entity["calendar_id"]:
            usage = max(usage, self._current_usage(command.organization_id, command.plant_id,
                                                 "calendar", before["calendar_id"]))
        affects = command.entity_type in {
            "person", "skill", "work_center", "resource", "calendar",
            "calendar_windows", "calendar_exception", "plant", "person_skill",
        }
        changed = self._operational_change(command, before, entity)
        if affects and changed:
            self._advance_planning_state(command, usage_id, before)
        result = MasterDataResult(_plain(entity), usage, changed and usage > 0, False)
        self._audit(command, entity_id, digest, before, result)
        return result

    # Mutation implementations are intentionally explicit: table and column names
    # never come from HTTP input.

    def _create(self, command: MasterDataCommand, entity_id: UUID):
        p, org, plant = command.payload, command.organization_id, command.plant_id
        if command.entity_type == "person":
            self._calendar(org, p["base_calendar_id"])
            if p.get("default_work_center_id"):
                self._center(org, plant, p["default_work_center_id"])
            return self.conn.execute(text("""
                INSERT INTO capacity.employees
                  (id,organization_id,plant_id,code,display_name,status,default_work_center_id,base_calendar_id)
                VALUES (:id,:org,:plant,:code,:name,'active',:center,:calendar) RETURNING *
            """), {"id": entity_id, "org": org, "plant": plant, "code": p["code"],
                    "name": p["display_name"], "center": p.get("default_work_center_id"),
                    "calendar": p["base_calendar_id"]}).mappings().one()
        if command.entity_type == "stage":
            return self.conn.execute(text("""
                INSERT INTO production.operation_definitions(id,organization_id,code,name,category,display_order)
                VALUES (:id,:org,:code,:name,'production_stage',:display_order) RETURNING *
            """), p|{"id":entity_id,"org":org}).mappings().one()
        if command.entity_type == "skill":
            return self.conn.execute(text("""
                INSERT INTO capacity.skills(id,organization_id,code,name,description,category)
                VALUES (:id,:org,:code,:name,:description,:category) RETURNING *
            """), {"id": entity_id, "org": org, "code": p["code"], "name": p["name"],
                    "description": p.get("description"), "category": p.get("category")}).mappings().one()
        if command.entity_type == "work_center":
            if p.get("base_calendar_id"):
                self._calendar(org, p["base_calendar_id"])
            return self.conn.execute(text("""
                INSERT INTO capacity.work_centers
                  (id,organization_id,plant_id,code,name,capacity_mode,aggregate_capacity,capacity_unit,base_calendar_id)
                VALUES (:id,:org,:plant,:code,:name,:mode,:capacity,:unit,:calendar) RETURNING *
            """), {"id": entity_id, "org": org, "plant": plant, "code": p["code"],
                    "name": p["name"], "mode": p["capacity_mode"],
                    "capacity": p.get("aggregate_capacity"), "unit": p.get("capacity_unit"),
                    "calendar": p.get("base_calendar_id")}).mappings().one()
        if command.entity_type == "resource":
            self._center(org, plant, p["work_center_id"])
            self._resource_type(org, p["resource_type_id"])
            self._calendar(org, p["base_calendar_id"])
            return self.conn.execute(text("""
                INSERT INTO capacity.physical_resources
                  (id,organization_id,plant_id,work_center_id,resource_type_id,code,name,
                   scheduling_mode,capacity_units,capacity_unit,is_mobile,base_calendar_id)
                VALUES (:id,:org,:plant,:center,:type,:code,:name,:mode,:units,:unit,:mobile,:calendar)
                RETURNING *
            """), {"id": entity_id, "org": org, "plant": plant, "center": p["work_center_id"],
                    "type": p["resource_type_id"], "code": p["code"], "name": p["name"],
                    "mode": p["scheduling_mode"], "units": p["capacity_units"],
                    "unit": p.get("capacity_unit"), "mobile": p.get("is_mobile", False),
                    "calendar": p["base_calendar_id"]}).mappings().one()
        if command.entity_type == "calendar":
            _zone(p["timezone"])
            return self.conn.execute(text("""
                INSERT INTO capacity.calendars
                  (id,organization_id,code,name,timezone,calendar_kind,description)
                VALUES (:id,:org,:code,:name,:timezone,:kind,:description) RETURNING *
            """), {"id": entity_id, "org": org, "code": p["code"], "name": p["name"],
                    "timezone": p["timezone"], "kind": p["calendar_kind"],
                    "description": p.get("description")}).mappings().one()
        if command.entity_type == "calendar_exception":
            calendar = self._calendar(org, p["calendar_id"])
            return self.conn.execute(text("""
                INSERT INTO capacity.calendar_exceptions
                  (id,organization_id,calendar_id,exception_date,time_range,effect,capacity_factor,reason)
                VALUES (:id,:org,:calendar,:day,
                  CASE WHEN :start_at IS NULL THEN NULL ELSE tstzrange(:start_at,:end_at,'[)') END,
                  :effect,:factor,:reason) RETURNING *
            """), {"id": entity_id, "org": org, "calendar": p["calendar_id"],
                    "day": p["exception_date"], **_exception_times(p, calendar["timezone"]),
                    "effect": p["effect"], "factor": p.get("capacity_factor"),
                    "reason": p.get("reason")}).mappings().one()
        raise InvalidMasterData(f"create is not supported for {command.entity_type}")

    def _update(self, command: MasterDataCommand, entity_id: UUID, before):
        p, org, plant = command.payload, command.organization_id, command.plant_id
        version = command.expected_row_version
        if version is None:
            raise InvalidMasterData("expected_row_version is required")
        if before["row_version"] != version:
            raise MasterDataConflict(
                f"expected row version {version}, current is {before['row_version']}"
            )
        if command.action == "set_status":
            if command.entity_type not in {"person", "skill", "work_center", "resource", "calendar", "stage"}:
                raise InvalidMasterData("this entity cannot be activated or deactivated")
            table = _table(command.entity_type)
            row = self.conn.execute(text(f"""
                UPDATE {table} SET status=:status,updated_at=now(),row_version=row_version+1
                 WHERE organization_id=:org AND id=:id AND row_version=:version RETURNING *
            """), {"status": p["status"], "org": org, "id": entity_id,
                    "version": version}).mappings().one_or_none()
            return self._updated(row)
        if command.entity_type == "person":
            self._calendar(org, p["base_calendar_id"])
            if p.get("default_work_center_id"):
                self._center(org, plant, p["default_work_center_id"])
            row = self.conn.execute(text("""
                UPDATE capacity.employees SET code=:code,display_name=:name,
                  default_work_center_id=:center,base_calendar_id=:calendar,
                  updated_at=now(),row_version=row_version+1
                 WHERE organization_id=:org AND plant_id=:plant AND id=:id AND row_version=:version
                 RETURNING *
            """), {"code": p["code"], "name": p["display_name"],
                    "center": p.get("default_work_center_id"), "calendar": p["base_calendar_id"],
                    "org": org, "plant": plant, "id": entity_id, "version": version}).mappings().one_or_none()
        elif command.entity_type == "stage":
            if p['code'] != before['code']:
                raise InvalidMasterData('El código de etapa es estable; creá otra etapa si necesitás otra clasificación.')
            row = self.conn.execute(text("""
                UPDATE production.operation_definitions SET name=:name,display_order=:display_order,
                    updated_at=now(),row_version=row_version+1
                WHERE organization_id=:org AND id=:id AND row_version=:version RETURNING *
            """), p|{"org":org,"id":entity_id,"version":version}).mappings().one_or_none()
        elif command.entity_type == "skill":
            row = self.conn.execute(text("""
                UPDATE capacity.skills SET code=:code,name=:name,description=:description,
                  category=:category,updated_at=now(),row_version=row_version+1
                 WHERE organization_id=:org AND id=:id AND row_version=:version RETURNING *
            """), {"code": p["code"], "name": p["name"], "description": p.get("description"),
                    "category": p.get("category"), "org": org, "id": entity_id,
                    "version": version}).mappings().one_or_none()
        elif command.entity_type == "work_center":
            if p.get("base_calendar_id"):
                self._calendar(org, p["base_calendar_id"])
            row = self.conn.execute(text("""
                UPDATE capacity.work_centers SET code=:code,name=:name,capacity_mode=:mode,
                  aggregate_capacity=:capacity,capacity_unit=:unit,base_calendar_id=:calendar,
                  updated_at=now(),row_version=row_version+1
                 WHERE organization_id=:org AND plant_id=:plant AND id=:id AND row_version=:version
                 RETURNING *
            """), {"code": p["code"], "name": p["name"], "mode": p["capacity_mode"],
                    "capacity": p.get("aggregate_capacity"), "unit": p.get("capacity_unit"),
                    "calendar": p.get("base_calendar_id"), "org": org, "plant": plant,
                    "id": entity_id, "version": version}).mappings().one_or_none()
        elif command.entity_type == "resource":
            self._center(org, plant, p["work_center_id"])
            self._resource_type(org, p["resource_type_id"])
            self._calendar(org, p["base_calendar_id"])
            row = self.conn.execute(text("""
                UPDATE capacity.physical_resources SET code=:code,name=:name,work_center_id=:center,
                  resource_type_id=:type,scheduling_mode=:mode,capacity_units=:units,
                  capacity_unit=:unit,is_mobile=:mobile,base_calendar_id=:calendar,
                  updated_at=now(),row_version=row_version+1
                 WHERE organization_id=:org AND plant_id=:plant AND id=:id AND row_version=:version
                 RETURNING *
            """), {"code": p["code"], "name": p["name"], "center": p["work_center_id"],
                    "type": p["resource_type_id"], "mode": p["scheduling_mode"],
                    "units": p["capacity_units"], "unit": p.get("capacity_unit"),
                    "mobile": p.get("is_mobile", False), "calendar": p["base_calendar_id"],
                    "org": org, "plant": plant, "id": entity_id, "version": version}).mappings().one_or_none()
        else:
            return self._update_calendar_or_plant(command, entity_id, before)
        return self._updated(row)

    def _update_calendar_or_plant(self, command, entity_id, before):
        p, org, version = command.payload, command.organization_id, command.expected_row_version
        if command.entity_type == "calendar":
            _zone(p["timezone"])
            row = self.conn.execute(text("""
                UPDATE capacity.calendars SET code=:code,name=:name,timezone=:timezone,
                  calendar_kind=:kind,description=:description,updated_at=now(),row_version=row_version+1
                 WHERE organization_id=:org AND id=:id AND row_version=:version RETURNING *
            """), {"code": p["code"], "name": p["name"], "timezone": p["timezone"],
                    "kind": p["calendar_kind"], "description": p.get("description"),
                    "org": org, "id": entity_id, "version": version}).mappings().one_or_none()
        elif command.entity_type == "calendar_exception":
            calendar = self._calendar(org, p["calendar_id"])
            row = self.conn.execute(text("""
                UPDATE capacity.calendar_exceptions SET calendar_id=:calendar,exception_date=:day,
                  time_range=CASE WHEN :start_at IS NULL THEN NULL ELSE tstzrange(:start_at,:end_at,'[)') END,
                  effect=:effect,capacity_factor=:factor,reason=:reason,
                  updated_at=now(),row_version=row_version+1
                 WHERE organization_id=:org AND id=:id AND row_version=:version RETURNING *
            """), {"calendar": p["calendar_id"], "day": p["exception_date"], **_exception_times(p, calendar["timezone"]),
                    "effect": p["effect"], "factor": p.get("capacity_factor"),
                    "reason": p.get("reason"), "org": org, "id": entity_id,
                    "version": version}).mappings().one_or_none()
        elif command.entity_type == "plant":
            self._calendar(org, p["base_calendar_id"])
            _zone(p["timezone"])
            row = self.conn.execute(text("""
                UPDATE core.plants SET code=:code,name=:name,timezone=:timezone,
                  base_calendar_id=:calendar,communication_threshold_business_days=:threshold,
                  updated_at=now(),row_version=row_version+1
                 WHERE organization_id=:org AND id=:id AND row_version=:version RETURNING *
            """), {"code": p["code"], "name": p["name"], "timezone": p["timezone"],
                    "calendar": p["base_calendar_id"],
                    "threshold": p["communication_threshold_business_days"],
                    "org": org, "id": entity_id, "version": version}).mappings().one_or_none()
        else:
            raise InvalidMasterData(f"update is not supported for {command.entity_type}")
        return self._updated(row)

    def _assign_skill(self, command: MasterDataCommand, entity_id: UUID):
        employee = self._entity("person", command.organization_id, command.plant_id, entity_id, lock=True)
        skill_id = UUID(str(command.payload["skill_id"]))
        skill = self._entity("skill", command.organization_id, command.plant_id, skill_id)
        if employee["status"] != "active" or skill["status"] != "active":
            raise InvalidMasterData("person and skill must be active")
        start = command.payload.get("valid_from") or self._local_day(command)
        end = command.payload.get("valid_to")
        if end is not None and start >= end:
            raise InvalidMasterData("skill validity end must be after start")
        existing = self.conn.execute(text("""
            SELECT * FROM capacity.employee_skills WHERE organization_id=:org
              AND employee_id=:employee AND skill_id=:skill AND enabled
              AND valid_during && daterange(:start,:finish,'[)') ORDER BY created_at,id FOR UPDATE
        """), {"org": command.organization_id, "employee": entity_id,
                "skill": skill_id, "start": start, "finish": end}).mappings().all()
        for previous in existing:
            interval = previous["valid_during"]
            has_left = interval.lower is None or interval.lower < start
            self.conn.execute(text("""
                UPDATE capacity.employee_skills SET
                  valid_during=CASE WHEN :left THEN daterange(lower(valid_during),:start,'[)') ELSE valid_during END,
                  enabled=:left WHERE organization_id=:org AND id=:id
            """), {"left": has_left, "start": start, "org": command.organization_id, "id": previous["id"]})
            if end is not None and (interval.upper is None or end < interval.upper):
                self.conn.execute(text("""
                    INSERT INTO capacity.employee_skills (id,organization_id,employee_id,skill_id,valid_during,level,enabled,approved_by)
                    VALUES (:id,:org,:employee,:skill,daterange(:start,:finish,'[)'),:level,true,:actor)
                """), {"id": uuid5(command.command_id, str(previous["id"])), "org": command.organization_id,
                        "employee": entity_id, "skill": skill_id, "start": end, "finish": interval.upper,
                        "level": previous["level"], "actor": previous["approved_by"]})
        return self.conn.execute(text("""
            INSERT INTO capacity.employee_skills
              (id,organization_id,employee_id,skill_id,valid_during,level,enabled,approved_by)
            VALUES (:id,:org,:employee,:skill,daterange(:start,:finish,'[)'),:level,true,:actor)
            RETURNING *
        """), {"id": uuid5(command.command_id, "assignment"),
                "org": command.organization_id, "employee": employee["id"],
                "skill": skill_id, "start": start, "finish": end,
                "level": command.payload.get("level"), "actor": command.actor_id}).mappings().one()

    def _remove_skill(self, command: MasterDataCommand, entity_id: UUID):
        self._entity("person", command.organization_id, command.plant_id, entity_id, lock=True)
        skill_id = UUID(str(command.payload["skill_id"]))
        row = self.conn.execute(text("""
            UPDATE capacity.employee_skills SET
              enabled=CASE WHEN lower_inf(valid_during) OR lower(valid_during)<:day THEN true ELSE false END,
              valid_during=CASE WHEN lower_inf(valid_during) OR lower(valid_during)<:day
                THEN daterange(lower(valid_during),:day,'[)') ELSE valid_during END
             WHERE organization_id=:org AND employee_id=:employee AND skill_id=:skill AND enabled
               AND (upper_inf(valid_during) OR upper(valid_during)>:day)
             RETURNING *
        """), {"org": command.organization_id, "employee": entity_id,
                "skill": skill_id, "day": self._local_day(command)}).mappings().all()
        if not row:
            raise EntityNotFound()
        return row[0]

    def _local_day(self, command):
        plant = self._plant(command.organization_id, command.plant_id)
        return datetime.now(ZoneInfo(plant["timezone"])).date()

    def _skill_history(self, command, entity_id):
        self._entity("person", command.organization_id, command.plant_id, entity_id, lock=True)
        rows = self.conn.execute(text("""
            SELECT * FROM capacity.employee_skills WHERE organization_id=:org AND employee_id=:employee
              AND skill_id=:skill ORDER BY created_at,id FOR UPDATE
        """), {"org": command.organization_id, "employee": entity_id,
                "skill": command.payload["skill_id"]}).mappings().all()
        return {"assignments": _rows(rows)}

    def _define_windows(self, command: MasterDataCommand, entity_id: UUID):
        calendar = self._calendar(command.organization_id, entity_id, lock=True)
        if command.expected_row_version is None or calendar["row_version"] != command.expected_row_version:
            raise MasterDataConflict("calendar changed concurrently")
        effective = command.payload.get("effective_from") or datetime.now(ZoneInfo(calendar["timezone"])).date()
        windows = command.payload["windows"]
        _validate_windows(windows)
        next_boundary = self.conn.scalar(text("""
            SELECT min(boundary) FROM (
              SELECT lower(valid_during) AS boundary FROM capacity.calendar_working_intervals
                WHERE organization_id=:org AND calendar_id=:calendar
              UNION ALL SELECT upper(valid_during) FROM capacity.calendar_working_intervals
                WHERE organization_id=:org AND calendar_id=:calendar
            ) edges WHERE boundary>:effective
        """), {"org": command.organization_id, "calendar": entity_id, "effective": effective})
        self.conn.execute(text("""
            DELETE FROM capacity.calendar_working_intervals
             WHERE organization_id=:org AND calendar_id=:calendar
               AND lower(valid_during)=:effective
        """), {"org": command.organization_id, "calendar": entity_id, "effective": effective})
        self.conn.execute(text("""
            UPDATE capacity.calendar_working_intervals
               SET valid_during=daterange(lower(valid_during),:effective,'[)'),
                   updated_at=now(),row_version=row_version+1
             WHERE organization_id=:org AND calendar_id=:calendar
               AND (lower_inf(valid_during) OR lower(valid_during)<:effective)
               AND (upper_inf(valid_during) OR upper(valid_during)>:effective)
        """), {"org": command.organization_id, "calendar": entity_id, "effective": effective})
        for index, window in enumerate(windows):
            self.conn.execute(text("""
                INSERT INTO capacity.calendar_working_intervals
                  (id,organization_id,calendar_id,weekday,local_start,local_end,
                   shift_code,capacity_factor,valid_during)
                VALUES (:id,:org,:calendar,:weekday,:start,:finish,:shift,:factor,
                        daterange(:effective,:until,'[)'))
            """), {"id": uuid5(command.command_id, f"window-{index}"),
                    "org": command.organization_id, "calendar": entity_id,
                    "weekday": window["weekday"], "start": window["local_start"],
                    "finish": window["local_end"], "shift": window.get("shift_code"),
                    "factor": window.get("capacity_factor", 1), "effective": effective, "until": next_boundary})
        return self.conn.execute(text("""
            UPDATE capacity.calendars SET updated_at=now(),row_version=row_version+1
             WHERE organization_id=:org AND id=:id AND row_version=:version RETURNING *
        """), {"org": command.organization_id, "id": entity_id,
                "version": command.expected_row_version}).mappings().one()

    @staticmethod
    def _updated(row):
        if row is None:
            raise MasterDataConflict("master record changed concurrently")
        return row

    def _replay(self, command: MasterDataCommand, digest: str) -> MasterDataResult | None:
        row = self.conn.execute(text("""
            SELECT action_code,entity_type,entity_id,actor_user_id,after_data,metadata
              FROM audit.audit_entries WHERE organization_id=:org AND request_id=:request
             ORDER BY created_at LIMIT 1
        """), {"org": command.organization_id,
                "request": command.command_id}).mappings().one_or_none()
        if row is None:
            return None
        metadata = row["metadata"]
        compatible = metadata.get("command_hash") == digest
        if not metadata.get("context_version"):
            # Legacy entries can replay only when their plant is provable from
            # the stored entity. Organization-wide entities lack that evidence.
            entity = row["after_data"].get("entity", {})
            compatible = (metadata.get("command_hash") == _digest(command, row["entity_id"], legacy=True)
                          and str(entity.get("plant_id", entity.get("id") if command.entity_type == "plant" else None)) == str(command.plant_id)
                          and row["actor_user_id"] == command.actor_id)
        if (row["action_code"] != command.action or row["entity_type"] != command.entity_type
                or not compatible):
            raise IdempotencyConflict("command_id was reused with different master-data input")
        data = row["after_data"]
        return MasterDataResult(data["entity"], data["current_usage_count"],
                                data["plan_requires_reconciliation"], True)

    def _audit(self, command, entity_id, digest, before, result) -> None:
        after = {"entity": _jsonable(result.entity),
                 "current_usage_count": result.current_usage_count,
                 "plan_requires_reconciliation": result.plan_requires_reconciliation}
        if command.entity_type == "person_skill":
            after["skill_history"] = self._skill_history(command, entity_id)
        self.conn.execute(text("""
            INSERT INTO audit.audit_entries
              (id,organization_id,actor_user_id,action_code,entity_type,entity_id,
               request_id,transaction_key,before_data,after_data,metadata)
            VALUES (:id,:org,:actor,:action,:type,:entity,:request,:request,
                    CAST(:before AS jsonb),CAST(:after AS jsonb),CAST(:metadata AS jsonb))
        """), {"id": uuid4(), "org": command.organization_id, "actor": command.actor_id,
                "action": command.action, "type": command.entity_type, "entity": entity_id,
                "request": command.command_id,
                "before": _dump(_plain(before)) if before else None,
                "after": _dump(after),
                "metadata": _dump({"command_hash": digest, "context_version": 2,
                                   "plant_id": str(command.plant_id), "dev_only": True})})

    def _entity(self, entity_type, org, plant, entity_id, lock=False):
        table = _table(entity_type)
        plant_clause = " AND plant_id=:plant" if entity_type in {"person", "work_center", "resource"} else ""
        row = self.conn.execute(text(
            f"SELECT * FROM {table} WHERE organization_id=:org AND id=:id{plant_clause}" +
            (" FOR UPDATE" if lock else "")
        ), {"org": org, "plant": plant, "id": entity_id}).mappings().one_or_none()
        if row is None:
            raise EntityNotFound()
        return row

    def _plant(self, org, plant):
        row = self.conn.execute(text(
            "SELECT * FROM core.plants WHERE organization_id=:org AND id=:plant"
        ), {"org": org, "plant": plant}).mappings().one_or_none()
        if row is None:
            raise EntityNotFound()
        return row

    def _calendar(self, org, calendar, lock=False):
        row = self.conn.execute(text(
            "SELECT * FROM capacity.calendars WHERE organization_id=:org AND id=:id" +
            (" FOR UPDATE" if lock else "")
        ), {"org": org, "id": calendar}).mappings().one_or_none()
        if row is None:
            raise EntityNotFound()
        return row

    def _center(self, org, plant, center):
        return self._entity("work_center", org, plant, center)

    def _resource_type(self, org, resource_type):
        row = self.conn.execute(text("""
            SELECT * FROM capacity.physical_resource_types
             WHERE organization_id=:org AND id=:id
        """), {"org": org, "id": resource_type}).mappings().one_or_none()
        if row is None:
            raise EntityNotFound()
        return row

    def _current_usage(self, org, plant, entity_type, entity_id, skill_id=None) -> int:
        kind = {"person_skill": "person", "calendar_windows": "calendar",
                "calendar_exception": "calendar"}.get(entity_type, entity_type)
        if entity_type == "person_skill" and skill_id is not None:
            kind = "person_skill:" + str(skill_id)
        return self._usage_counts(org, plant).get((kind, entity_id), 0)

    def _usage_counts(self, org, plant):
        """One query, distinct CURRENT operations, including base plant calendar.

        Count planned operations (not segments or unrelated master references).
        All joins retain organization scope, including shared calendars/skills.
        """
        rows = self.conn.execute(text("""
          WITH current AS (
            SELECT pv.schedule_solution_id,p.base_calendar_id FROM core.plants p
            JOIN planning.plan_versions pv ON pv.organization_id=p.organization_id
              AND pv.id=p.current_plan_version_id WHERE p.organization_id=:org AND p.id=:plant
          ), ops AS (
            SELECT opr.required_operation_id AS operation,ph.id AS phase,
                   ph.required_operation_id, ppa.id AS assignment
            FROM current c JOIN planning.operation_plan_results opr
              ON opr.schedule_solution_id=c.schedule_solution_id AND opr.organization_id=:org
            JOIN planning.phase_plan_results pr ON pr.organization_id=:org AND pr.operation_plan_result_id=opr.id
            JOIN production.required_operation_phases ph ON ph.organization_id=:org AND ph.id=pr.required_operation_phase_id
            LEFT JOIN planning.planned_phase_assignments ppa ON ppa.organization_id=:org AND ppa.phase_plan_result_id=pr.id
          ), humans AS (
            SELECT o.operation,h.employee_id,e.base_calendar_id FROM ops o
            JOIN planning.assignment_segments s ON s.organization_id=:org AND s.planned_phase_assignment_id=o.assignment
            JOIN planning.human_segment_assignments h ON h.organization_id=:org AND h.assignment_segment_id=s.id
            JOIN capacity.employees e ON e.organization_id=:org AND e.id=h.employee_id
          ), physical AS (
            SELECT o.operation,r.id,r.work_center_id,r.base_calendar_id,w.base_calendar_id AS center_calendar
            FROM ops o JOIN planning.assignment_segments s ON s.organization_id=:org AND s.planned_phase_assignment_id=o.assignment
            JOIN planning.physical_resource_reservations rr ON rr.organization_id=:org AND rr.assignment_segment_id=s.id
            JOIN capacity.physical_resources r ON r.organization_id=:org AND r.id=rr.physical_resource_id
            JOIN capacity.work_centers w ON w.organization_id=:org AND w.id=r.work_center_id
          ), refs AS (
            SELECT 'person' AS kind,employee_id AS id,operation FROM humans
            UNION ALL SELECT 'resource',id,operation FROM physical
            UNION ALL SELECT 'work_center',work_center_id,operation FROM physical
            UNION ALL SELECT 'skill',lr.skill_id,o.operation FROM ops o
              JOIN production.operation_labor_requirements lr ON lr.organization_id=:org AND lr.required_operation_phase_id=o.phase
            UNION ALL SELECT 'person_skill:' || lr.skill_id::text,h.employee_id,h.operation
              FROM humans h JOIN ops o ON o.operation=h.operation
              JOIN production.operation_labor_requirements lr ON lr.organization_id=:org AND lr.required_operation_phase_id=o.phase
            UNION ALL SELECT 'calendar',base_calendar_id,operation FROM humans
            UNION ALL SELECT 'calendar',base_calendar_id,operation FROM physical
            UNION ALL SELECT 'calendar',center_calendar,operation FROM physical WHERE center_calendar IS NOT NULL
            UNION ALL SELECT 'calendar',c.base_calendar_id,o.operation FROM current c CROSS JOIN ops o
            UNION ALL SELECT 'plant',CAST(:plant AS uuid),operation FROM ops
          ) SELECT kind,id,count(DISTINCT operation) AS uses FROM refs GROUP BY kind,id
        """), {"org": org, "plant": plant}).mappings().all()
        return {(r["kind"], r["id"]): int(r["uses"]) for r in rows}

    @staticmethod
    def _operational_change(command, before, entity):
        if before is None or command.entity_type in {"person_skill", "calendar_windows", "calendar_exception"}:
            return True
        descriptive = {"code", "name", "display_name", "description", "reason"}
        def equal(previous, value):
            if isinstance(previous, Decimal) and value is not None:
                return previous == Decimal(str(value))
            return _jsonable(previous) == _jsonable(value)
        return any(key not in descriptive and not equal(before.get(key), value)
                   for key, value in command.payload.items())

    def _advance_planning_state(self, command, usage_id, before):
        shared = command.entity_type in {"skill", "calendar", "calendar_windows", "calendar_exception"}
        heads = self.conn.execute(text("""
            SELECT plant_id,current_revision_no FROM planning.planning_state_heads
            WHERE organization_id=:org AND (:shared OR plant_id=:plant) ORDER BY plant_id FOR UPDATE
        """), {"org": command.organization_id, "plant": command.plant_id, "shared": shared}).mappings().all()
        for head in heads:
            revision = uuid5(command.command_id, str(head["plant_id"]))
            affected = self._current_usage(command.organization_id, head["plant_id"],
                command.entity_type, usage_id, command.payload.get("skill_id")) > 0
            if command.entity_type == "calendar_exception" and before:
                affected = affected or self._current_usage(command.organization_id, head["plant_id"],
                    "calendar", before["calendar_id"]) > 0
            summary = {"master_data": True, "entity_type": command.entity_type,
                       "entity_id": str(usage_id), "action": command.action,
                       "current_affected": affected}
            self.conn.execute(text("""
                INSERT INTO planning.planning_state_revisions
                  (id,organization_id,plant_id,revision_no,reason,transaction_key,change_summary,created_by)
                VALUES (:id,:org,:plant,:number,'MASTER_DATA_CHANGED',:key,CAST(:summary AS jsonb),:actor)
            """), {"id": revision, "org": command.organization_id, "plant": head["plant_id"],
                    "number": head["current_revision_no"] + 1, "key": revision,
                    "summary": _dump(summary), "actor": command.actor_id})
            self.conn.execute(text("""
                UPDATE planning.planning_state_heads SET current_revision_id=:id,
                  current_revision_no=current_revision_no+1,row_version=row_version+1,
                  updated_at=now(),updated_by=:actor WHERE organization_id=:org AND plant_id=:plant
            """), {"id": revision, "org": command.organization_id, "plant": head["plant_id"], "actor": command.actor_id})
            self.conn.execute(text("""
                UPDATE planning.scenarios SET status='stale',updated_at=now(),row_version=row_version+1
                WHERE organization_id=:org AND plant_id=:plant AND status IN ('draft','calculating','ready')
                  AND base_state_revision_id<>:revision
            """), {"org": command.organization_id, "plant": head["plant_id"], "revision": revision})


class PostgresMasterDataUnitOfWorkFactory:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def __call__(self) -> PostgresMasterDataUnitOfWork:
        return PostgresMasterDataUnitOfWork(self.engine)


def _table(entity_type: str) -> str:
    tables = {"person": "capacity.employees", "skill": "capacity.skills",
              "work_center": "capacity.work_centers", "resource": "capacity.physical_resources",
              "calendar": "capacity.calendars", "calendar_exception": "capacity.calendar_exceptions",
              "plant": "core.plants", "stage":"production.operation_definitions"}
    try:
        return tables[entity_type]
    except KeyError as exc:
        raise InvalidMasterData(f"unsupported entity type {entity_type}") from exc


def _plain(row) -> dict[str, Any]:
    return {key: _jsonable(value) for key, value in dict(row).items()} if row is not None else {}


def _rows(rows) -> list[dict[str, Any]]:
    return [_plain(row) for row in rows]


def _jsonable(value):
    if isinstance(value, (UUID, datetime, date, time, Decimal)):
        return str(value)
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _dump(value) -> str:
    return json.dumps(value, default=_jsonable, sort_keys=True)


def _digest(command: MasterDataCommand, entity_id: UUID, *, legacy=False) -> str:
    value = {"action": command.action, "entity_type": command.entity_type,
             "entity_id": str(entity_id), "payload": _jsonable(command.payload),
             "expected_row_version": command.expected_row_version}
    if not legacy:
        value.update(organization_id=str(command.organization_id),
                     plant_id=str(command.plant_id), actor_id=str(command.actor_id))
    return hashlib.sha256(_dump(value).encode()).hexdigest()


def _zone(value: str) -> ZoneInfo:
    try:
        return ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise InvalidMasterData("timezone must be a valid IANA name") from exc


def _exception_times(payload: dict, timezone_name: str) -> dict[str, datetime | None]:
    start, finish = payload.get("local_start"), payload.get("local_end")
    if start is None and finish is None:
        return {"start_at": None, "end_at": None}
    if start is None or finish is None or start >= finish:
        raise InvalidMasterData("exception local_start must be before local_end")
    zone = _zone(timezone_name)
    day = payload["exception_date"]
    result = {"start_at": datetime.combine(day, start, zone),
              "end_at": datetime.combine(day, finish, zone)}
    for instant in result.values():
        if instant.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None) != instant.replace(tzinfo=None):
            raise InvalidMasterData("exception local time does not exist in calendar timezone")
        if instant.replace(fold=0).utcoffset() != instant.replace(fold=1).utcoffset():
            raise InvalidMasterData("exception local time is ambiguous in calendar timezone")
    return result


def _validate_windows(windows: list[dict]) -> None:
    by_day: dict[int, list[tuple[time, time]]] = {}
    for window in windows:
        start, finish = window["local_start"], window["local_end"]
        weekday = window["weekday"]
        if not 1 <= weekday <= 7 or start >= finish:
            raise InvalidMasterData("calendar windows require weekday 1..7 and start before end")
        if Decimal(str(window.get("capacity_factor", 1))) <= 0:
            raise InvalidMasterData("capacity_factor must be positive")
        by_day.setdefault(weekday, []).append((start, finish))
    for values in by_day.values():
        ordered = sorted(values)
        if any(current[0] < previous[1] for previous, current in zip(ordered, ordered[1:])):
            raise InvalidMasterData("calendar windows cannot overlap")
