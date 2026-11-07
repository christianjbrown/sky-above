"""Builds everything the watcher needs from the settings, and holds the tunings it runs with."""

import logging
import pathlib
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from flights_watcher.announced import RememberedFlights
from flights_watcher.approach import ApproachFinder, ClosestApproach, LandsFirst, OverheadAndApproaching, SteeredIn
from flights_watcher.bound import DestinationBound, SameWay
from flights_watcher.budget import BudgetedHttp, MonthlyBudget, PricedByPath
from flights_watcher.caching import CachedOperatorNames, CachedPhotoLookup, CachedRouteLookup, RetryLater, TtlCache
from flights_watcher.cards import CardBuilder
from flights_watcher.chime import MutedLaunchDevice
from flights_watcher.chromecast import ListedChromecasts, PyChromecastDevice, planes_channel
from flights_watcher.clock import Clock
from flights_watcher.config import Settings
from flights_watcher.display import CastDevice, CastDisplay, CoolingOffDevice, Display, FanOutDisplay, LoggingDisplay, Stamped
from flights_watcher.emergency import (
    AltitudeBearsOut,
    DeclaredEmergency,
    EmergencyAlert,
    EmergencyLog,
    EmergencyMessages,
    FirstEmergencies,
    HeldEmergencies,
    SteepClimbOrDescent,
)
from flights_watcher.emergency_speech import EmergencyAnnouncer, EmergencyWording
from flights_watcher.estimate import (
    DepartureEstimator,
    EstimatedFollowedFlights,
    RecentBlockTimes,
    TurnaroundRule,
    TurnaroundsByType,
)
from flights_watcher.flightaware import AeroApiOperatorNames, AeroApiRouteLookup, OperatorNames
from flights_watcher.followed_card import FollowedCardBuilder
from flights_watcher.followed_list import FollowedListFile
from flights_watcher.followed_news import (
    AnnouncedFollowedCards,
    BeltChanged,
    Cancelled,
    DelayMoved,
    Diverted,
    FollowedAnnouncer,
    FollowedNews,
    GateChanged,
    Landed,
    LandingSoon,
    TookOff,
)
from flights_watcher.following import FollowedFlights, FollowTiming
from flights_watcher.heard import SpeechTiming
from flights_watcher.http import JsonHttp, UrllibJsonHttp
from flights_watcher.live import LatestCard, LiveServer
from flights_watcher.lookups import (
    AdsbdbRouteLookup,
    AirportTidier,
    NoPhotos,
    NoRoutes,
    PhotoLookup,
    PlanespottersPhotoLookup,
    RouteLookup,
    TidiedRoutes,
)
from flights_watcher.memory import (
    AllFresh,
    KeptRouteLookup,
    Memory,
    RememberedOperatorNames,
    RememberedRouteLookup,
    SameTimetable,
    SqliteAnswerStore,
    YoungerThan,
)
from flights_watcher.messages import PlanesMessageBuilder
from flights_watcher.naming import (
    AircraftNames,
    AirportCities,
    AirportCountries,
    AirportPlaces,
    FirstService,
    MilitaryService,
    NearestAirportCountry,
    Service,
    Services,
    SquawkServices,
)
from flights_watcher.paths import (
    CameOverhead,
    FirstFound,
    JsonPathStore,
    LearnedPaths,
    Likeness,
    MissedBefore,
    MissedIt,
    Observing,
    PathFinder,
    PathRecorder,
)
from flights_watcher.presence import Linger, MinimumShowing
from flights_watcher.priority import ServicesStay
from flights_watcher.rare import RareKinds
from flights_watcher.rotorcraft import KnownRotorcraft
from flights_watcher.schedule import QuietHours
from flights_watcher.schedules import AeroApiSchedules
from flights_watcher.sources import Tar1090AircraftSource
from flights_watcher.speech import (
    AirbusNumbersSaid,
    AnnouncementWording,
    Announcer,
    BoeingNumbersSaid,
    EndOfShowing,
    InterruptedByEmergency,
    QuietVoice,
    SaidAsWords,
    Silence,
    SpeechClips,
    SpokenArrival,
    SpokenWhereabouts,
    WyomingSpeech,
)
from flights_watcher.standby import FollowedStandby, NothingOnStandby
from flights_watcher.status import AllObservers, DailyTally, HeardSource, WatchStatus
from flights_watcher.watcher import ArrivalLog, Watcher
from flights_watcher.zone import Zone

