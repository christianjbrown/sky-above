"""The tunings the watcher runs with, from tuning/tuning.toml and anything tuning/local.toml
changes. Every value has to be there and of the right kind, and nothing unknown may be,
so a typo stops the watcher at start-up rather than being quietly ignored."""

import pathlib
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from flights_watcher.config import ConfigError
from flights_watcher.estimate import TurnaroundRule
from flights_watcher.following import FollowTiming
from flights_watcher.paths import Likeness

MINUTE = 60
HOUR = 60 * MINUTE
DAY = 24 * HOUR


class TuningError(ConfigError):
    pass


class TuningTable:
    """One [section] of the file, read a value at a time. done() then refuses any key
    that nothing read, in it or the sections read from it."""

    def __init__(self, data: Mapping[str, Any], name: str) -> None:
        self._data = data
        self._name = name
        self._read: set[str] = set()
        self._children: list[TuningTable] = []

    def number(self, key: str) -> float:
        value = self._get(key)
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise TuningError(f"{self._where(key)} should be a number, not {value!r}")
        return float(value)

    def whole(self, key: str) -> int:
        value = self._get(key)
        if isinstance(value, bool) or not isinstance(value, int):
            raise TuningError(f"{self._where(key)} should be a whole number, not {value!r}")
        return value

    def text(self, key: str) -> str:
        value = self._get(key)
        if not isinstance(value, str):
            raise TuningError(f"{self._where(key)} should be text, not {value!r}")
        return value

    def texts(self, key: str) -> tuple[str, ...]:
        return _texts(self._get(key), self._where(key))

    def words(self, key: str) -> dict[str, str]:
        """A table whose keys are chosen by whoever writes the file, each with text."""
        found = dict(self._mapping(key))
        for name, value in found.items():
            if not isinstance(value, str):
                raise TuningError(f"{self._where(key)}.{name} should be text, not {value!r}")
        return found

    def lists(self, key: str) -> dict[str, tuple[str, ...]]:
        """A table whose keys are chosen by whoever writes the file, each with a list of text."""
        return {name: _texts(value, f"{self._where(key)}.{name}") for name, value in self._mapping(key).items()}

    def table(self, key: str) -> "TuningTable":
        child = TuningTable(self._mapping(key), self._where(key))
        self._children.append(child)
        return child

    def tables(self, key: str) -> list["TuningTable"]:
        value = self._get(key)
        if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
            raise TuningError(f"{self._where(key)} should be a list of [[{self._where(key)}]] tables")
        children = [TuningTable(item, f"{self._where(key)}[{index}]") for index, item in enumerate(value)]
        self._children.extend(children)
        return children

    def done(self) -> None:
        unknown = sorted(set(self._data) - self._read)
        if unknown:
            raise TuningError(f"{self._name or 'the tuning file'} has nothing called {', '.join(unknown)}")
        for child in self._children:
            child.done()

    def _get(self, key: str) -> Any:
        if key not in self._data:
            raise TuningError(f"{self._where(key)} is missing")
        self._read.add(key)
        return self._data[key]

    def _mapping(self, key: str) -> Mapping[str, Any]:
        value = self._get(key)
        if not isinstance(value, dict):
            raise TuningError(f"{self._where(key)} should be a [{self._where(key)}] table")
        return value

    def _where(self, key: str) -> str:
        return f"{self._name}.{key}" if self._name else key


