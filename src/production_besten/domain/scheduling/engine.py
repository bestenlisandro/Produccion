from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from itertools import combinations, product
from math import ceil
from zoneinfo import ZoneInfo

from production_besten.domain.scheduling.models import (
    CalendarData, EmployeeData, PhaseData, PhaseOutcome, PlannedSegment,
    ProjectData, ResourceData, SchedulingInput, SchedulingOutput, TimeWindow,
)


class GreedyFiniteCapacityScheduler:
    version = "v1-greedy-4"

    def __init__(self) -> None:
        self._calendar_cache: dict[object, list[TimeWindow]] = {}
        self._factor_cache = {}

    def schedule(self, value: SchedulingInput) -> SchedulingOutput:
        self._calendar_cache = {}
        self._factor_cache = {}
        dependencies = self._dependencies(value)
        cycle = self._cycle(dependencies)
        if cycle:
            return SchedulingOutput("failed", False, (), "PRECEDENCE_CYCLE:" + "->".join(str(x) for x in cycle))

        projects = {project.id: project for project in value.projects}
        phases = {phase.id: phase for phase in value.phases}
        pending = set(phases)
        outcomes: dict[object, PhaseOutcome] = {}
        reservations: dict[object, list[TimeWindow]] = defaultdict(list)
        capacity_reservations: dict[object, list[tuple[TimeWindow, float]]] = defaultdict(list)

        while pending:
            eligible = [phase_id for phase_id in pending if dependencies[phase_id].keys() <= outcomes.keys()]
            if not eligible:  # Defensive; cycle was checked above.
                return SchedulingOutput("failed", False, tuple(outcomes.values()), "PRECEDENCE_CYCLE")
            eligible.sort(key=lambda phase_id: (
                0 if phases[phase_id].manual_intent_priority else 1,
                self._priority_key(projects[phases[phase_id].project_id], phases[phase_id]),
            ))
            phase_id = eligible[0]
            phase = phases[phase_id]
            ready_at, inherited = self._ready_time(value, phase, dependencies[phase_id], outcomes)
            if any(outcomes[dep].status != "planned" for dep in dependencies[phase_id]):
                outcome = PhaseOutcome(phase.id, "out_of_horizon", 0, phase.original_minutes, (),
                    ("PREDECESSOR_NOT_FINISHED", "OUT_OF_HORIZON"), ready_at)
            else:
                outcome = self.find_earliest_feasible_slot(
                    value, phase, ready_at, reservations, capacity_reservations, inherited
                )
            outcomes[phase_id] = outcome
            pending.remove(phase_id)
            for segment in outcome.segments:
                window = TimeWindow(segment.start, segment.end)
                for owner in segment.employee_ids:
                    reservations[owner].append(window)
                demands = dict(segment.resource_capacity_units)
                for center, demand in self._center_demands(value, tuple(
                        (owner, units) for owner, units in demands.items()
                        if owner not in segment.occupation_resource_ids)).items():
                    capacity_reservations[center].append((window, demand))
                for owner in segment.resource_ids:
                    resource = self._resource(value, owner)
                    if resource.scheduling_mode == "exclusive":
                        reservations[owner].append(window)
                    elif owner not in segment.occupation_resource_ids:
                        capacity_reservations[owner].append((window, demands[owner]))
            if outcome.segments:
                occupation = TimeWindow(outcome.segments[0].start, outcome.segments[-1].end)
                for center, demand in self._center_demands(value, tuple(
                        (owner, units) for owner, units in outcome.segments[0].resource_capacity_units
                        if owner in outcome.segments[0].occupation_resource_ids)).items():
                    capacity_reservations[center].append((occupation, demand))
                for owner in outcome.segments[0].occupation_resource_ids:
                    resource = self._resource(value, owner)
                    if resource.scheduling_mode == "exclusive":
                        reservations[owner].append(occupation)
                    else:
                        demand = dict(outcome.segments[0].resource_capacity_units)[owner]
                        capacity_reservations[owner].append((occupation, demand))
        ordered = tuple(outcomes[phase.id] for phase in value.phases)
        complete = all(outcome.status == "planned" for outcome in ordered)
        return SchedulingOutput("ready", complete, ordered)

    def find_earliest_feasible_slot(self, value: SchedulingInput, phase: PhaseData,
                                    earliest_start: datetime,
                                    reservations: dict[object, list[TimeWindow]],
                                    capacity_reservations: dict[object, list[tuple[TimeWindow, float]]],
                                    inherited_blockers: tuple[str, ...] = ()) -> PhaseOutcome:
        unknown = [gate.blocker for gate in phase.gates if gate.blocker]
        if unknown:
            return PhaseOutcome(phase.id, "blocked", 0, phase.original_minutes, (),
                                tuple(dict.fromkeys((*inherited_blockers, *unknown))), earliest_start)
        gate_dates = [gate.release_at for gate in phase.gates if gate.release_at]
        ready = max([earliest_start, *(gate_dates or [])])
        blockers = list(inherited_blockers)
        for gate in phase.gates:
            if gate.release_at and gate.release_at > earliest_start:
                blockers.append(_gate_blocker(gate.gate_type))

        if phase.original_minutes == 0:
            return PhaseOutcome(
                phase.id, "planned", 0, 0, (), tuple(dict.fromkeys(blockers)), ready
            )

        teams, team_error = self._teams(value, phase)
        if not teams:
            return PhaseOutcome(phase.id, "blocked", 0, phase.original_minutes, (),
                                tuple(dict.fromkeys((*blockers, team_error))), ready)
        resource_sets, resource_error = self._resource_sets(value, phase)
        if not resource_sets:
            return PhaseOutcome(phase.id, "blocked", 0, phase.original_minutes, (),
                                tuple(dict.fromkeys((*blockers, resource_error))), ready)

        best = None
        for employees in teams:
            duration = self._duration(phase, employees)
            for resources, occupations, resource_capacity in resource_sets:
                candidate = self._allocate(value, phase, ready, duration, employees, resources,
                                           occupations, resource_capacity, reservations,
                                           capacity_reservations)
                if candidate is None:
                    continue
                windows, complete = candidate
                allocated = sum(int((item.end - item.start).total_seconds() // 60) for item in windows)
                score = (not complete, -allocated if not complete else 0,
                         windows[-1].end, windows[0].start,
                         tuple(self._employee(value, x).code for x in employees),
                         tuple(self._resource(value, x).code for x in resources))
                if best is None or score < best[0]:
                    best = (score, windows, complete, employees, resources, occupations,
                            resource_capacity, duration)
        if best is None:
            reason = self._capacity_blocker(value, phase, ready, reservations)
            return PhaseOutcome(phase.id, "out_of_horizon", 0, phase.original_minutes, (),
                                tuple(dict.fromkeys((*blockers, reason, "OUT_OF_HORIZON"))), ready)
        _, windows, complete, employees, resources, occupations, resource_capacity, duration = best
        start = windows[0].start
        if start > ready:
            blockers.extend(self._delay_blockers(
                value, employees, resources, resource_capacity, ready, start,
                reservations, capacity_reservations,
            ))
        segment_values = []
        for window in windows:
            minutes = int((window.end - window.start).total_seconds() // 60)
            employee_overtime = tuple((owner, self._overtime_for(value, phase.project_id, owner, None, window)) for owner in employees)
            resource_overtime = tuple((owner, self._overtime_for(value, phase.project_id, owner,
                self._resource(value, owner).work_center_id, window)) for owner in resources)
            overtime_minutes = minutes if (
                not _contains(self._base_windows(value, value.plant_calendar_id), window)
                or any(authorization is not None for _, authorization in employee_overtime)
                or any(authorization is not None for _, authorization in resource_overtime)
            ) else 0
            segment_values.append(PlannedSegment(
                window.start, window.end, minutes, employees, resources, occupations,
                resource_capacity, overtime_minutes, employee_overtime, resource_overtime,
            ))
        segments = tuple(segment_values)
        planned_minutes = sum(segment.work_minutes for segment in segments)
        if not complete:
            blockers.append("OUT_OF_HORIZON")
        return PhaseOutcome(
            phase.id, "planned" if complete else "out_of_horizon", planned_minutes,
            max(0, phase.original_minutes - planned_minutes), segments,
            tuple(dict.fromkeys(blockers)), ready,
        )

    def _dependencies(self, value: SchedulingInput):
        by_operation: dict[object, list[PhaseData]] = defaultdict(list)
        for phase in value.phases:
            by_operation[phase.operation_id].append(phase)
        for phases in by_operation.values():
            phases.sort(key=lambda item: (item.sequence_no, item.code))
        deps: dict[object, dict[object, int]] = {phase.id: {} for phase in value.phases}
        for phases in by_operation.values():
            for previous, current in zip(phases, phases[1:]):
                deps[current.id][previous.id] = 0
        for edge in value.precedences:
            predecessor = by_operation.get(edge.predecessor_operation_id, [])
            successor = by_operation.get(edge.successor_operation_id, [])
            if predecessor and successor:
                # finish_finish is conservatively treated as finish_start in 5.1.
                deps[successor[0].id][predecessor[-1].id] = edge.lag_minutes
        return deps

    def _cycle(self, deps):
        visiting, visited, path = set(), set(), []
        def visit(node):
            if node in visiting:
                return path[path.index(node):] + [node]
            if node in visited:
                return None
            visiting.add(node); path.append(node)
            for parent in deps[node]:
                found = visit(parent)
                if found:
                    return found
            path.pop(); visiting.remove(node); visited.add(node)
            return None
        for node in deps:
            found = visit(node)
            if found:
                return found
        return None

    def _ready_time(self, value, phase, deps, outcomes):
        ready = max(value.horizon_start, phase.earliest_start or value.horizon_start)
        blockers = []
        for dep, lag in deps.items():
            outcome = outcomes[dep]
            if outcome.segments:
                ready = max(ready, outcome.segments[-1].end + timedelta(minutes=lag))
                blockers.append("PREDECESSOR_NOT_FINISHED")
        return ready, tuple(blockers)

    def _priority_key(self, project: ProjectData, phase: PhaseData):
        priority = {"URGENT": 0, "HIGH": 1, "NORMAL": 2}.get(project.priority_code.upper(), 3 + project.priority_rank)
        commitment = project.committed_date or date.max
        return (priority, commitment, project.code, phase.lot_sequence, phase.lot_code or "",
                phase.operation_code, phase.sequence_no, phase.code)

    def _teams(self, value, phase):
        if not phase.labor:
            if phase.required_people == 0:
                return [()], ""  # Historical phases without human demand remain automatic.
            candidates = sorted(value.employees, key=lambda employee: employee.code)
            if len(candidates) < phase.required_people:
                return [], "REQUIRED_PEOPLE_UNAVAILABLE"
            return list(combinations((employee.id for employee in candidates), phase.required_people)), ""
        choices = []
        for need in phase.labor:
            candidates = [employee for employee in value.employees if need.skill_id in employee.skills]
            candidates.sort(key=lambda employee: employee.code)
            if len(candidates) < need.min_people:
                return [], "REQUIRED_SKILL_UNAVAILABLE"
            options = []
            for size in range(need.min_people, min(need.max_people, len(candidates)) + 1):
                options.extend(combinations((employee.id for employee in candidates), size))
            choices.append(options)
        teams = []
        for selected in product(*choices):
            flattened = tuple(item for group in selected for item in group)
            if len(set(flattened)) == len(flattened) and len(flattened) >= phase.required_people:
                teams.append(flattened)
        teams.sort(key=lambda ids: tuple(self._employee(value, x).code for x in ids))
        return teams, "REQUIRED_PEOPLE_UNAVAILABLE" if not teams and phase.required_people else ""

    def _resource_sets(self, value, phase):
        if not phase.physical:
            return [((), (), ())], ""
        choices = []
        for need in phase.physical:
            if need.usage_mode == "occupation" and phase.lot_id is None:
                return [], "PHYSICAL_OCCUPATION_REQUIRES_LOT"
            exclusive_candidates = []
            cumulative_candidates = []
            cumulative_match = False
            cumulative_demand = need.quantity * need.capacity_units
            for resource in value.resources:
                maximum = resource.capacity_units * max([1.0, *(factor for _, factor in self._capacity_factors(value, resource.calendar_id))])
                selected = ((need.resource_type_id is not None and resource.resource_type_id == need.resource_type_id)
                    or (need.resource_group_id is not None and need.resource_group_id in resource.group_ids)
                    or (need.work_center_id is not None and resource.work_center_id == need.work_center_id))
                if selected:
                    if (phase.requested_resource_id is not None
                            and resource.id != phase.requested_resource_id):
                        continue
                    if resource.scheduling_mode == "cumulative":
                        cumulative_match = True
                        if maximum >= cumulative_demand:
                            cumulative_candidates.append(resource)
                    elif resource.scheduling_mode == "exclusive" and resource.capacity_units >= need.capacity_units:
                        exclusive_candidates.append(resource)
            exclusive_candidates.sort(key=lambda resource: resource.code)
            cumulative_candidates.sort(key=lambda resource: resource.code)
            options = []
            if need.quantity == int(need.quantity):
                count = int(need.quantity)
                options.extend((
                    tuple(resource.id for resource in selected),
                    tuple(resource.id for resource in selected) if need.usage_mode == "occupation" else (),
                    tuple((resource.id, need.capacity_units) for resource in selected),
                    frozenset(resource.id for resource in selected),
                ) for selected in combinations(exclusive_candidates, count))
            options.extend((
                (resource.id,),
                (resource.id,) if need.usage_mode == "occupation" else (),
                ((resource.id, cumulative_demand),),
                frozenset(),
            ) for resource in cumulative_candidates)
            if not options:
                if phase.requested_resource_id is not None:
                    return [], "REQUESTED_RESOURCE_UNAVAILABLE_OR_INCOMPATIBLE"
                return [], ("CUMULATIVE_CAPACITY_EXHAUSTED" if cumulative_match
                            else "PHYSICAL_RESOURCE_UNAVAILABLE")
            choices.append(options)
        result = []
        for selected in product(*choices):
            flattened = tuple(item for group, _, _, _ in selected for item in group)
            exclusive = set().union(*(items for _, _, _, items in selected))
            if any(flattened.count(resource_id) > 1 for resource_id in exclusive):
                continue
            demands = defaultdict(float)
            for _, _, capacity, _ in selected:
                for resource_id, units in capacity:
                    demands[resource_id] += units
            if any(demands[resource.id] > resource.capacity_units * max([1.0, *(factor for _, factor in self._capacity_factors(value, resource.calendar_id))]) for resource in value.resources
                   if resource.id in demands):
                continue
            resources = tuple(sorted(set(flattened), key=lambda item: self._resource(value, item).code))
            occupations = tuple(sorted(
                {item for _, items, _, _ in selected for item in items},
                key=lambda item: self._resource(value, item).code,
            ))
            capacity = tuple((item, demands[item]) for item in resources)
            result.append((resources, occupations, capacity))
        result.sort(key=lambda pair: tuple(self._resource(value, x).code for x in pair[0]))
        return result, ""

    def _duration(self, phase, employees):
        if not phase.scalable_labor or len(phase.labor) != 1:
            return phase.original_minutes
        return ceil(phase.labor[0].work_minutes / max(1, len(employees)))

    def _center_demands(self, value, resource_capacity):
        demands = defaultdict(float)
        for owner, units in resource_capacity:
            center = self._resource(value, owner).work_center_id
            if center in value.work_centers:
                demands[center] += units
        return demands

    def _allocate(self, value, phase, ready, duration, employees, resources, occupations,
                  resource_capacity, reservations, capacity_reservations):
        if duration == 0:
            return None
        search = ready
        while search < value.horizon_end:
            owners = [(value.plant_calendar_id, None, None)]
            owners += [(self._employee(value, item).calendar_id, item, None) for item in employees]
            owners += [(self._resource(value, item).calendar_id, item, self._resource(value, item).work_center_id) for item in resources]
            windows = [TimeWindow(search, value.horizon_end)]
            for calendar_id, owner_id, center_id in owners:
                resource = (self._resource(value, owner_id)
                            if owner_id is not None and any(item.id == owner_id for item in value.resources)
                            else None)
                exclusive_busy = reservations.get(owner_id, []) if resource is None or resource.scheduling_mode == "exclusive" else []
                available = self._owner_windows(value, calendar_id, owner_id, center_id,
                                                phase.project_id, exclusive_busy)
                if resource is not None and resource.scheduling_mode == "cumulative":
                    demand = dict(resource_capacity)[owner_id]
                    available = self._capacity_windows(
                        value, resource, demand, available, capacity_reservations.get(owner_id, [])
                    )
                windows = _intersect(windows, available)
                if not windows:
                    break
            for center_id, demand in self._center_demands(value, resource_capacity).items():
                center = value.work_centers[center_id]
                available = self._owner_windows(value, center.calendar_id, center_id,
                                                center_id, phase.project_id, [])
                available = self._capacity_windows(value, center, demand, available,
                                                   capacity_reservations.get(center_id, []))
                windows = _intersect(windows, available)
            allocation, complete = _consume(windows, duration, phase.split_policy == "splittable")
            if not allocation:
                return None
            span = TimeWindow(allocation[0].start, allocation[-1].end)
            conflict_end = None
            # Occupation holds center capacity across non-working gaps as well.
            for center_id, demand in self._center_demands(value, tuple(
                    (owner, units) for owner, units in resource_capacity if owner in occupations)).items():
                center = value.work_centers[center_id]
                usage = capacity_reservations.get(center_id, [])
                if not _contains(self._capacity_windows(value, center, demand, [span], usage), span):
                    changes = [busy.end for busy, _ in usage if _overlaps(span, busy)]
                    changes.extend(item.window.end for item in value.actual_capacity_usage.get(center_id, ()) if _overlaps(span, item.window))
                    if changes:
                        conflict_end = min(changes)
                    else:
                        return None
            for owner in occupations:
                resource = self._resource(value, owner)
                if resource.scheduling_mode == "cumulative":
                    demand = dict(resource_capacity)[owner]
                    available = self._capacity_windows(
                        value, resource, demand, [span], capacity_reservations.get(owner, [])
                    )
                    if not _contains(available, span):
                        changes = [busy.end for busy, _ in capacity_reservations.get(owner, []) if _overlaps(span, busy)]
                        changes.extend(item.window.end for item in value.actual_capacity_usage.get(owner, ()) if _overlaps(span, item.window))
                        if changes:
                            next_change = min(changes)
                            conflict_end = max(conflict_end or next_change, next_change)
                busy = [*reservations.get(owner, []), *value.actual_occupations.get(owner, ())]
                for item in busy:
                    if _overlaps(span, item):
                        conflict_end = max(conflict_end or item.end, item.end)
            if conflict_end is None:
                return allocation, complete
            search = conflict_end
        return None

    def _owner_windows(self, value, calendar_id, owner_id, center_id, project_id, reservations):
        windows = list(self._base_windows(value, calendar_id))
        for overtime in value.overtime:
            if overtime.project_id not in (None, project_id):
                continue
            scoped = overtime.employee_id is not None or overtime.resource_id is not None or overtime.work_center_id is not None
            if owner_id is None or not scoped or overtime.employee_id == owner_id or overtime.resource_id == owner_id or overtime.work_center_id == center_id:
                authorized_end = overtime.end
                if overtime.max_minutes is not None:
                    authorized_end = min(authorized_end, overtime.start + timedelta(minutes=overtime.max_minutes))
                windows.append(TimeWindow(overtime.start, authorized_end))
        windows = _merge(windows)
        if owner_id is not None:
            windows = _subtract(windows, [*value.unavailability.get(owner_id, ()),
                                          *value.actual_occupations.get(owner_id, ()), *reservations])
        return windows

    def _capacity_windows(self, value, resource, demand, windows, planned_usage):
        """Return event-bounded windows where cumulative demand fits in full."""
        usage = [*planned_usage]
        usage.extend(
            (item.window, item.capacity_units)
            for item in value.actual_capacity_usage.get(resource.id, ())
        )
        result = []
        factors = self._capacity_factors(value, resource.calendar_id)
        for window in windows:
            boundaries = {window.start, window.end}
            for span, _ in factors:
                if _overlaps(window, span):
                    boundaries.update((max(window.start, span.start), min(window.end, span.end)))
            relevant = []
            for busy, units in usage:
                if _overlaps(window, busy):
                    clipped = TimeWindow(max(window.start, busy.start), min(window.end, busy.end))
                    relevant.append((clipped, units))
                    boundaries.update((clipped.start, clipped.end))
            ordered = sorted(boundaries)
            for start, end in zip(ordered, ordered[1:]):
                interval = TimeWindow(start, end)
                committed = sum(units for busy, units in relevant if _overlaps(interval, busy))
                factor = min((factor for span, factor in factors if _overlaps(interval, span)), default=1.0)
                if committed + demand <= resource.capacity_units * factor + 1e-9:
                    result.append(interval)
        return _merge(result)

    def _capacity_factors(self, value, calendar_id):
        key = (calendar_id, value.horizon_start, value.horizon_end)
        if key in self._factor_cache:
            return self._factor_cache[key]
        calendar = value.calendars[calendar_id]
        zone = ZoneInfo(calendar.timezone)
        current = value.horizon_start.astimezone(zone).date()
        finish = value.horizon_end.astimezone(zone).date()
        factors = []
        while current <= finish:
            day = []
            for item in calendar.intervals:
                if (item.weekday == current.isoweekday()
                        and (item.valid_from is None or current >= item.valid_from)
                        and (item.valid_to is None or current < item.valid_to)):
                    span = TimeWindow(datetime.combine(current, item.local_start, zone).astimezone(timezone.utc),
                                      datetime.combine(current, item.local_end, zone).astimezone(timezone.utc))
                    day.append((span, item.capacity_factor))
            for exception in calendar.exceptions:
                if exception.date != current:
                    continue
                if exception.effect == "replace":
                    day = []
                if exception.start is not None:
                    changed = TimeWindow(exception.start, exception.end)
                    if exception.effect in {"replace", "add"}:
                        # An explicit exception replaces the factor on its span.
                        day = [(part, factor) for span, factor in day for part in _subtract([span], [changed])]
                        day.append((changed, exception.capacity_factor or 1.0))
                elif exception.capacity_factor is not None:
                    day = [(span, exception.capacity_factor) for span, _ in day]
            factors.extend(day)
            current += timedelta(days=1)
        self._factor_cache[key] = factors
        return factors

    def _overtime_for(self, value, project_id, owner_id, center_id, window):
        regular_calendar = (self._employee(value, owner_id).calendar_id
                            if any(x.id == owner_id for x in value.employees)
                            else self._resource(value, owner_id).calendar_id)
        if _contains(self._base_windows(value, regular_calendar), window):
            return None
        for overtime in value.overtime:
            if overtime.project_id not in (None, project_id):
                continue
            authorized_end = overtime.end
            if overtime.max_minutes is not None:
                authorized_end = min(authorized_end, overtime.start + timedelta(minutes=overtime.max_minutes))
            if not (overtime.start <= window.start and window.end <= authorized_end):
                continue
            scoped = overtime.employee_id is not None or overtime.resource_id is not None or overtime.work_center_id is not None
            if not scoped or overtime.employee_id == owner_id or overtime.resource_id == owner_id or overtime.work_center_id == center_id:
                return overtime.id
        return None

    def _base_windows(self, value, calendar_id):
        key = (calendar_id, value.horizon_start, value.horizon_end)
        if key in self._calendar_cache:
            return self._calendar_cache[key]
        calendar = value.calendars[calendar_id]
        zone = ZoneInfo(calendar.timezone)
        start_date = value.horizon_start.astimezone(zone).date()
        end_date = value.horizon_end.astimezone(zone).date()
        windows = []
        current = start_date
        while current <= end_date:
            day = []
            for interval in calendar.intervals:
                if interval.weekday == current.isoweekday() and (interval.valid_from is None or current >= interval.valid_from) and (interval.valid_to is None or current < interval.valid_to):
                    begin = datetime.combine(current, interval.local_start, zone).astimezone(timezone.utc)
                    finish = datetime.combine(current, interval.local_end, zone).astimezone(timezone.utc)
                    day.append(TimeWindow(max(begin, value.horizon_start), min(finish, value.horizon_end)))
            exceptions = [item for item in calendar.exceptions if item.date == current]
            for exception in exceptions:
                changed = [] if exception.effect == "replace" else day
                if exception.effect == "remove":
                    removal = [TimeWindow(exception.start, exception.end)] if exception.start else list(day)
                    changed = _subtract(day, removal)
                elif exception.effect in {"add", "replace"} and exception.start:
                    changed = [*changed, TimeWindow(exception.start, exception.end)]
                day = changed
            windows.extend(item for item in day if item.start < item.end)
            current += timedelta(days=1)
        self._calendar_cache[key] = _merge(windows)
        return self._calendar_cache[key]

    def _capacity_blocker(self, value, phase, ready, reservations):
        if not self._base_windows(value, value.plant_calendar_id):
            return "OUTSIDE_WORKING_CALENDAR"
        if any(
            resource.scheduling_mode == "cumulative"
            and ((need.resource_type_id is not None and resource.resource_type_id == need.resource_type_id)
                 or (need.resource_group_id is not None and need.resource_group_id in resource.group_ids)
                 or (need.work_center_id is not None and need.work_center_id == resource.work_center_id))
            for need in phase.physical for resource in value.resources
        ):
            return "CUMULATIVE_CAPACITY_EXHAUSTED"
        if phase.physical:
            return "PHYSICAL_RESOURCE_OCCUPIED"
        if phase.labor or phase.required_people:
            return "PERSON_UNAVAILABLE"
        return "OUTSIDE_WORKING_CALENDAR"

    def _delay_blockers(self, value, employees, resources, resource_capacity, ready, start,
                        reservations, capacity_reservations):
        reasons = []
        span = TimeWindow(ready, start)
        for owner in employees:
            busy = [*reservations.get(owner, []), *value.unavailability.get(owner, ())]
            if any(_overlaps(span, item) for item in busy):
                reasons.extend(("PERSON_UNAVAILABLE", f"PERSON_UNAVAILABLE:{self._employee(value, owner).code}"))
        for owner in resources:
            resource = self._resource(value, owner)
            if resource.scheduling_mode == "cumulative":
                demand = dict(resource_capacity)[owner]
                usable = self._capacity_windows(
                    value, resource, demand, [span], capacity_reservations.get(owner, [])
                )
                if not _contains(usable, span):
                    reasons.extend((
                        "CUMULATIVE_CAPACITY_EXHAUSTED",
                        f"CUMULATIVE_CAPACITY_EXHAUSTED:{resource.code}:capacity={resource.capacity_units:g}:available_at={start.isoformat()}",
                    ))
            else:
                busy = [*reservations.get(owner, []), *value.unavailability.get(owner, ()),
                        *value.actual_occupations.get(owner, ())]
                if any(_overlaps(span, item) for item in busy):
                    reasons.extend(("PHYSICAL_RESOURCE_OCCUPIED",
                                    f"PHYSICAL_RESOURCE_OCCUPIED:{resource.code}"))
        if not reasons:
            reasons.append("OUTSIDE_WORKING_CALENDAR")
        return reasons

    @staticmethod
    def _employee(value, employee_id) -> EmployeeData:
        return next(item for item in value.employees if item.id == employee_id)

    @staticmethod
    def _resource(value, resource_id) -> ResourceData:
        return next(item for item in value.resources if item.id == resource_id)


def _gate_blocker(gate_type: str) -> str:
    value = gate_type.upper()
    if "MATERIAL" in value:
        return "MATERIAL_NOT_AVAILABLE"
    if "DRAW" in value or "PLANO" in value:
        return "DRAWINGS_NOT_AVAILABLE"
    if "HARDWARE" in value or "HERRAJE" in value:
        return "HARDWARE_NOT_AVAILABLE"
    return "GATE_NOT_AVAILABLE"


def _overlaps(a: TimeWindow, b: TimeWindow) -> bool:
    return a.start < b.end and b.start < a.end


def _merge(windows):
    values = sorted((item for item in windows if item.start < item.end), key=lambda item: (item.start, item.end))
    result = []
    for item in values:
        if result and item.start <= result[-1].end:
            result[-1] = TimeWindow(result[-1].start, max(result[-1].end, item.end))
        else:
            result.append(item)
    return result


def _intersect(left, right):
    result = []
    i = j = 0
    left, right = sorted(left, key=lambda x: x.start), sorted(right, key=lambda x: x.start)
    while i < len(left) and j < len(right):
        start, end = max(left[i].start, right[j].start), min(left[i].end, right[j].end)
        if start < end:
            result.append(TimeWindow(start, end))
        if left[i].end <= right[j].end:
            i += 1
        else:
            j += 1
    return result


def _subtract(windows, busy):
    result = list(windows)
    for block in sorted(busy, key=lambda x: x.start):
        changed = []
        for item in result:
            if not _overlaps(item, block):
                changed.append(item)
            else:
                if item.start < block.start:
                    changed.append(TimeWindow(item.start, min(item.end, block.start)))
                if block.end < item.end:
                    changed.append(TimeWindow(max(item.start, block.end), item.end))
        result = changed
    return _merge(result)


def _consume(windows, minutes, splittable):
    duration = timedelta(minutes=minutes)
    if not splittable:
        for item in windows:
            if item.end - item.start >= duration:
                return [TimeWindow(item.start, item.start + duration)], True
        return None, False
    result, remaining = [], duration
    for item in windows:
        available = item.end - item.start
        used = min(available, remaining)
        if used > timedelta(0):
            result.append(TimeWindow(item.start, item.start + used))
            remaining -= used
        if remaining == timedelta(0):
            return result, True
    return result, False


def _contains(windows, target):
    return any(item.start <= target.start and target.end <= item.end for item in windows)