USER_AGENT = "sky-above (personal Nest Hub plane display)"
LOOKUP_TTL_SECONDS = 6 * 60 * 60
LOOKUP_CACHE_ENTRIES = 2000
# How long a callsign whose route lookup failed waits before it is asked about again.
ROUTE_RETRY_SECONDS = 30
# Airline names hardly change, and each one asked for is a paid AeroAPI lookup.
OPERATOR_TTL_SECONDS = 30 * 24 * 60 * 60
# A callsign with nothing in the air yet may just be a plane whose take-off has not
# reached FlightAware, so it is asked about again sooner than a known route.
NO_ROUTE_TTL_SECONDS = 10 * 60
# Answers kept on disk in STATE_DIR. A route is trusted for a week, or until the
# timetables change; an airline's name for a year. Past that they are asked for again.
ANSWERS_FILE = "lookups.sqlite3"
ROUTE_KEPT_FRESH = timedelta(days=7)
OPERATOR_KEPT_FRESH = timedelta(days=365)
# Airlines that write their own flight numbers with the ICAO code: easyJet and its
# European and Swiss arms all sell and board as EZY, never U2, EC or DS.
ICAO_NUMBERED_AIRLINES = ("EZY", "EJU", "EZS")
# What AeroAPI charges for each kind of request the watcher makes, from the fee list at
# https://www.flightaware.com/commercial/aeroapi/. Each request asks for one page, and
# FlightAware charges by the page. Anything not listed is priced at the dearest fee
# on that list, so a new kind of request can only ever be overcounted.
AEROAPI_PRICES = (
    (r"/flights/[^/]+/position", Decimal("0.010")),
    (r"/flights/[^/]+", Decimal("0.005")),
    (r"/operators/[^/]+", Decimal("0.015")),
)
AEROAPI_UNLISTED_PRICE = Decimal("0.200")
CAST_RETRY_SECONDS = 30
# Airports whose city in the route services is not the one people would say, mostly
# because it is the town the airport stands in, and the airports of cities that have
# several, which are announced by name ("London Stansted", "Paris Orly") rather than city.
AIRPORT_CITIES = {
    "HEL": "Helsinki",
    "DLM": "Dalaman",
    "ACE": "Lanzarote",
    "RHO": "Rhodes",
    "FRA": "Frankfurt",
    "GOT": "Göteborg",
    **dict.fromkeys(("LHR", "LGW", "LCY", "STN", "LTN", "SEN"), "London"),
    **dict.fromkeys(("CDG", "ORY", "BVA"), "Paris"),
    **dict.fromkeys(("JFK", "LGA", "EWR"), "New York"),
    **dict.fromkeys(("IAD", "DCA"), "Washington"),
    **dict.fromkeys(("ORD", "MDW"), "Chicago"),
    **dict.fromkeys(("HND", "NRT"), "Tokyo"),
    **dict.fromkeys(("ICN", "GMP"), "Seoul"),
    **dict.fromkeys(("PVG", "SHA"), "Shanghai"),
    **dict.fromkeys(("PEK", "PKX"), "Beijing"),
    **dict.fromkeys(("BKK", "DMK"), "Bangkok"),
    **dict.fromkeys(("MXP", "LIN", "BGY"), "Milan"),
    **dict.fromkeys(("FCO", "CIA"), "Rome"),
    **dict.fromkeys(("IST", "SAW"), "Istanbul"),
    **dict.fromkeys(("SVO", "DME", "VKO"), "Moscow"),
    **dict.fromkeys(("ARN", "BMA", "NYO"), "Stockholm"),
    **dict.fromkeys(("OSL", "TRF"), "Oslo"),
    **dict.fromkeys(("GRU", "CGH"), "São Paulo"),
    **dict.fromkeys(("EZE", "AEP"), "Buenos Aires"),
}
NAMED_AIRPORTS = tuple(code for code, city in AIRPORT_CITIES.items() if list(AIRPORT_CITIES.values()).count(city) > 1)
# How long the Hub stays muted after a launch, so its start-up chime goes unheard.
CHIME_SECONDS = 3
SPEECH_TIMEOUT_SECONDS = 15
# How the announcement's timing goes, for saying where the plane will be when it is heard.
# Measured on the Pi: Piper reads about 13 characters a second and takes about a third of
# a clip's length to make it. A card takes about 5 seconds to launch, then the chime mute
# and the receiver's UNMUTE_SETTLE_MS; on a card already showing, the clip plays within a second.
SPOKEN_CHARS_PER_SECOND = 13
CLIP_MAKING_RATIO = 0.33
CAST_LAUNCH_SECONDS = 5
UNMUTE_SETTLE_SECONDS = 2
SHOWING_START_SECONDS = 1
SPEECH_CLIPS_KEPT = 50
# An announcement ends "It's overhead now." when the plane will be this close by the time
# it has been read out.
OVERHEAD_NOW_KM = 0.5
# Flights already announced, so one that drops back to second or leaves and returns stays quiet.
# Longer than any flight is in sight, so a plane is introduced once whatever happens.
ANNOUNCED_KEPT_FOR = timedelta(hours=6)
ANNOUNCED_FILE = "announced.json"
# Other planes are drawn on the map out to this far, which reaches past its edges
# however far away the plane on the card is. Only the nearest few dozen.
SURROUNDINGS_KM = 50
MAX_OTHER_PLANES = 40
# A plane further out whose straight line passes within the zone is shown and announced
# on its way in, once its line has held through the zone for this many looks (a second
# each) without its track turning more than this; a plane mid-turn sweeps its line across
# home without coming near. Slower than the speed is hovering or taxiing.
APPROACH_STEADY_POLLS = 5
APPROACH_STEADY_POLLS_PER_KM = 2
APPROACH_MAX_TURN_DEG = 3
APPROACH_MIN_SPEED_KT = 60
# Once counted, a plane stops counting if it turns enough that its line misses the zone by more than this.
APPROACH_WANDER_KM = 0.3
# Further out than this, a plane coming down below this height is being steered in to land.
STEERED_BELOW_FT = 10000
STEERED_BEYOND_KM = 10
DESCENDING_FPM = -300
# Planes that came within the zone teach the watcher the path they flew there, from as far
# out as this, a point every couple of seconds. A plane is on one of those paths when it is
# this near a point on it in place, height and heading. Once it has been on the paths of two
# earlier planes for three looks in a row it is on its way, turning or not, and is given the
# time they took from there. A path is forgotten after a few months, as routes change, and
# only the most recent are kept.
PATH_KM = 25
PATH_EVERY_SECONDS = 2
PATH_GONE_SECONDS = 60
PATH_LIKENESS = Likeness(within_km=0.5, within_ft=1500, within_deg=15)
PATH_MIN_PLANES = 2
PATH_HELD_POLLS = 3
PATHS_KEPT = 60
PATH_KEPT_FOR = timedelta(days=90)
PATHS_FILE = "paths.json"
# Two planes that looked on their way from the same spot and missed, and none that came over.
MISSES_MIN = 2
MISSES_FILE = "missed.json"
# Planes bound within this many degrees of each other fly the same departure route.
BOUND_WITHIN = SameWay(within_deg=30)
# A plane on its way due overhead within this long takes the card at once, rather than
# waiting for the plane before to finish, so there is still time to launch and announce it.
APPROACH_DUE_SECONDS = 45
# Followed flights show from four hours before they are due out until half an hour after
# they reach the gate. FlightAware is asked every ten minutes while one is on, every five
# in its last hour before leaving, and for its position in the air every three, unless our
# own receiver can see it. Each flight costs roughly 100 lookups.
FOLLOW_TIMING = FollowTiming(
    lead=timedelta(hours=4),
    tail=timedelta(minutes=30),
    before_showing_every=6 * 60 * 60,
    hours_to_go_every=10 * 60,
    last_hour_every=5 * 60,
    under_way_every=10 * 60,
    earlier_leg_every=10 * 60,
    position_every=3 * 60,
    not_found_every=30 * 60,
)
# How far behind its timetable a leg has to be before it is called late.
LATE_MINUTES = 10
# A followed flight's delay is announced again each time it moves by this much, and once
# more when it is this close to landing. Its news is handed to the card for long enough
# to cover a launch.
DELAY_STEP_MINUTES = 10
LANDING_SOON = timedelta(minutes=20)
FOLLOWED_NEWS_KEPT_SECONDS = 60
# The least time a plane needs on the ground between flights, by size, for our own
# estimate of when a followed flight can leave. Anything not listed is a narrow-body.
TURNAROUNDS = TurnaroundsByType(
    [
        TurnaroundRule(("A33", "A34", "A35", "A38", "B74", "B76", "B77", "B78", "B79"), timedelta(minutes=75)),
        TurnaroundRule(("E1", "E7", "CRJ", "AT4", "AT7", "DH8", "SF3", "F70", "J41"), timedelta(minutes=25)),
    ],
    timedelta(minutes=35),
)
# How long a flight number's recent gate-to-gate times are kept before being asked for again.
BLOCK_TIMES_KEEP_SECONDS = 6 * 60 * 60
FOLLOWED_BUDGET_FILE = "followed-aeroapi.json"
# A plane in the zone this close to its nearest point to home is announced without a time.
OVERHEAD_SOON_SECONDS = 10
# A plane in an emergency counts once its squawk or emergency status has held for this
# many looks, or its climb or descent, steeper than any departure or arrival, for this
# many; it is over once this long has passed without a look that showed it. A plane can
# start its descent at well over the steep rate for a few seconds, while a real emergency
# descent keeps it up for minutes, so the steep rate has to hold for most of a minute.
EMERGENCY_HELD_POLLS = 3
STEEP_HELD_POLLS = 45
EMERGENCY_CLEAR_SECONDS = 60
STEEP_DESCENT_FPM = 6000
STEEP_CLIMB_FPM = 8000
# A steep rate only counts while the altitude has moved at least this share of what the
# rate says it should have.
STEEP_ALTITUDE_SHARE = 0.5
EMERGENCIES_ANNOUNCED_REMEMBERED = 20
# An air ambulance, police or military aircraft that comes into the zone keeps the card until it is
# further than this from home.
SERVICES_KEPT = ("ambulance", "police", "military")
SERVICE_HOLD_KM = 5
# Words in aircraft names the voice gets wrong, and how to write them so it says them
# right: MAX is said as a word, not spelled out, and ERJ is spelled out, not said as one.
SAID_AS_WORDS = {"MAX": "Max", "ERJ": "E R J"}
# Where nginx serves the clip folder, relative to the receiver page.
SPEECH_URL_PREFIX = "speech/"


