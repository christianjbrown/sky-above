"""Settings, all from the environment that docker-compose.yml hands the container."""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from flights_watcher.geo import Location
from flights_watcher.rare import KINDS
from flights_watcher.schedule import QuietHours

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
# ambulance or police callsigns to pick out. AEROAPI_PRICES and AEROAPI_UNLISTED_PRICE
# may only be empty without an AEROAPI_KEY, since a key spends money they count.
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
    "AEROAPI_MONTHLY_DOLLARS",
    "AEROAPI_PRICES",
    "AEROAPI_UNLISTED_PRICE",
    "STATE_DIR",
    "MUTE_CHIME",
    "FOLLOWED_FILE",
    "FOLLOWED_MONTHLY_DOLLARS",
    "AIR_AMBULANCE_CALLSIGNS",
    "POLICE_CALLSIGNS",
    "QUIET_HOURS_EXCEPT",
    "HOME_COUNTRY",
    "NOTABLE_AIRCRAFT_URL",
    "NOTABLE_CATEGORIES",
    "NOTABLE_NAMES_FILE",
    "PORTRAIT_API_URL",
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
    # Dollars a month on AeroAPI, for planes overhead and for followed flights. Each
    # lookup past the free credit is charged, so the two are best kept inside it together.
    aeroapi_monthly_dollars: Decimal
    # What AeroAPI charges for one request to each path below aeroapi_url, where * is any
    # one part of the path, and for a request to anywhere else.
    aeroapi_prices: tuple[tuple[str, Decimal], ...]
    aeroapi_unlisted_price: Decimal
    state_dir: str
    mute_chime: bool
    followed_file: str
    followed_monthly_dollars: Decimal
    # The operator codes at the front of these services' callsigns, such as HLE.
    air_ambulance_callsigns: tuple[str, ...]
    police_callsigns: tuple[str, ...]
    # The squawks set aside for these services, each four octal digits.
    air_ambulance_squawks: tuple[str, ...]
    police_squawks: tuple[str, ...]
    # Kinds of aircraft let through both kinds of quiet hours: helicopters, military.
    quiet_hours_except: tuple[str, ...]
    # Two-letter country code, or empty to go by the nearest airport.
    home_country: str
    # Where to fetch plane-alert-db's list of notable aircraft, or empty for none.
    notable_aircraft_url: str
    # Which of its categories to name the owners of.
    notable_categories: tuple[str, ...]
    # A file of registrations and who each belongs to, or empty for none.
    notable_names_file: str
    # Where pictures of notable aircraft's owners come from (Wikipedia's REST API), or empty for none.
    portrait_api_url: str

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "Settings":
        missing = [key for key in REQUIRED_KEYS if not env.get(key, "").strip()]
        if missing:
            raise ConfigError(f"missing settings: {', '.join(missing)}")
        try:
            settings = cls(
                aircraft_url=env["AIRCRAFT_URL"],
                home=Location(float(env["HOME_LAT"]), float(env["HOME_LON"])),
                radius_km=float(env["ZONE_RADIUS_KM"]),
                linger_seconds=float(env["LINGER_SECONDS"]),
                card_min_seconds=float(env["CARD_MIN_SECONDS"]),
                poll_seconds=float(env["POLL_SECONDS"]),
                max_cards=int(env["MAX_CARDS"]),
                quiet_hours=_hours("QUIET_HOURS", env.get("QUIET_HOURS", "")),
                timezone=env["TZ"],
                cast_device_name=env["CAST_DEVICE_NAME"],
                cast_app_id=env.get("CAST_APP_ID", "").strip(),
                cast_timeout_seconds=float(env["CAST_TIMEOUT_SECONDS"]),
                route_api_url=env.get("ROUTE_API_URL", "").strip(),
                photo_api_url=env.get("PHOTO_API_URL", "").strip(),
                live_port=int(env["LIVE_PORT"]) if env.get("LIVE_PORT", "").strip() else None,
                speech_server=_host_and_port(env.get("SPEECH_SERVER", "")),
                speech_quiet_hours=_hours("SPEECH_QUIET_HOURS", env.get("SPEECH_QUIET_HOURS", "")),
                speech_dir=env.get("SPEECH_DIR", "").strip(),
                aeroapi_key=env.get("AEROAPI_KEY", "").strip(),
                aeroapi_url=env.get("AEROAPI_URL", "").strip(),
                aeroapi_monthly_dollars=_dollars("AEROAPI_MONTHLY_DOLLARS", env.get("AEROAPI_MONTHLY_DOLLARS", "")),
                aeroapi_prices=_prices(env.get("AEROAPI_PRICES", "")),
                aeroapi_unlisted_price=_dollars("AEROAPI_UNLISTED_PRICE", env.get("AEROAPI_UNLISTED_PRICE", "")),
                state_dir=env.get("STATE_DIR", "").strip(),
                mute_chime=_switch("MUTE_CHIME", env.get("MUTE_CHIME", "")),
                followed_file=env.get("FOLLOWED_FILE", "").strip(),
                followed_monthly_dollars=_dollars("FOLLOWED_MONTHLY_DOLLARS", env.get("FOLLOWED_MONTHLY_DOLLARS", "")),
                air_ambulance_callsigns=_codes(env.get("AIR_AMBULANCE_CALLSIGNS", "")),
                police_callsigns=_codes(env.get("POLICE_CALLSIGNS", "")),
                air_ambulance_squawks=_squawks(env.get("AIR_AMBULANCE_SQUAWKS", "")),
                police_squawks=_squawks(env.get("POLICE_SQUAWKS", "")),
                quiet_hours_except=_kinds(env.get("QUIET_HOURS_EXCEPT", "")),
                home_country=env.get("HOME_COUNTRY", "").strip().upper(),
                notable_aircraft_url=env.get("NOTABLE_AIRCRAFT_URL", "").strip(),
                notable_categories=tuple(name.strip() for name in env.get("NOTABLE_CATEGORIES", "").split(",") if name.strip()),
                notable_names_file=env.get("NOTABLE_NAMES_FILE", "").strip(),
                portrait_api_url=env.get("PORTRAIT_API_URL", "").strip(),
            )
            if settings.aeroapi_key and not (settings.aeroapi_prices and env.get("AEROAPI_UNLISTED_PRICE", "").strip()):
                raise ValueError("an AEROAPI_KEY needs AEROAPI_PRICES and AEROAPI_UNLISTED_PRICE to count what it spends")
        except ValueError as error:
            raise ConfigError(f"bad setting: {error}") from error
        return settings


