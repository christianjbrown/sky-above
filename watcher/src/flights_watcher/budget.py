"""A monthly cap on what paid lookups cost, so a busy sky cannot run up a bill.

The cap is in dollars rather than requests because a paid service charges some
requests more than others: AeroAPI's airline names cost three times its routes.
What has been spent is kept in a file, so a restart does not hand out the month again."""

import json
import pathlib
import re
from collections.abc import Sequence
from decimal import Decimal
from typing import Any, Protocol
from urllib.parse import urlsplit

from flights_watcher.clock import Clock
from flights_watcher.http import JsonHttp


class BudgetSpent(OSError):
    """This month's money is spent. An OSError, as JsonHttp promises, so callers treat it as an outage."""


class Pricing(Protocol):
    def price(self, url: str) -> Decimal:
        """What one request to this address costs, in dollars."""
        ...


class PricedByPath:
    """Prices from a list of patterns for the whole path below a service's base address,
    the first match winning, and a fallback for anything the list does not name."""

    def __init__(self, base_url: str, prices: Sequence[tuple[str, Decimal]], fallback: Decimal) -> None:
        self._base_path = urlsplit(base_url).path.rstrip("/")
        self._prices = [(re.compile(pattern), price) for pattern, price in prices]
        self._fallback = fallback

    def price(self, url: str) -> Decimal:
        path = urlsplit(url).path
        if not path.startswith(f"{self._base_path}/"):
            return self._fallback
        below = path.removeprefix(self._base_path)
        return next((price for pattern, price in self._prices if pattern.fullmatch(below)), self._fallback)


class Budget(Protocol):
    def check(self, cost: Decimal) -> None:
        """Raises BudgetSpent when spending this much would go over the month's limit."""
        ...

    def charge(self, cost: Decimal) -> None: ...


class MonthlyBudget:
    def __init__(self, limit: Decimal, path: pathlib.Path, clock: Clock) -> None:
        self._limit = limit
        self._path = path
        self._clock = clock

    def check(self, cost: Decimal) -> None:
        month = self._month()
        if self._spent(month) + cost > self._limit:
            raise BudgetSpent(f"the ${self._limit} for {month} is spent")

    def charge(self, cost: Decimal) -> None:
        month = self._month()
        partial = self._path.with_suffix(".part")
        partial.write_text(json.dumps({"month": month, "spent": str(self._spent(month) + cost)}))
        partial.replace(self._path)

    def _month(self) -> str:
        return self._clock.now().strftime("%Y-%m")

    def _spent(self, month: str) -> Decimal:
        try:
            saved = json.loads(self._path.read_text())
        except (OSError, ValueError):
            return Decimal(0)
        return Decimal(saved.get("spent", "0")) if saved.get("month") == month else Decimal(0)


class BudgetedHttp:
    """Only an answer is charged for. A request that fails, such as AeroAPI's 404 for a
    callsign it does not know, costs nothing there and so costs nothing here."""

    def __init__(self, inner: JsonHttp, budget: Budget, pricing: Pricing) -> None:
        self._inner = inner
        self._budget = budget
        self._pricing = pricing

    def get_json(self, url: str) -> Any:
        cost = self._pricing.price(url)
        self._budget.check(cost)
        answer = self._inner.get_json(url)
        self._budget.charge(cost)
        return answer