@dataclass(frozen=True)
class Lookups:
    routes: RouteLookup
    # Routes for planes that are not on the card, which must not cost a lookup.
    known_routes: RouteLookup
    photos: PhotoLookup
    operator_names: OperatorNames | None
    airport_tidiers: Sequence[AirportTidier]


@dataclass(frozen=True)
class Voices:
    planes: QuietVoice | Silence
    followed: QuietVoice | Silence
    emergency: EmergencyAnnouncer | Silence


@dataclass(frozen=True)
class App:
    watcher: Watcher
    display: Display
    live_server: LiveServer | None
    status: WatchStatus


def build(settings: Settings, clock: Clock, logger: logging.Logger) -> App:
    """Everything the watcher needs, from the settings. Nothing is asked of the network yet."""
    http = UrllibJsonHttp(USER_AGENT, timeout_seconds=5)
    found = lookups(settings, http, clock, logger)
    # Let through quiet hours, as rare enough to be worth waking up for.
    rare = RareKinds(settings.quiet_hours_except)
    voice = voices(settings, clock, rare, logger)
    status = WatchStatus(clock)
    display, live_server = display_for(settings, status, clock, logger)
    display = FanOutDisplay([display, EndOfShowing(voice.planes), InterruptedByEmergency(voice.planes)])
    watcher = watcher_for(
        settings, http, found, voice, display, followed_standby(settings, found, voice, clock, logger), rare, status, clock, logger
    )
    return App(watcher, display, live_server, status)


