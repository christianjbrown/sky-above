"""Where a plane will be by the time the announcement about it is heard.

Making the clip, launching the card, waiting for the Hub's sound to come back and
reading out the flight and route all take time, ten seconds and more, and an
airliner covers a couple of kilometres in that. So the distance, direction and time
until overhead are worked out for the moment they are spoken, not when the clip is made."""

import math
from dataclasses import dataclass
from typing import Any

KM_PER_HOUR_PER_KNOT = 1.852
KM_PER_DEGREE_LAT = 110.574
KM_PER_DEGREE_LON_AT_EQUATOR = 111.32


@dataclass(frozen=True)
class SpeechTiming:
    """chars_per_second is how fast the voice reads, making_ratio how long the clip takes
    to make for each second of it, and the start times how long after the clip is made it
    starts playing: on a card launched for it, or on one already showing."""

    chars_per_second: float
    making_ratio: float
    launch_start_seconds: float
    showing_start_seconds: float

    def until(self, text: str, offset: int, launching: bool) -> float:
        """Seconds from now until the words at offset in text are heard."""
        making = len(text) / self.chars_per_second * self.making_ratio
        start = self.launch_start_seconds if launching else self.showing_start_seconds
        return making + start + offset / self.chars_per_second


def ahead(card: dict[str, Any], seconds: float) -> dict[str, Any]:
    """The card as it will be after seconds more of flying straight on at the same speed."""
    later = dict(card)
    if card.get("overheadInSeconds"):
        remaining = card["overheadInSeconds"] - seconds
        later["overheadInSeconds"] = remaining if remaining > 0 else None
    if any(card.get(key) is None for key in ("lat", "lon", "trackDeg", "speedKt")):
        return later
    km = card["speedKt"] * KM_PER_HOUR_PER_KNOT / 3600 * seconds
    track = math.radians(card["trackDeg"])
    later["lat"] = card["lat"] + km * math.cos(track) / KM_PER_DEGREE_LAT
    later["lon"] = card["lon"] + km * math.sin(track) / (KM_PER_DEGREE_LON_AT_EQUATOR * math.cos(math.radians(card["lat"])))
    return later
