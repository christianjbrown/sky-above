from datetime import datetime
from decimal import Decimal
from urllib.error import HTTPError

import pytest

from fakes import FakeClock, FakeHttp, http_error
from flights_watcher.budget import BudgetedHttp, BudgetSpent, MonthlyBudget, PricedByPath
from flights_watcher.wiring import AEROAPI_PRICES, AEROAPI_UNLISTED_PRICE

BASE = "https://aeroapi.test/aeroapi"
ROUTE_URL = f"{BASE}/flights/EWG6U?ident_type=designator&max_pages=1"
OPERATOR_URL = f"{BASE}/operators/EWG"
AEROAPI = PricedByPath(BASE, AEROAPI_PRICES, AEROAPI_UNLISTED_PRICE)


def budgeted(http, limit, path, clock):
    return BudgetedHttp(http, MonthlyBudget(Decimal(limit), path, clock), AEROAPI)


def test_each_aeroapi_request_is_priced_at_flightawares_fee():
    assert AEROAPI.price(ROUTE_URL) == Decimal("0.005")
    assert AEROAPI.price(f"{BASE}/flights/EWG6U-1762070400-schedule-0001?ident_type=fa_flight_id") == Decimal("0.005")
    assert AEROAPI.price(f"{BASE}/flights/EWG6U-1762070400-schedule-0001/position") == Decimal("0.010")
    assert AEROAPI.price(OPERATOR_URL) == Decimal("0.015")
    assert AEROAPI.price(f"{BASE}/history/flights/EWG6U") == AEROAPI_UNLISTED_PRICE
    assert AEROAPI.price("https://aeroapi.test/flights/EWG6U") == AEROAPI_UNLISTED_PRICE


def test_the_budget_stops_at_its_dollars_survives_a_restart_and_starts_again_each_month(tmp_path):
    clock = FakeClock(datetime(2026, 11, 30, 23, 0))
    http = FakeHttp({OPERATOR_URL: {"name": "Eurowings"}, ROUTE_URL: {"flights": []}})
    budgeted(http, "0.020", tmp_path / "aeroapi.json", clock).get_json(OPERATOR_URL)
    restarted = budgeted(http, "0.020", tmp_path / "aeroapi.json", clock)
    with pytest.raises(BudgetSpent, match=r"the \$0.020 for 2026-11 is spent"):
        restarted.get_json(OPERATOR_URL)
    # A cheaper request still fits in what is left, to the last cent.
    restarted.get_json(ROUTE_URL)
    with pytest.raises(BudgetSpent):
        restarted.get_json(ROUTE_URL)
    assert http.requested == [OPERATOR_URL, ROUTE_URL]
    clock.at = datetime(2026, 12, 1, 0, 0)
    restarted.get_json(OPERATOR_URL)
    assert len(http.requested) == 3


def test_a_request_that_fails_costs_nothing(tmp_path):
    clock = FakeClock()
    http = FakeHttp({OPERATOR_URL: http_error(404), ROUTE_URL: {"flights": []}})
    # Charged for the failed 0.015, the route after it would not fit.
    lookups = budgeted(http, "0.015", tmp_path / "aeroapi.json", clock)
    with pytest.raises(HTTPError) as refused:
        lookups.get_json(OPERATOR_URL)
    refused.value.close()
    lookups.get_json(ROUTE_URL)
    assert http.requested == [OPERATOR_URL, ROUTE_URL]


def test_an_unreadable_record_counts_as_nothing_spent(tmp_path):
    record = tmp_path / "aeroapi.json"
    record.write_text("not json")
    http = FakeHttp({ROUTE_URL: {"flights": []}})
    budgeted(http, "0.005", record, FakeClock()).get_json(ROUTE_URL)
    assert record.read_text() == '{"month": "2026-11", "spent": "0.005"}'
