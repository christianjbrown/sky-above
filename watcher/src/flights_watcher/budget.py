"""A monthly cap on paid lookups, so a busy sky cannot run up a bill.

The count is kept in a file, so a restart does not hand out the month again."""

import json
import pathlib
from typing import Any

from flights_watcher.clock import Clock
from flights_watcher.http import JsonHttp


class BudgetSpent(OSError):
    """This month's lookups are used up. An OSError, as JsonHttp promises, so callers treat it as an outage."""


class MonthlyBudget:
    def __init__(self, limit: int, path: pathlib.Path, clock: Clock) -> None:
        self._limit = limit
        self._path = path
        self._clock = clock

    def spend(self) -> None:
        month = self._clock.now().strftime("%Y-%m")
        used = self._used(month)
        if used >= self._limit:
            raise BudgetSpent(f"all {self._limit} lookups for {month} are used")
        partial = self._path.with_suffix(".part")
        partial.write_text(json.dumps({"month": month, "used": used + 1}))
        partial.replace(self._path)

    def _used(self, month: str) -> int:
        try:
            saved = json.loads(self._path.read_text())
        except (OSError, ValueError):
            return 0
        return int(saved.get("used", 0)) if saved.get("month") == month else 0


class BudgetedHttp:
    def __init__(self, inner: JsonHttp, budget: MonthlyBudget) -> None:
        self._inner = inner
        self._budget = budget

    def get_json(self, url: str) -> Any:
        self._budget.spend()
        return self._inner.get_json(url)
