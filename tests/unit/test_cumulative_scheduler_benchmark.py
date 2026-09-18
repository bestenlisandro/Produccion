from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from time import perf_counter

import pytest

from production_besten.domain.scheduling.engine import GreedyFiniteCapacityScheduler
from production_besten.domain.scheduling.models import CapacityUsage, ProjectData, TimeWindow
from tests.unit.test_cumulative_scheduler import START, _id, _input, _phase


@pytest.mark.parametrize(
    ("label", "project_count", "operation_count", "reservation_count", "days"),
    (("small", 3, 12, 2, 7), ("moderate", 20, 100, 20, 60)),
)
def test_cumulative_event_window_benchmark(
    label, project_count, operation_count, reservation_count, days, capsys
):
    project_ids = [_id(f"benchmark-project-{number}") for number in range(project_count)]
    projects = tuple(
        ProjectData(project_id, f"P-{number:03d}", "NORMAL", 3, None)
        for number, project_id in enumerate(project_ids)
    )
    phases = []
    for number in range(operation_count):
        phase = _phase(f"OP-{number:04d}", 60 + (number % 4) * 15, 1)
        project_number = number % project_count
        phases.append(replace(
            phase, project_id=project_ids[project_number], project_code=f"P-{project_number:03d}"
        ))
    actual = tuple(
        CapacityUsage(
            TimeWindow(START + timedelta(hours=number), START + timedelta(hours=number + 1)), 1
        )
        for number in range(reservation_count)
    )
    value = replace(
        _input(phases, actual=actual, days=days), projects=projects, phases=tuple(phases)
    )
    started = perf_counter()
    result = GreedyFiniteCapacityScheduler().schedule(value)
    elapsed_ms = (perf_counter() - started) * 1000
    print(
        f"benchmark={label} projects={project_count} operations={operation_count} "
        f"resources=1 people=0 reservations={reservation_count} elapsed_ms={elapsed_ms:.2f}"
    )
    assert result.status == "ready"
    assert elapsed_ms < 5000