def _texts(value: Any, where: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise TuningError(f"{where} should be a list of text, not {value!r}")
    return tuple(value)


def merged(base: Mapping[str, Any], changes: Mapping[str, Any]) -> dict[str, Any]:
    """The base with changes laid over it, table by table; anything else is replaced whole."""
    result = dict(base)
    for key, value in changes.items():
        under = result.get(key)
        result[key] = merged(under, value) if isinstance(under, dict) and isinstance(value, dict) else value
    return result


def read_toml(path: pathlib.Path) -> dict[str, Any]:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        raise TuningError(f"{path} is not valid TOML: {error}") from error


@dataclass(frozen=True)
class Tuning:
    user_agent: str
    http_timeout_seconds: float
    lookup_ttl_seconds: float
    lookup_cache_entries: int
    route_retry_seconds: float
    operator_ttl_seconds: float
    no_route_ttl_seconds: float
    route_kept_fresh: timedelta
    operator_kept_fresh: timedelta
    icao_numbered_airlines: tuple[str, ...]
    answers_file: str
    aeroapi_budget_file: str
    followed_budget_file: str
    announced_file: str
    paths_file: str
    misses_file: str
    notable_file: str
    # Each airport's code with the city to say for it.
    airport_cities: dict[str, str]
    cast_retry_seconds: float
    chime_seconds: float
    cast_launch_seconds: float
    live_host: str
    speech_timeout_seconds: float
    spoken_chars_per_second: float
    clip_making_ratio: float
    unmute_settle_seconds: float
    showing_start_seconds: float
    speech_clips_kept: int
    overhead_now_km: float
    announced_kept_for: timedelta
    speech_url_prefix: str
    said_as_words: dict[str, str]
    surroundings_km: float
    max_other_planes: int
    approach_steady_polls: int
    approach_steady_polls_per_km: float
    approach_max_turn_deg: float
    approach_min_speed_kt: float
    approach_wander_km: float
    steered_below_ft: int
    steered_beyond_km: float
    descending_fpm: int
    bound_within_deg: float
    approach_due_seconds: float
    overhead_soon_seconds: float
    path_km: float
    path_every_seconds: float
    path_gone_seconds: float
    path_likeness: Likeness
    path_min_planes: int
    path_held_polls: int
    paths_kept: int
    path_kept_for: timedelta
    misses_min: int
    follow_timing: FollowTiming
    late_minutes: int
    delay_step_minutes: int
    landing_soon: timedelta
    followed_news_kept_seconds: float
    block_times_kept_seconds: float
    turnarounds: tuple[TurnaroundRule, ...]
    default_turnaround: timedelta
    emergency_held_polls: int
    steep_held_polls: int
    emergency_clear_seconds: float
    steep_descent_fpm: int
    steep_climb_fpm: int
    steep_altitude_share: float
    emergencies_announced_remembered: int
    services_kept: tuple[str, ...]
    service_hold_km: float
    notable_max_age_seconds: float
    notable_reread_seconds: float
    notable_timeout_seconds: float
    portrait_cache_seconds: float
    portrait_retry_seconds: float
    portrait_cache_entries: int

    @property
    def named_airports(self) -> tuple[str, ...]:
        """Airports of cities that have several, announced by name rather than city."""
        cities = list(self.airport_cities.values())
        return tuple(code for code, city in self.airport_cities.items() if cities.count(city) > 1)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "Tuning":
        root = TuningTable(data, "")
        http, lookups, state = root.table("http"), root.table("lookups"), root.table("state")
        airports, cast, live, speech = root.table("airports"), root.table("cast"), root.table("live"), root.table("speech")
        surroundings, approach, paths = root.table("map"), root.table("approach"), root.table("paths")
        followed, emergency, services = root.table("followed"), root.table("emergency"), root.table("services")
        notable, portraits = root.table("notable"), root.table("portraits")
        tuning = cls(
            user_agent=http.text("user_agent"),
            http_timeout_seconds=http.number("timeout_seconds"),
            lookup_ttl_seconds=lookups.number("ttl_hours") * HOUR,
            lookup_cache_entries=lookups.whole("cache_entries"),
            route_retry_seconds=lookups.number("route_retry_seconds"),
            operator_ttl_seconds=lookups.number("operator_ttl_days") * DAY,
            no_route_ttl_seconds=lookups.number("no_route_ttl_minutes") * MINUTE,
            route_kept_fresh=timedelta(days=lookups.number("route_kept_fresh_days")),
            operator_kept_fresh=timedelta(days=lookups.number("operator_kept_fresh_days")),
            icao_numbered_airlines=lookups.texts("icao_numbered_airlines"),
            answers_file=state.text("answers_file"),
            aeroapi_budget_file=state.text("aeroapi_budget_file"),
            followed_budget_file=state.text("followed_budget_file"),
            announced_file=state.text("announced_file"),
            paths_file=state.text("paths_file"),
            misses_file=state.text("misses_file"),
            notable_file=state.text("notable_file"),
            airport_cities={code: city for city, codes in airports.lists("cities").items() for code in codes},
            cast_retry_seconds=cast.number("retry_seconds"),
            chime_seconds=cast.number("chime_seconds"),
            cast_launch_seconds=cast.number("launch_seconds"),
            live_host=live.text("host"),
            speech_timeout_seconds=speech.number("timeout_seconds"),
            spoken_chars_per_second=speech.number("spoken_chars_per_second"),
            clip_making_ratio=speech.number("clip_making_ratio"),
            unmute_settle_seconds=speech.number("unmute_settle_seconds"),
            showing_start_seconds=speech.number("showing_start_seconds"),
            speech_clips_kept=speech.whole("clips_kept"),
            overhead_now_km=speech.number("overhead_now_km"),
            announced_kept_for=timedelta(hours=speech.number("announced_kept_hours")),
            speech_url_prefix=speech.text("url_prefix"),
            said_as_words=speech.words("said_as"),
            surroundings_km=surroundings.number("surroundings_km"),
            max_other_planes=surroundings.whole("max_other_planes"),
            approach_steady_polls=approach.whole("steady_polls"),
            approach_steady_polls_per_km=approach.number("steady_polls_per_km"),
            approach_max_turn_deg=approach.number("max_turn_deg"),
            approach_min_speed_kt=approach.number("min_speed_kt"),
            approach_wander_km=approach.number("wander_km"),
            steered_below_ft=approach.whole("steered_below_ft"),
            steered_beyond_km=approach.number("steered_beyond_km"),
            descending_fpm=approach.whole("descending_fpm"),
            bound_within_deg=approach.number("bound_within_deg"),
            approach_due_seconds=approach.number("due_seconds"),
            overhead_soon_seconds=approach.number("overhead_soon_seconds"),
            path_km=paths.number("km"),
            path_every_seconds=paths.number("every_seconds"),
            path_gone_seconds=paths.number("gone_seconds"),
            path_likeness=Likeness(
                within_km=paths.number("within_km"), within_ft=paths.whole("within_ft"), within_deg=paths.number("within_deg")
            ),
            path_min_planes=paths.whole("min_planes"),
            path_held_polls=paths.whole("held_polls"),
            paths_kept=paths.whole("kept"),
            path_kept_for=timedelta(days=paths.number("kept_days")),
            misses_min=paths.whole("misses_min"),
            follow_timing=FollowTiming(
                lead=timedelta(hours=followed.number("lead_hours")),
                tail=timedelta(minutes=followed.number("tail_minutes")),
                before_showing_every=followed.number("before_showing_every_minutes") * MINUTE,
                hours_to_go_every=followed.number("hours_to_go_every_minutes") * MINUTE,
                last_hour_every=followed.number("last_hour_every_minutes") * MINUTE,
                under_way_every=followed.number("under_way_every_minutes") * MINUTE,
                earlier_leg_every=followed.number("earlier_leg_every_minutes") * MINUTE,
                position_every=followed.number("position_every_minutes") * MINUTE,
                not_found_every=followed.number("not_found_every_minutes") * MINUTE,
            ),
            late_minutes=followed.whole("late_minutes"),
            delay_step_minutes=followed.whole("delay_step_minutes"),
            landing_soon=timedelta(minutes=followed.number("landing_soon_minutes")),
            followed_news_kept_seconds=followed.number("news_kept_seconds"),
            block_times_kept_seconds=followed.number("block_times_kept_hours") * HOUR,
            turnarounds=tuple(
                TurnaroundRule(rule.texts("types"), timedelta(minutes=rule.number("minutes"))) for rule in followed.tables("turnarounds")
            ),
            default_turnaround=timedelta(minutes=followed.number("default_turnaround_minutes")),
            emergency_held_polls=emergency.whole("held_polls"),
            steep_held_polls=emergency.whole("steep_held_polls"),
            emergency_clear_seconds=emergency.number("clear_seconds"),
            steep_descent_fpm=emergency.whole("steep_descent_fpm"),
            steep_climb_fpm=emergency.whole("steep_climb_fpm"),
            steep_altitude_share=emergency.number("steep_altitude_share"),
            emergencies_announced_remembered=emergency.whole("announced_remembered"),
            services_kept=services.texts("kept"),
            service_hold_km=services.number("hold_km"),
            notable_max_age_seconds=notable.number("max_age_hours") * HOUR,
            notable_reread_seconds=notable.number("reread_minutes") * MINUTE,
            notable_timeout_seconds=notable.number("timeout_seconds"),
            portrait_cache_seconds=portraits.number("cache_hours") * HOUR,
            portrait_retry_seconds=portraits.number("retry_minutes") * MINUTE,
            portrait_cache_entries=portraits.whole("cache_entries"),
        )
        root.done()
        return tuning


def load_tuning(tuning_file: pathlib.Path, local_file: pathlib.Path | None) -> Tuning:
    """The tuning file, with the local one laid over it when there is one."""
    data = read_toml(tuning_file)
    if local_file is not None and local_file.is_file():
        data = merged(data, read_toml(local_file))
    return Tuning.from_mapping(data)
