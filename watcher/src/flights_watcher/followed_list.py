"""The flights worth following on the Hub: our own, and friends and family coming and going.

They are kept in a plain text file on the Pi, one a line, so they never reach the
repo, and the file is read again each time, so an edit shows up without a restart:

    2027-03-01 BA2468
    # lines starting with a hash are ignored

The date is the day the flight is due to leave, in the time at the airport it leaves from."""

import logging
import pathlib
from dataclasses import dataclass
from datetime import date
from typing import Protocol


@dataclass(frozen=True)
class FollowedEntry:
    day: date
    ident: str


class FollowedList(Protocol):
    def entries(self) -> list[FollowedEntry]: ...


class FollowedListFile:
    def __init__(self, path: pathlib.Path, logger: logging.Logger) -> None:
        self._path = path
        self._logger = logger
        self._complained: set[str] = set()

    def entries(self) -> list[FollowedEntry]:
        try:
            lines = self._path.read_text().splitlines()
        except FileNotFoundError:
            return []
        except OSError as error:
            self._complain(f"cannot read {self._path}: {error}")
            return []
        found = []
        for line in lines:
            entry = _entry(line)
            if entry is not None:
                found.append(entry)
            elif line.strip() and not line.lstrip().startswith("#"):
                self._complain(f"not a date and a flight number: {line.strip()!r}")
        return found

    def _complain(self, problem: str) -> None:
        if problem not in self._complained:
            self._complained.add(problem)
            self._logger.warning("followed flights: %s", problem)


def _entry(line: str) -> FollowedEntry | None:
    words = line.split("#", 1)[0].split()
    if len(words) != 2:
        return None
    try:
        day = date.fromisoformat(words[0])
    except ValueError:
        return None
    return FollowedEntry(day, words[1].upper())
