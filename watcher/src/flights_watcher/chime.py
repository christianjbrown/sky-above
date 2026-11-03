"""Hiding the chime the Hub plays whenever a Cast app starts.

The chime is part of the Hub's firmware and has no setting, so the Hub is muted
for the launch and unmuted once the chime has passed. The watcher only launches
on an idle Hub, so nothing else is silenced."""

from collections.abc import Callable
from typing import Any, Protocol


class Mutable(Protocol):
    def is_muted(self) -> bool: ...

    def set_muted(self, muted: bool) -> None: ...


class LaunchingDevice(Mutable, Protocol):
    def running_app_id(self) -> str | None: ...

    def is_idle(self) -> bool: ...

    def is_hidden(self) -> bool: ...

    def launch(self, app_id: str) -> None: ...

    def send(self, payload: dict[str, Any]) -> None: ...

    def quit(self) -> None: ...


class MutedLaunchDevice:
    """Launches with the Hub muted, and always puts the sound back as it was,
    even when the launch fails."""

    def __init__(self, inner: LaunchingDevice, chime_seconds: float, pause: Callable[[float], None]) -> None:
        self._inner = inner
        self._chime_seconds = chime_seconds
        self._pause = pause

    def running_app_id(self) -> str | None:
        return self._inner.running_app_id()

    def is_idle(self) -> bool:
        return self._inner.is_idle()

    def is_hidden(self) -> bool:
        return self._inner.is_hidden()

    def launch(self, app_id: str) -> None:
        if self._inner.is_muted():
            self._inner.launch(app_id)
            return
        self._inner.set_muted(True)
        try:
            self._inner.launch(app_id)
            self._pause(self._chime_seconds)
        finally:
            self._inner.set_muted(False)

    def send(self, payload: dict[str, Any]) -> None:
        self._inner.send(payload)

    def quit(self) -> None:
        self._inner.quit()
