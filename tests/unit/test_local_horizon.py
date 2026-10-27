from datetime import date,datetime,timezone
from zoneinfo import ZoneInfo
import pytest
from production_besten.domain.scheduling.horizon import local_scheduling_horizon
from production_besten.domain.errors import InvalidSchedulingInput
from production_besten.api.production_readiness_schemas import ProductionSimulationRequest

ZONE='America/Argentina/Cordoba'


def test_date_only_is_plant_midnight_not_previous_evening():
    start,end=local_scheduling_horizon(date(2026,10,26),date(2026,10,27),ZONE,datetime(2026,10,25,12,tzinfo=timezone.utc))
    assert start.isoformat()=='2026-10-26T03:00:00+00:00'
    assert start.astimezone(ZoneInfo(ZONE)).date()==date(2026,10,26)
    assert end.isoformat()=='2026-10-27T03:00:00+00:00'


@pytest.mark.parametrize('selected',[date(2026,10,25),date(2026,10,26)])
def test_today_and_past_never_schedule_before_injected_now(selected):
    now=datetime(2026,10,26,18,tzinfo=timezone.utc)
    assert local_scheduling_horizon(selected,date(2026,10,28),ZONE,now)[0]==now


def test_expired_horizon_is_a_domain_error():
    with pytest.raises(InvalidSchedulingInput):
        local_scheduling_horizon(date(2026,10,26),date(2026,10,27),ZONE,datetime(2026,10,28,tzinfo=timezone.utc))


@pytest.mark.parametrize('start,kind',[('2026-10-26',date),('2026-10-26T03:00:00Z',datetime),('2026-10-26T00:00:00-03:00',datetime)])
def test_http_dates_and_aware_instants_keep_their_semantics(start,kind):
    value=ProductionSimulationRequest(expected_row_version=1,evaluation_token='a'*64,reason='Test',horizon_start=start,horizon_end='2026-10-28')
    assert type(value.horizon_start) is kind


def test_http_rejects_naive_timestamp():
    with pytest.raises(ValueError):
        ProductionSimulationRequest(expected_row_version=1,evaluation_token='a'*64,reason='Test',horizon_start='2026-10-26T12:00:00',horizon_end='2026-10-28')