def lookups(settings: Settings, http: JsonHttp, clock: Clock, logger: logging.Logger) -> Lookups:
    """Routes and airline names from AeroAPI when there is a key, else from adsbdb, and photos.
    AeroAPI is paid by the lookup, so only planes on the card are asked about; anything
    else goes by the routes already kept. adsbdb is free, so it answers for both."""
    routes: RouteLookup = NoRoutes()
    known_routes: RouteLookup | None = None
    operator_names: OperatorNames | None = None
    if settings.aeroapi_key:
        aeroapi = BudgetedHttp(
            UrllibJsonHttp(USER_AGENT, timeout_seconds=5, headers={"x-apikey": settings.aeroapi_key}),
            MonthlyBudget(settings.aeroapi_monthly_dollars, pathlib.Path(settings.state_dir) / "aeroapi.json", clock),
            PricedByPath(settings.aeroapi_url, AEROAPI_PRICES, AEROAPI_UNLISTED_PRICE),
        )
        answers = str(pathlib.Path(settings.state_dir) / ANSWERS_FILE)
        known_routes = KeptRouteLookup(SqliteAnswerStore(answers, "route", logger))
        operator_names = CachedOperatorNames(
            RememberedOperatorNames(
                AeroApiOperatorNames(settings.aeroapi_url, aeroapi),
                Memory(SqliteAnswerStore(answers, "operator", logger), YoungerThan(OPERATOR_KEPT_FRESH), clock, logger),
            ),
            TtlCache(clock, OPERATOR_TTL_SECONDS, LOOKUP_CACHE_ENTRIES),
        )
        routes = CachedRouteLookup(
            RememberedRouteLookup(
                AeroApiRouteLookup(settings.aeroapi_url, aeroapi, operator_names, ICAO_NUMBERED_AIRLINES),
                Memory(
                    SqliteAnswerStore(answers, "route", logger),
                    AllFresh([YoungerThan(ROUTE_KEPT_FRESH), SameTimetable()]),
                    clock,
                    logger,
                ),
            ),
            TtlCache(clock, LOOKUP_TTL_SECONDS, LOOKUP_CACHE_ENTRIES, NO_ROUTE_TTL_SECONDS),
        )
    elif settings.route_api_url:
        routes = CachedRouteLookup(
            AdsbdbRouteLookup(settings.route_api_url, http), TtlCache(clock, LOOKUP_TTL_SECONDS, LOOKUP_CACHE_ENTRIES)
        )
    airport_tidiers: list[AirportTidier] = [AirportCities(AIRPORT_CITIES), AirportCountries.bundled(), AirportPlaces.bundled()]
    photos: PhotoLookup = NoPhotos()
    if settings.photo_api_url:
        photos = CachedPhotoLookup(
            PlanespottersPhotoLookup(settings.photo_api_url, http), TtlCache(clock, LOOKUP_TTL_SECONDS, LOOKUP_CACHE_ENTRIES)
        )
    tidied = TidiedRoutes(RetryLater(routes, clock, ROUTE_RETRY_SECONDS), airport_tidiers)
    known = TidiedRoutes(known_routes, airport_tidiers) if known_routes else tidied
    return Lookups(tidied, known, photos, operator_names, airport_tidiers)


