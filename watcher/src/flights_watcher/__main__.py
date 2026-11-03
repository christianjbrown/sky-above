"""Runs the watcher until it is told to stop."""

import logging
import os
import signal
import threading
from collections.abc import Mapping
from zoneinfo import ZoneInfo

from flights_watcher.clock import SystemClock
from flights_watcher.config import Settings
from flights_watcher.runner import Runner
from flights_watcher.wiring import build


def main(environ: Mapping[str, str], stop: threading.Event) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logger = logging.getLogger("flights")
    settings = Settings.from_env(environ)
    app = build(settings, SystemClock(ZoneInfo(settings.timezone)), logger)
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    if app.live_server is not None:
        app.live_server.start()
    logger.info("watching %.1f km around home", settings.radius_km)
    try:
        Runner(app.watcher, app.display, settings.poll_seconds, logger).run(stop)
    finally:
        if app.live_server is not None:
            app.live_server.stop()


if __name__ == "__main__":
    main(os.environ, threading.Event())
