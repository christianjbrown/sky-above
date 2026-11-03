"""The card for a browser on the home network, for when the Hub is not the one looking."""

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Protocol

CLEAR = {"type": "clear"}


class Snapshot(Protocol):
    def latest(self) -> dict[str, Any]: ...


class LatestCard:
    """A Display that remembers the last message, so the page can ask for it."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._message: dict[str, Any] = CLEAR

    def show(self, message: dict[str, Any]) -> bool:
        with self._lock:
            self._message = message
        return True

    def clear(self) -> None:
        with self._lock:
            self._message = CLEAR

    def latest(self) -> dict[str, Any]:
        with self._lock:
            return self._message


class LiveServer:
    """Answers GET /planes.json with the latest message, in a background thread, from
    when it is started until it is stopped."""

    PATH = "/planes.json"

    def __init__(self, snapshot: Snapshot, host: str, port: int, logger: logging.Logger) -> None:
        self._handler = _handler_for(snapshot)
        self._address = (host, port)
        self._logger = logger
        self._server: ThreadingHTTPServer | None = None

    def start(self) -> int:
        """Starts listening, and says on which port (the one asked for, unless that was 0)."""
        self._server = ThreadingHTTPServer(self._address, self._handler)
        port = self._server.server_address[1]
        threading.Thread(target=self._server.serve_forever, name="live-card", daemon=True).start()
        self._logger.info("serving the live card on port %d", port)
        return port

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None


def _handler_for(snapshot: Snapshot) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path.split("?", 1)[0] != LiveServer.PATH:
                self.send_error(404)
                return
            body = json.dumps(snapshot.latest()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            pass

    return Handler