def voices(settings: Settings, clock: Clock, rare: RareKinds, logger: logging.Logger) -> Voices:
    """Spoken announcements when there is a speech server, silence otherwise."""
    if settings.speech_server is None:
        return Voices(Silence(), Silence(), Silence())
    host, port = settings.speech_server
    launch_start = CAST_LAUNCH_SECONDS + (CHIME_SECONDS + UNMUTE_SETTLE_SECONDS if settings.mute_chime else 0)
    clips = SpeechClips(
        pathlib.Path(settings.speech_dir),
        SPEECH_URL_PREFIX,
        SPEECH_CLIPS_KEPT,
        SaidAsWords(BoeingNumbersSaid(AirbusNumbersSaid(WyomingSpeech(host, port, SPEECH_TIMEOUT_SECONDS))), SAID_AS_WORDS),
    )
    wording = AnnouncementWording(NAMED_AIRPORTS, SpokenWhereabouts(settings.home))
    announcer = Announcer(
        wording,
        SpokenArrival(settings.home, OVERHEAD_NOW_KM),
        SpeechTiming(SPOKEN_CHARS_PER_SECOND, CLIP_MAKING_RATIO, launch_start, SHOWING_START_SECONDS),
        clips,
        RememberedFlights(pathlib.Path(settings.state_dir) / ANNOUNCED_FILE, ANNOUNCED_KEPT_FOR, clock, logger),
        logger,
    )
    quiet_hours = QuietHours.parse(settings.speech_quiet_hours)
    return Voices(
        QuietVoice(announcer, quiet_hours, clock, rare),
        QuietVoice(FollowedAnnouncer(clips, FOLLOWED_NEWS_KEPT_SECONDS, clock, logger), quiet_hours, clock, rare),
        # Heard at any hour.
        EmergencyAnnouncer(EmergencyWording(wording, SpokenWhereabouts(settings.home)), clips, EMERGENCIES_ANNOUNCED_REMEMBERED, logger),
    )


