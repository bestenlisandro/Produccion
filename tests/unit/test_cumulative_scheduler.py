from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from uuid import NAMESPACE_DNS, uuid5

from production_besten.domain.scheduling.engine import GreedyFiniteCapacityScheduler
from production_besten.domain.scheduling.models import (
    CalendarData, CalendarInterval, CapacityUsage, EmployeeData, LaborNeed,
    PhaseData, PhysicalNeed, ProjectData, ResourceData, SchedulingInput, TimeWindow,
)


START = datetime(2026, 9, 7, 8, tzinfo=timezone.utc)


def _id(value: str):
    return uuid5(NAMESPACE_DNS, f"production-besten-test:{value}")


def _phase(code, minutes, demand, *, labor=(), physical=(), split="splittable"):
    needs = physical or (PhysicalNeed(_id(f"need-{code}"), None, None, _id("center"), 1, demand, "active_use"),)
    return PhaseData(
        _id(f"phase-{code}"), _id(f"operation-{code}"), _id("project"), "PROJECT",
        _id("lot"), "LOT", 1, code, 1, f"{code}-PHASE", minutes, "labor", split,
        None, False, tuple(labor), tuple(needs), (),
    )


def _input(phases, *, capacity=3, employees=(), resources=None, actual=(), days=3):
    calendar = CalendarData(
        _id("calendar"), "UTC",
        tuple(CalendarInterval(day, time(8), time(16), date(2026, 1, 1), date(2027, 1, 1)) for day in range(1, 6)),
        (),
    )
    resources = resources or (
        ResourceData(_id("center-resource"), "CENTER-A", calendar.id, _id("center-type"),
                     _id("center"), frozenset(), "cumulative", capacity),
    )
    return SchedulingInput(
        _id("org"), _id("plant"), calendar.id, START, START + timedelta(days=days),
        _id("definition"), _id("state"), None,
        (ProjectData(_id("project"), "PROJECT", "NORMAL", 3, None),), tuple(phases), (),
        {calendar.id: calendar}, tuple(employees), tuple(resources), {}, {},
        {_id("center-resource"): tuple(actual)} if actual else {}, (),
    )


def _by_code(output, phases):
    code = {phase.id: phase.operation_code for phase in phases}
    return {code[item.phase_id]: item for item in output.outcomes}


def test_capacity_three_accepts_three_demands_of_one_at_once():
    phases = [_phase(code, 60, 1) for code in ("A", "B", "C")]
    result = _by_code(GreedyFiniteCapacityScheduler().schedule(_input(phases)), phases)
    assert {item.segments[0].start for item in result.values()} == {START}


def test_fourth_demand_waits_for_first_internal_release_event():
    phases = [_phase("A", 240, 2), _phase("B", 120, 1), _phase("C", 60, 1)]
    result = _by_code(GreedyFiniteCapacityScheduler().schedule(_input(phases)), phases)
    assert result["A"].segments[0].start == START
    assert result["B"].segments[0].start == START
    assert result["C"].segments[0].start == START + timedelta(hours=2)
    assert "CUMULATIVE_CAPACITY_EXHAUSTED" in result["C"].blockers


def test_two_plus_two_is_incompatible_on_capacity_three():
    phases = [_phase("A", 120, 2), _phase("B", 60, 2)]
    result = _by_code(GreedyFiniteCapacityScheduler().schedule(_input(phases)), phases)
    assert result["B"].segments[0].start == START + timedelta(hours=2)


def test_actual_cumulative_usage_releases_capacity_at_event_boundary():
    phase = _phase("A", 60, 1)
    actual = (CapacityUsage(TimeWindow(START, START + timedelta(hours=2)), 3),)
    outcome = GreedyFiniteCapacityScheduler().schedule(_input([phase], actual=actual)).outcomes[0]
    assert outcome.segments[0].start == START + timedelta(hours=2)


def test_cumulative_capacity_and_specific_exclusive_resource_are_both_required():
    cumulative = ResourceData(_id("center-resource"), "CENTER-A", _id("calendar"), _id("center-type"),
                              _id("center"), frozenset(), "cumulative", 3)
    saw = ResourceData(_id("saw"), "SAW-1", _id("calendar"), _id("saw-type"),
                       _id("saw-center"), frozenset(), "exclusive", 1)
    physical_a = (
        PhysicalNeed(_id("a-center"), None, None, _id("center"), 1, 1, "active_use"),
        PhysicalNeed(_id("a-saw"), _id("saw-type"), None, None, 1, 1, "active_use"),
    )
    physical_b = (
        PhysicalNeed(_id("b-center"), None, None, _id("center"), 1, 1, "active_use"),
        PhysicalNeed(_id("b-saw"), _id("saw-type"), None, None, 1, 1, "active_use"),
    )
    phases = [_phase("A", 120, 1, physical=physical_a), _phase("B", 60, 1, physical=physical_b)]
    result = _by_code(GreedyFiniteCapacityScheduler().schedule(_input(phases, resources=(cumulative, saw))), phases)
    assert result["B"].segments[0].start == START + timedelta(hours=2)
    assert "PHYSICAL_RESOURCE_OCCUPIED" in result["B"].blockers


def test_capacity_available_does_not_replace_two_qualified_people():
    skill = _id("skill")
    employee = EmployeeData(_id("employee"), "EMP-1", _id("calendar"), frozenset({skill}))
    phase = _phase("A", 60, 1, labor=(LaborNeed(skill, 2, 2, 60),))
    outcome = GreedyFiniteCapacityScheduler().schedule(_input([phase], employees=(employee,))).outcomes[0]
    assert outcome.status == "blocked"
    assert outcome.blockers == ("REQUIRED_SKILL_UNAVAILABLE",)


def test_splittable_work_uses_three_hours_then_five_next_workday():
    phases = [_phase("A", 300, 3), _phase("B", 480, 1)]
    result = _by_code(GreedyFiniteCapacityScheduler().schedule(_input(phases)), phases)
    assert [(segment.start, segment.work_minutes) for segment in result["B"].segments] == [
        (START + timedelta(hours=5), 180),
        (START + timedelta(days=1), 300),
    ]


def test_same_input_and_version_produce_same_semantic_segments():
    phases = [_phase("A", 240, 2), _phase("B", 120, 1), _phase("C", 60, 1)]
    value = _input(phases)
    first = GreedyFiniteCapacityScheduler().schedule(value)
    second = GreedyFiniteCapacityScheduler().schedule(value)
    assert first == second
    assert GreedyFiniteCapacityScheduler.version == "v1-greedy-2"
