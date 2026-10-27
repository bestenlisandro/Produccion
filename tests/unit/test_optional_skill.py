from dataclasses import replace
from datetime import timedelta, time

import pytest

from production_besten.domain.scheduling.engine import GreedyFiniteCapacityScheduler
from production_besten.domain.scheduling.models import EmployeeData, LaborNeed, TimeWindow
from tests.unit.test_cumulative_scheduler import _id, _phase, _input, START


def people():
    return tuple(EmployeeData(_id(name),name,_id('calendar'),frozenset())
                 for name in ('Mariano','Emiliano','Gonzalo'))


@pytest.mark.parametrize('count',[1,2])
def test_unskilled_human_demand_selects_distinct_real_people(count):
    phase=replace(_phase('A',20,1),physical=(),required_people=count)
    result=GreedyFiniteCapacityScheduler().schedule(_input([phase],employees=people()))
    assert result.complete
    segment=result.outcomes[0].segments[0]
    assert segment.start == START and segment.end == START+timedelta(minutes=20)
    assert len(segment.employee_ids)==len(set(segment.employee_ids))==count
    assert set(segment.employee_ids)<=set(p.id for p in people())


def test_generic_team_respects_calendars_and_unavailability():
    phase=replace(_phase('A',20,1),physical=(),required_people=2)
    value=_input([phase],employees=people()[:2])
    calendar=value.calendars[_id('calendar')]
    late=replace(calendar,intervals=tuple(replace(w,local_start=time(9)) for w in calendar.intervals))
    value=replace(value,calendars={calendar.id:late},unavailability={people()[0].id:(TimeWindow(START,START+timedelta(hours=2)),)})
    result=GreedyFiniteCapacityScheduler().schedule(value)
    assert result.complete and result.outcomes[0].segments[0].start==START+timedelta(hours=2)


def test_unskilled_phases_reserve_people_without_overlap():
    phases=[replace(_phase(code,20,1),physical=(),required_people=2) for code in ['A','B']]
    result=GreedyFiniteCapacityScheduler().schedule(_input(phases,employees=people()[:2]))
    assert result.complete
    spans=sorted((s.start,s.end) for o in result.outcomes for s in o.segments)
    assert spans[0][1]<=spans[1][0]


def test_real_skill_still_excludes_unqualified_people():
    skill=_id('skill')
    qualified=replace(people()[0],skills=frozenset([skill]))
    phase=replace(_phase('A',60,1),physical=(),required_people=1,labor=(LaborNeed(skill,1,1,60),))
    result=GreedyFiniteCapacityScheduler().schedule(_input([phase],employees=(*people()[1:],qualified)))
    assert result.complete and result.outcomes[0].segments[0].employee_ids==(qualified.id,)
    blocked=GreedyFiniteCapacityScheduler().schedule(_input([phase],employees=people()[1:]))
    assert not blocked.complete and 'REQUIRED_SKILL_UNAVAILABLE' in blocked.outcomes[0].blockers


def test_not_enough_people_is_not_a_missing_skill_error():
    phase=replace(_phase('A',20,1),physical=(),required_people=2)
    result=GreedyFiniteCapacityScheduler().schedule(_input([phase],employees=people()[:1]))
    assert not result.complete
    assert 'REQUIRED_PEOPLE_UNAVAILABLE' in result.outcomes[0].blockers
    assert 'REQUIRED_SKILL_UNAVAILABLE' not in result.outcomes[0].blockers


def test_legacy_automatic_phase_does_not_acquire_human_demand():
    from production_besten.persistence.product_editor_uow import _legacy_people_intent
    body={'lots':[{'operations':[{'phases':[{'required_people':0,'labor_requirements':[{'productivity_curve':{'required_people':0}}]}]}]}]}
    normalized=_legacy_people_intent(body)
    ph=normalized['lots'][0]['operations'][0]['phases'][0]
    assert 'required_people' not in ph
    assert ph['labor_requirements'][0]['productivity_curve']=={'required_people':0}
    assert body['lots'][0]['operations'][0]['phases'][0]['required_people']==0

    phase=replace(_phase('A',20,1),physical=())
    result=GreedyFiniteCapacityScheduler().schedule(_input([phase]))
    assert result.complete and result.outcomes[0].segments[0].employee_ids==()