def followed_standby(
    settings: Settings, found: Lookups, voice: Voices, clock: Clock, logger: logging.Logger
) -> FollowedStandby | NothingOnStandby:
    """Followed flights need AeroAPI and a list of them; without both, nothing waits on standby."""
    if found.operator_names is None or not settings.followed_file:
        return NothingOnStandby()
    # Its own monthly cap, so a busy sky cannot use up the lookups a followed flight needs.
    followed_http = BudgetedHttp(
        UrllibJsonHttp(USER_AGENT, timeout_seconds=5, headers={"x-apikey": settings.aeroapi_key}),
        MonthlyBudget(settings.followed_monthly_dollars, pathlib.Path(settings.state_dir) / FOLLOWED_BUDGET_FILE, clock),
        PricedByPath(settings.aeroapi_url, AEROAPI_PRICES, AEROAPI_UNLISTED_PRICE),
    )
    schedules = AeroApiSchedules(settings.aeroapi_url, followed_http)
    timezone = ZoneInfo(settings.timezone)
    return FollowedStandby(
        EstimatedFollowedFlights(
            FollowedFlights(FollowedListFile(pathlib.Path(settings.followed_file), logger), schedules, FOLLOW_TIMING, clock, logger),
            DepartureEstimator(RecentBlockTimes(schedules, BLOCK_TIMES_KEEP_SECONDS, clock, logger), TURNAROUNDS, clock),
        ),
        AnnouncedFollowedCards(
            FollowedCardBuilder(settings.timezone, found.airport_tidiers, found.operator_names, LATE_MINUTES, logger),
            FollowedNews(
                [
                    Cancelled(),
                    Diverted(),
                    DelayMoved(LATE_MINUTES, DELAY_STEP_MINUTES, timezone),
                    GateChanged(),
                    TookOff(timezone),
                    LandingSoon(LANDING_SOON),
                    Landed(),
                    BeltChanged(),
                ],
                clock,
                logger,
            ),
            voice.followed,
        ),
    )


def display_for(settings: Settings, status: WatchStatus, clock: Clock, logger: logging.Logger) -> tuple[Display, LiveServer | None]:
    """The Cast device when there is an app to cast, else the log; and the live page if it has a port."""
    display: Display
    if settings.cast_app_id:
        chromecast = PyChromecastDevice(
            ListedChromecasts(settings.cast_device_name, settings.cast_timeout_seconds),
            planes_channel(settings.cast_app_id),
            settings.cast_timeout_seconds,
            logger,
        )
        hub: CastDevice = MutedLaunchDevice(chromecast, CHIME_SECONDS, time.sleep) if settings.mute_chime else chromecast
        display = CastDisplay(CoolingOffDevice(hub, clock, CAST_RETRY_SECONDS, logger), settings.cast_app_id, logger)
    else:
        logger.info("CAST_APP_ID is empty, so planes are logged rather than cast")
        display = LoggingDisplay(logger)
    live_server: LiveServer | None = None
    if settings.live_port is not None:
        latest = LatestCard()
        # All interfaces, so the receiver container can reach it through the host.
        live_server = LiveServer({"/planes.json": latest, "/status.json": status}, "0.0.0.0", settings.live_port, logger)  # noqa: S104
        display = FanOutDisplay([display, latest])
    # Lets the card leave the flag off places in home's own country. Near a border the
    # nearest airport can be in the next country, so HOME_COUNTRY says for sure.
    home_country = settings.home_country or NearestAirportCountry.bundled().of(settings.home)
    if not settings.home_country:
        logger.info("HOME_COUNTRY is empty, so going by the nearest airport: %s", home_country)
    return Stamped(display, {"homeCountry": home_country}), live_server


