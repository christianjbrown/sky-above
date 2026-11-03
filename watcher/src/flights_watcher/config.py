"""Settings, all from the environment that docker-compose.yml hands the container."""

from collections.abc import Mapping
from dataclasses import dataclass

from flights_watcher.geo import Location
from flights_watcher.rare import KINDS

REQUIRED_KEYS = (
    "AIRCRAFT_URL",
    "HOME_LAT",
    "HOME_LON",
    "ZONE_RADIUS_KM",
    "LINGER_SECONDS",
    "CARD_MIN_SECONDS",
    "POLL_SECONDS",
    "MAX_CARDS",
    "TZ",
    "CAST_DEVICE_NAME",
    "CAST_TIMEOUT_SECONDS",
)
# Empty is meaningful for these: no quiet hours, no Cast app yet (log instead of casting),
# no route service (nothing leaves the house; cards show the flight without its route),
# no photo service (cards show a plane symbol), no live card for browsers, no spoken announcements,
# a voice that speaks at any hour, routes from adsbdb rather than FlightAware, a cast
# chime left audible (MUTE_CHIME takes true or false), no followed flights, and no air
# ambulance or police callsigns to pick out.
OPTIONAL_KEYS = (
    "QUIET_HOURS",
    "CAST_APP_ID",
    "ROUTE_API_URL",
    "PHOTO_API_URL",
    "LIVE_PORT",
    "SPEECH_SERVER",
    "SPEECH_DIR",
    "SPEECH_QUIET_HOURS",
    "AEROAPI_KEY",
    "AEROAPI_URL",
    "AEROAPI_MONTHLY_LIMIT",
    "STATE_DIR",
    "MUTE_CHIME",
    "FOLLOWED_FILE",
    "FOLLOWED_MONTHLY_LIMIT",
    "AIR_AMBULANCE_CALLSIGNS",
    "POLICE_CALLSIGNS",
    "QUIET_HOURS_EXCEPT",
    "HOME_COUNTRY",
)


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Settings:
    aircraft_url: str
    home: Location
    radius_km: float
    linger_seconds: float
    card_min_seconds: float
    poll_seconds: float
    max_cards: int
    quiet_hours: str
    timezone: str
    cast_device_name: str
    cast_app_id: str
    cast_timeout_seconds: float
    route_api_url: str
    photo_api_url: str
    live_port: int | None
    speech_server: tuple[str, int] | None
    speech_dir: str
    speech_quiet_hours: str
    aeroapi_key: str
    aeroapi_url: str
    aeroapi_monthly_limit: int
    state_dir: str
    mute_chime: bool
    followed_file: str
    followed_monthly_limit: int
    # The operator codes at the front of these services' callsigns, such as HLE.
    air_ambulance_callsigns: tuple[str, ...]
    police_callsigns: tuple[str, ...]
    # Kinds of aircraft let through both kinds of quiet hours: helicopters, military.
    quiet_hours_except: tuple[str, ...]
    # Two-letter country code, or empty to go by the nearest airport.
    home_country: str

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "Settings":
        missing = [key for key in REQUIRED_KEYS if not env.get(key, "").strip()]
        if missing:
            raise ConfigError(f"missing settings: {', '.join(missing)}")
        try:
            return cls(
                aircraft_url=env["AIRCRAFT_URL"],
                home=Location(float(env["HOME_LAT"]), float(env["HOME_LON"])),
                radius_km=float(env["ZONE_RADIUS_KM"]),
                linger_seconds=float(env["LINGER_SECONDS"]),
                card_min_seconds=float(env["CARD_MIN_SECONDS"]),
                poll_seconds=float(env["POLL_SECONDS"]),
                max_cards=int(env["MAX_CARDS"]),
                quiet_hours=env.get("QUIET_HOURS", ""),
                timezone=env["TZ"],
                cast_device_name=env["CAST_DEVICE_NAME"],
                cast_app_id=env.get("CAST_APP_ID", "").strip(),
                cast_timeout_seconds=float(env["CAST_TIMEOUT_SECONDS"]),
                route_api_url=env.get("ROUTE_API_URL", "").strip(),
                photo_api_url=env.get("PHOTO_API_URL", "").strip(),
                live_port=int(env["LIVE_PORT"]) if env.get("LIVE_PORT", "").strip() else None,
                speech_server=_host_and_port(env.get("SPEECH_SERVER", "")),
                speech_quiet_hours=env.get("SPEECH_QUIET_HOURS", ""),
                speech_dir=env.get("SPEECH_DIR", "").strip(),
                aeroapi_key=env.get("AEROAPI_KEY", "").strip(),
                aeroapi_url=env.get("AEROAPI_URL", "").strip(),
                aeroapi_monthly_limit=int(env.get("AEROAPI_MONTHLY_LIMIT", "").strip() or 0),
                state_dir=env.get("STATE_DIR", "").strip(),
                mute_chime=_switch("MUTE_CHIME", env.get("MUTE_CHIME", "")),
                followed_file=env.get("FOLLOWED_FILE", "").strip(),
                followed_monthly_limit=int(env.get("FOLLOWED_MONTHLY_LIMIT", "").strip() or 0),
                air_ambulance_callsigns=_codes(env.get("AIR_AMBULANCE_CALLSIGNS", "")),
                police_callsigns=_codes(env.get("POLICE_CALLSIGNS", "")),
                quiet_hours_except=_kinds(env.get("QUIET_HOURS_EXCEPT", "")),
                home_country=env.get("HOME_COUNTRY", "").strip().upper(),
            )
        except ValueError as error:
            raise ConfigError(f"bad setting: {error}") from error


def _switch(name: str, value: str) -> bool:
    words = {"true": True, "yes": True, "on": True, "1": True, "false": False, "no": False, "off": False, "0": False, "": False}
    try:
        return words[value.strip().lower()]
    except KeyError:
        raise ValueError(f"{name} should be true or false, not {value!r}") from None


def _kinds(value: str) -> tuple[str, ...]:
    kinds = tuple(kind.strip().lower() for kind in value.split(",") if kind.strip())
    unknown = [kind for kind in kinds if kind not in KINDS]
    if unknown:
        raise ValueError(f"QUIET_HOURS_EXCEPT takes {' and '.join(KINDS)}, not {', '.join(unknown)}")
    return kinds


def _codes(value: str) -> tuple[str, ...]:
    """A comma separated list of operator codes, upper cased: "hle, xyz" is ("HLE", "XYZ")."""
    return tuple(code.strip().upper() for code in value.split(",") if code.strip())


def _host_and_port(value: str) -> tuple[str, int] | None:
    if not value.strip():
        return None
    host, _, port = value.strip().rpartition(":")
    if not host:
        raise ValueError(f"SPEECH_SERVER should be host:port, not {value!r}")
    return host, int(port)
