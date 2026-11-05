"""One aircraft as readsb reports it in tar1090's aircraft.json."""

from dataclasses import dataclass
from typing import Any

from flights_watcher.geo import Location

# The bit in readsb's dbFlags that marks a military airframe.
MILITARY_FLAG = 1


@dataclass(frozen=True)
class Aircraft:
    hex: str
    callsign: str | None
    registration: str | None
    type_code: str | None
    description: str | None
    location: Location | None
    altitude_ft: int | None
    on_ground: bool
    ground_speed_kt: float | None
    track_deg: float | None
    vertical_rate_fpm: int | None
    category: str | None = None
    # From the decoder's aircraft database, which flags military airframes and knows
    # who owns many planes ("Royal Air Force").
    military: bool = False
    operator: str | None = None
    # The Mode A code the crew has set, such as "7700", and the plane's own ADS-B
    # emergency status ("general", "nordo"), left out when it says "none".
    squawk: str | None = None
    emergency: str | None = None

    @classmethod
    def from_tar1090(cls, raw: dict[str, Any]) -> "Aircraft":
        altitude = raw.get("alt_baro")
        has_position = "lat" in raw and "lon" in raw
        return cls(
            hex=str(raw["hex"]),
            callsign=_callsign(raw.get("flight")),
            registration=_text(raw.get("r")),
            type_code=_text(raw.get("t")),
            description=_text(raw.get("desc")),
            location=Location(float(raw["lat"]), float(raw["lon"])) if has_position else None,
            altitude_ft=altitude if isinstance(altitude, int) else None,
            on_ground=altitude == "ground",
            ground_speed_kt=_number(raw.get("gs")),
            track_deg=_number(raw.get("track")),
            vertical_rate_fpm=_whole(raw.get("baro_rate", raw.get("geom_rate"))),
            category=_text(raw.get("category")),
            military=bool((_whole(raw.get("dbFlags")) or 0) & MILITARY_FLAG),
            operator=_text(raw.get("ownOp")),
            squawk=_text(raw.get("squawk")),
            emergency=None if raw.get("emergency") == "none" else _text(raw.get("emergency")),
        )


def _callsign(value: Any) -> str | None:
    """A callsign is letters and digits. The decoder fills one it could not read with
    "@" (as in "@@@@@@@@"), which is the same as having none."""
    text = _text(value)
    return text if text and text.isascii() and text.isalnum() else None


def _text(value: Any) -> str | None:
    if value is None:
        return None
    stripped = str(value).strip()
    return stripped or None


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) else None


def _whole(value: Any) -> int | None:
    return int(value) if isinstance(value, int | float) else None