def watcher_for(
    settings: Settings,
    http: JsonHttp,
    found: Lookups,
    voice: Voices,
    display: Display,
    standby: FollowedStandby | NothingOnStandby,
    rare: RareKinds,
    status: WatchStatus,
    clock: Clock,
    logger: logging.Logger,
) -> Watcher:
    zone = Zone(settings.home, settings.radius_km)
    services = FirstService(
        [
            Services(
                {code: Service("Air ambulance", "ambulance") for code in settings.air_ambulance_callsigns}
                | {code: Service("Police", "police") for code in settings.police_callsigns}
            ),
            SquawkServices(
                {code: Service("Air ambulance", "ambulance") for code in settings.air_ambulance_squawks}
                | {code: Service("Police", "police") for code in settings.police_squawks}
            ),
            MilitaryService(),
        ]
    )
    closest = ClosestApproach(settings.home, APPROACH_MIN_SPEED_KT)
    paths = LearnedPaths(
        JsonPathStore(pathlib.Path(settings.state_dir) / PATHS_FILE, logger), PATH_LIKENESS, PATHS_KEPT, PATH_KEPT_FOR, clock
    )
    bound = DestinationBound(found.known_routes, settings.home, logger)
    misses = LearnedPaths(
        JsonPathStore(pathlib.Path(settings.state_dir) / MISSES_FILE, logger), PATH_LIKENESS, PATHS_KEPT, PATH_KEPT_FOR, clock
    )
    recorder = PathRecorder(
        [CameOverhead(paths, bound, zone.radius_km, logger), MissedIt(misses, bound, zone.radius_km, logger)],
        closest,
        settings.home,
        zone.radius_km,
        PATH_KM,
        PATH_EVERY_SECONDS,
        PATH_GONE_SECONDS,
        clock,
    )
    approaching = FirstFound(
        [
            ApproachFinder(
                closest,
                settings.home,
                zone.radius_km,
                APPROACH_STEADY_POLLS,
                APPROACH_STEADY_POLLS_PER_KM,
                APPROACH_MAX_TURN_DEG,
                APPROACH_WANDER_KM,
                [
                    LandsFirst(),
                    SteeredIn(STEERED_BELOW_FT, STEERED_BEYOND_KM, DESCENDING_FPM),
                    MissedBefore(misses, paths, bound, BOUND_WITHIN, MISSES_MIN),
                ],
            ),
            PathFinder(paths, bound, BOUND_WITHIN, settings.home, zone.radius_km, PATH_MIN_PLANES, PATH_HELD_POLLS),
        ]
    )
    cards = CardBuilder(found.routes, found.photos, AircraftNames(), services, logger)

    def planes_message(speech: QuietVoice | Silence) -> PlanesMessageBuilder:
        return PlanesMessageBuilder(
            cards,
            speech,
            settings.home,
            zone.radius_km,
            settings.max_cards,
            Zone(settings.home, SURROUNDINGS_KM),
            MAX_OTHER_PLANES,
            services,
        )

    emergencies = FirstEmergencies(
        [
            HeldEmergencies(DeclaredEmergency(), settings.home, EMERGENCY_HELD_POLLS, EMERGENCY_CLEAR_SECONDS, clock),
            HeldEmergencies(
                AltitudeBearsOut(SteepClimbOrDescent(STEEP_DESCENT_FPM, STEEP_CLIMB_FPM), clock, STEEP_ALTITUDE_SHARE),
                settings.home,
                STEEP_HELD_POLLS,
                EMERGENCY_CLEAR_SECONDS,
                clock,
            ),
        ]
    )
    return Watcher(
        source=HeardSource(KnownRotorcraft.bundled(Tar1090AircraftSource(settings.aircraft_url, http)), status),
        zone=ServicesStay(
            OverheadAndApproaching(zone, Observing(recorder, approaching), closest, OVERHEAD_SOON_SECONDS),
            services,
            SERVICES_KEPT,
            settings.home,
            SERVICE_HOLD_KM,
        ),
        messages=planes_message(voice.planes),
        display=display,
        quiet_hours=QuietHours.parse(settings.quiet_hours),
        linger=MinimumShowing(Linger(settings.linger_seconds, clock), settings.card_min_seconds, clock),
        arrivals=AllObservers([ArrivalLog(logger), DailyTally(status, clock, logger)]),
        clock=clock,
        standby=standby,
        due_seconds=APPROACH_DUE_SECONDS,
        surroundings=Zone(settings.home, SURROUNDINGS_KM),
        rare=rare,
        emergencies=EmergencyAlert(emergencies, EmergencyMessages(planes_message(Silence()), voice.emergency), EmergencyLog(logger)),
    )
