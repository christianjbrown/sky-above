"""Takes flights that are over off the followed list, so it only holds what is still to come.

The watcher reads the list read-only, so this runs as its own small service, as the
user who owns the file, and checks the list every few hours. A flight goes once its date
is more than a couple of days ago, which leaves room for one that lands the day after
it leaves, in another time zone. Comments, blank lines and lines it cannot read are left
exactly as they are.

    python -m flights_watcher.followed_pruner
"""

import logging
import os
import pathlib
import signal
import tempfile
import threading
from collections.abc import Mapping
from datetime import timedelta
from zoneinfo import ZoneInfo

from flights_watcher.clock import Clock, SystemClock
from flights_watcher.followed_list import entry_from_line

CHECK_EVERY_SECONDS = 6 * 3600
# A flight can leave late on its date in one time zone and land two dates later in ours.
KEPT_AFTER = timedelta(days=2)
FILE_SETTING = "FOLLOWED_FILE"
ZONE_SETTING = "TZ"
DEFAULT_ZONE = "UTC"


class FollowedListPruner:
    def __init__(self, path: pathlib.Path, clock: Clock, logger: logging.Logger) -> None:
        self._path = path
        self._clock = clock
        self._logger = logger

    def prune(self) -> list[str]:
        """Removes the flights that are over and gives back the lines it took out."""
        try:
            text = self._path.read_text()
        except FileNotFoundError:
            return []
        except OSError as error:
            self._logger.warning("followed flights: cannot read %s: %s", self._path, error)
            return []
        oldest_kept = self._clock.now().date() - KEPT_AFTER
        kept: list[str] = []
        removed: list[str] = []
        for line in text.splitlines(keepends=True):
            entry = entry_from_line(line)
            (removed if entry is not None and entry.day < oldest_kept else kept).append(line)
        if removed:
            try:
                self._replace("".join(kept))
            except OSError as error:
                self._logger.warning("followed flights: cannot rewrite %s: %s", self._path, error)
                return []
            for line in removed:
                self._logger.info("followed flights: %s is over, taken off the list", line.strip())
        return removed

    def _replace(self, text: str) -> None:
        """Written beside the list and swapped in whole, so the watcher never reads half a file."""
        mode = self._path.stat().st_mode
        handle, name = tempfile.mkstemp(dir=self._path.parent, prefix=f".{self._path.name}.")
        temporary = pathlib.Path(name)
        try:
            with os.fdopen(handle, "w") as written:
                written.write(text)
            temporary.chmod(mode)
            temporary.replace(self._path)
        except OSError:
            temporary.unlink(missing_ok=True)
            raise


def build(environ: Mapping[str, str], logger: logging.Logger) -> FollowedListPruner:
    clock = SystemClock(ZoneInfo(environ.get(ZONE_SETTING) or DEFAULT_ZONE))
    return FollowedListPruner(pathlib.Path(environ[FILE_SETTING]), clock, logger)


def main(environ: Mapping[str, str], stop: threading.Event) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logger = logging.getLogger("followed-pruner")
    pruner = build(environ, logger)
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    logger.info("taking finished flights off %s", environ[FILE_SETTING])
    pruner.prune()
    while not stop.wait(CHECK_EVERY_SECONDS):
        pruner.prune()


if __name__ == "__main__":
    main(os.environ, threading.Event())
