"""Where the current list of aircraft comes from."""

from typing import Protocol

from flights_watcher.aircraft import Aircraft
from flights_watcher.http import JsonHttp


class AircraftSource(Protocol):
    def aircraft(self) -> list[Aircraft]: ...


class Tar1090AircraftSource:
    """Reads the aircraft.json that ultrafeeder's tar1090 serves."""

    def __init__(self, url: str, http: JsonHttp) -> None:
        self._url = url
        self._http = http

    def aircraft(self) -> list[Aircraft]:
        data = self._http.get_json(self._url)
        return [Aircraft.from_tar1090(raw) for raw in data.get("aircraft", []) if "hex" in raw]