def _switch(name: str, value: str) -> bool:
    words = {"true": True, "yes": True, "on": True, "1": True, "false": False, "no": False, "off": False, "0": False, "": False}
    try:
        return words[value.strip().lower()]
    except KeyError:
        raise ValueError(f"{name} should be true or false, not {value!r}") from None


def _dollars(name: str, value: str) -> Decimal:
    """An amount of money like 4 or 2.50, where empty is nothing, so no paid lookups at all."""
    try:
        amount = Decimal(value.strip() or "0")
    except InvalidOperation:
        raise ValueError(f"{name} should be an amount of dollars, not {value!r}") from None
    if not amount.is_finite() or amount < 0:
        raise ValueError(f"{name} should be an amount of dollars, not {value!r}")
    return amount


def _prices(value: str) -> tuple[tuple[str, Decimal], ...]:
    """Comma separated path=dollars pairs: "flights/*=0.005, operators/*=0.015"."""
    prices: list[tuple[str, Decimal]] = []
    for item in (part.strip() for part in value.split(",")):
        if not item:
            continue
        path, equals, amount = item.partition("=")
        if not equals or not path.strip(" /"):
            raise ValueError(f"AEROAPI_PRICES takes path=dollars pairs, not {item!r}")
        prices.append((path.strip(" /"), _dollars("AEROAPI_PRICES", amount)))
    return tuple(prices)


def _hours(name: str, value: str) -> str:
    """Checked here so a mistyped schedule stops the watcher at start-up, not mid-card."""
    try:
        QuietHours.parse(value)
    except ValueError as error:
        raise ValueError(f"{name}: {error}") from None
    return value


def _kinds(value: str) -> tuple[str, ...]:
    kinds = tuple(kind.strip().lower() for kind in value.split(",") if kind.strip())
    unknown = [kind for kind in kinds if kind not in KINDS]
    if unknown:
        raise ValueError(f"QUIET_HOURS_EXCEPT takes {' and '.join(KINDS)}, not {', '.join(unknown)}")
    return kinds


def _codes(value: str) -> tuple[str, ...]:
    """A comma separated list of operator codes, upper cased: "hle, xyz" is ("HLE", "XYZ")."""
    return tuple(code.strip().upper() for code in value.split(",") if code.strip())


def _squawks(value: str) -> tuple[str, ...]:
    """A comma separated list of squawks and ranges of them: "0032, 0041-0047" is 0032
    and 0041 to 0047. Squawks are octal, so 0047 is followed by 0050."""
    found: list[str] = []
    for item in value.split(","):
        first, _, last = item.strip().partition("-")
        if not first:
            continue
        start, end = _squawk(first), _squawk(last or first)
        if end < start:
            raise ValueError(f"squawk range {item.strip()} runs backwards")
        found.extend(f"{code:04o}" for code in range(start, end + 1))
    return tuple(found)


def _squawk(text: str) -> int:
    code = text.strip()
    if len(code) != 4 or any(digit not in "01234567" for digit in code):
        raise ValueError(f"{code} is not a squawk")
    return int(code, 8)


def _host_and_port(value: str) -> tuple[str, int] | None:
    if not value.strip():
        return None
    host, _, port = value.strip().rpartition(":")
    if not host:
        raise ValueError(f"SPEECH_SERVER should be host:port, not {value!r}")
    return host, int(port)
