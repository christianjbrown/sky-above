"""Builds everything the watcher needs from the settings and the tunings it runs with."""

import logging
import pathlib
import time
from collections.abc import Sequence
from dataclasses import dataclass
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
    TurnaroundsByType,
)
from flights_watcher.faces import FaceCrops
from flights_watcher.files import KeptFiles
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
from flights_watcher.following import FollowedFlights
from flights_watcher.heard import SpeechTiming
from flights_watcher.http import JsonHttp, UrllibBytesHttp, UrllibJsonHttp, UrllibTextHttp
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
from flights_watcher.notable import (
    InBackground,
    LocalText,
    MirroredText,
    NotableAircraft,
    NotableFinder,
    NoText,
    OwnedCards,
    ThreadStarter,
    owner_names,
    plane_alert_table,
)
from flights_watcher.opencv import YUNET_MODEL, OpenCvPictures, YuNetFaces
from flights_watcher.paths import (
    CameOverhead,
    FirstFound,
    JsonPathStore,
    LearnedPaths,
    MissedBefore,
    MissedIt,
    Observing,
    PathFinder,
    PathRecorder,
)
from flights_watcher.portraits import CachedPortraits, FirstPortrait, LocalPortraits, PortraitLookup, WikipediaPortraits
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
from flights_watcher.tuning import Tuning
from flights_watcher.watcher import ArrivalLog, Watcher
from flights_watcher.zone import Zone


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


def build(settings: Settings, tuning: Tuning, clock: Clock, logger: logging.Logger) -> App:
    """Everything the watcher needs, from the settings. Nothing is asked of the network yet."""
    http = UrllibJsonHttp(tuning.user_agent, timeout_seconds=tuning.http_timeout_seconds)
    found = lookups(settings, tuning, http, clock, logger)
    # Let through quiet hours, as rare enough to be worth waking up for.
    rare = RareKinds(settings.quiet_hours_except)
    voice = voices(settings, tuning, clock, rare, logger)
    status = WatchStatus(clock)
    display, live_server = display_for(settings, tuning, status, clock, logger)
    display = FanOutDisplay([display, EndOfShowing(voice.planes), InterruptedByEmergency(voice.planes)])
    watcher = watcher_for(
        settings,
        tuning,
        http,
        found,
        voice,
        display,
        followed_standby(settings, tuning, found, voice, clock, logger),
        rare,
        status,
        clock,
        logger,
    )
    return App(watcher, display, live_server, status)


def lookups(settings: Settings, tuning: Tuning, http: JsonHttp, clock: Clock, logger: logging.Logger) -> Lookups:
    """Routes and airline names from AeroAPI when there is a key, else from adsbdb, and photos.
    AeroAPI is paid by the lookup, so only planes on the card are asked about; anything
    else goes by the routes already kept. adsbdb is free, so it answers for both."""
    routes: RouteLookup = NoRoutes()
    known_routes: RouteLookup | None = None
    operator_names: OperatorNames | None = None
    if settings.aeroapi_key:
        aeroapi = BudgetedHttp(
            UrllibJsonHttp(tuning.user_agent, timeout_seconds=tuning.http_timeout_seconds, headers={"x-apikey": settings.aeroapi_key}),
            MonthlyBudget(settings.aeroapi_monthly_dollars, pathlib.Path(settings.state_dir) / tuning.aeroapi_budget_file, clock),
            PricedByPath(settings.aeroapi_url, settings.aeroapi_prices, settings.aeroapi_unlisted_price),
        )
        answers = str(pathlib.Path(settings.state_dir) / tuning.answers_file)
        known_routes = KeptRouteLookup(SqliteAnswerStore(answers, "route", logger))
        operator_names = CachedOperatorNames(
            RememberedOperatorNames(
                AeroApiOperatorNames(settings.aeroapi_url, aeroapi),
                Memory(SqliteAnswerStore(answers, "operator", logger), YoungerThan(tuning.operator_kept_fresh), clock, logger),
            ),
            TtlCache(clock, tuning.operator_ttl_seconds, tuning.lookup_cache_entries),
        )
        routes = CachedRouteLookup(
            RememberedRouteLookup(
                AeroApiRouteLookup(settings.aeroapi_url, aeroapi, operator_names, tuning.icao_numbered_airlines),
                Memory(
                    SqliteAnswerStore(answers, "route", logger),
                    AllFresh([YoungerThan(tuning.route_kept_fresh), SameTimetable()]),
                    clock,
                    logger,
                ),
            ),
            TtlCache(clock, tuning.lookup_ttl_seconds, tuning.lookup_cache_entries, tuning.no_route_ttl_seconds),
        )
    elif settings.route_api_url:
        routes = CachedRouteLookup(
            AdsbdbRouteLookup(settings.route_api_url, http), TtlCache(clock, tuning.lookup_ttl_seconds, tuning.lookup_cache_entries)
        )
    airport_tidiers: list[AirportTidier] = [AirportCities(tuning.airport_cities), AirportCountries.bundled(), AirportPlaces.bundled()]
    photos: PhotoLookup = NoPhotos()
    if settings.photo_api_url:
        photos = CachedPhotoLookup(
            PlanespottersPhotoLookup(settings.photo_api_url, http), TtlCache(clock, tuning.lookup_ttl_seconds, tuning.lookup_cache_entries)
        )
    tidied = TidiedRoutes(RetryLater(routes, clock, tuning.route_retry_seconds), airport_tidiers)
    known = TidiedRoutes(known_routes, airport_tidiers) if known_routes else tidied
    return Lookups(tidied, known, photos, operator_names, airport_tidiers)


# Announcement clips are WAVs, which is what Piper makes and the receiver's /speech/ serves.
SPEECH_FILES = ".wav"


def voices(settings: Settings, tuning: Tuning, clock: Clock, rare: RareKinds, logger: logging.Logger) -> Voices:
    """Spoken announcements when there is a speech server, silence otherwise."""
    if settings.speech_server is None:
        return Voices(Silence(), Silence(), Silence())
    host, port = settings.speech_server
    launch_start = tuning.cast_launch_seconds + (tuning.chime_seconds + tuning.unmute_settle_seconds if settings.mute_chime else 0)
    clips = SpeechClips(
        KeptFiles(pathlib.Path(settings.speech_dir), tuning.speech_url_prefix, tuning.speech_clips_kept, SPEECH_FILES),
        SaidAsWords(BoeingNumbersSaid(AirbusNumbersSaid(WyomingSpeech(host, port, tuning.speech_timeout_seconds))), tuning.said_as_words),
    )
    wording = AnnouncementWording(tuning.named_airports, SpokenWhereabouts(settings.home))
    announcer = Announcer(
        wording,
        SpokenArrival(settings.home, tuning.overhead_now_km),
        SpeechTiming(tuning.spoken_chars_per_second, tuning.clip_making_ratio, launch_start, tuning.showing_start_seconds),
        clips,
        RememberedFlights(pathlib.Path(settings.state_dir) / tuning.announced_file, tuning.announced_kept_for, clock, logger),
        logger,
    )
    quiet_hours = QuietHours.parse(settings.speech_quiet_hours)
    return Voices(
        QuietVoice(announcer, quiet_hours, clock, rare),
        QuietVoice(FollowedAnnouncer(clips, tuning.followed_news_kept_seconds, clock, logger), quiet_hours, clock, rare),
        # Heard at any hour.
        EmergencyAnnouncer(
            EmergencyWording(wording, SpokenWhereabouts(settings.home)), clips, tuning.emergencies_announced_remembered, logger
        ),
    )


def followed_standby(
    settings: Settings, tuning: Tuning, found: Lookups, voice: Voices, clock: Clock, logger: logging.Logger
) -> FollowedStandby | NothingOnStandby:
    """Followed flights need AeroAPI and a list of them; without both, nothing waits on standby."""
    if found.operator_names is None or not settings.followed_file:
        return NothingOnStandby()
    # Its own monthly cap, so a busy sky cannot use up the lookups a followed flight needs.
    followed_http = BudgetedHttp(
        UrllibJsonHttp(tuning.user_agent, timeout_seconds=tuning.http_timeout_seconds, headers={"x-apikey": settings.aeroapi_key}),
        MonthlyBudget(settings.followed_monthly_dollars, pathlib.Path(settings.state_dir) / tuning.followed_budget_file, clock),
        PricedByPath(settings.aeroapi_url, settings.aeroapi_prices, settings.aeroapi_unlisted_price),
    )
    schedules = AeroApiSchedules(settings.aeroapi_url, followed_http)
    timezone = ZoneInfo(settings.timezone)
    return FollowedStandby(
        EstimatedFollowedFlights(
            FollowedFlights(FollowedListFile(pathlib.Path(settings.followed_file), logger), schedules, tuning.follow_timing, clock, logger),
            DepartureEstimator(
                RecentBlockTimes(schedules, tuning.block_times_kept_seconds, clock, logger),
                TurnaroundsByType(tuning.turnarounds, tuning.default_turnaround),
                clock,
            ),
        ),
        AnnouncedFollowedCards(
            FollowedCardBuilder(settings.timezone, found.airport_tidiers, found.operator_names, tuning.late_minutes, logger),
            FollowedNews(
                [
                    Cancelled(),
                    Diverted(),
                    DelayMoved(tuning.late_minutes, tuning.delay_step_minutes, timezone),
                    GateChanged(),
                    TookOff(timezone),
                    LandingSoon(tuning.landing_soon),
                    Landed(),
                    BeltChanged(),
                ],
                clock,
                logger,
            ),
            voice.followed,
        ),
    )


def display_for(
    settings: Settings, tuning: Tuning, status: WatchStatus, clock: Clock, logger: logging.Logger
) -> tuple[Display, LiveServer | None]:
    """The Cast device when there is an app to cast, else the log; and the live page if it has a port."""
    display: Display
    if settings.cast_app_id:
        chromecast = PyChromecastDevice(
            ListedChromecasts(settings.cast_device_name, settings.cast_timeout_seconds),
            planes_channel(settings.cast_app_id),
            settings.cast_timeout_seconds,
            logger,
        )
        hub: CastDevice = MutedLaunchDevice(chromecast, tuning.chime_seconds, time.sleep) if settings.mute_chime else chromecast
        display = CastDisplay(CoolingOffDevice(hub, clock, tuning.cast_retry_seconds, logger), settings.cast_app_id, logger)
    else:
        logger.info("CAST_APP_ID is empty, so planes are logged rather than cast")
        display = LoggingDisplay(logger)
    live_server: LiveServer | None = None
    if settings.live_port is not None:
        latest = LatestCard()
        # All interfaces, so the receiver container can reach it through the host.
        live_server = LiveServer({"/planes.json": latest, "/status.json": status}, tuning.live_host, settings.live_port, logger)
        display = FanOutDisplay([display, latest])
    # Lets the card leave the flag off places in home's own country. Near a border the
    # nearest airport can be in the next country, so HOME_COUNTRY says for sure.
    home_country = settings.home_country or NearestAirportCountry.bundled().of(settings.home)
    if not settings.home_country:
        logger.info("HOME_COUNTRY is empty, so going by the nearest airport: %s", home_country)
    return Stamped(display, {"homeCountry": home_country}), live_server


def notables(settings: Settings, tuning: Tuning, clock: Clock, logger: logging.Logger) -> NotableFinder:
    """Who notable aircraft belong to, from plane-alert-db and the names file. Both are
    read on work of their own, so a slow download never holds up a card."""
    table = (
        MirroredText(
            settings.notable_aircraft_url,
            pathlib.Path(settings.state_dir) / tuning.notable_file,
            tuning.notable_max_age_seconds,
            UrllibTextHttp(tuning.user_agent, tuning.notable_timeout_seconds),
            clock,
            logger,
        )
        if settings.notable_aircraft_url
        else NoText()
    )
    names = LocalText(pathlib.Path(settings.notable_names_file)) if settings.notable_names_file else NoText()
    starter = ThreadStarter()
    return NotableAircraft(
        InBackground(
            lambda: plane_alert_table(table.text() or "", settings.notable_categories), {}, clock, tuning.notable_reread_seconds, starter
        ),
        InBackground(lambda: owner_names(names.text() or ""), {}, clock, tuning.notable_reread_seconds, starter),
    )


# Where the receiver serves the Pi's own owner pictures and the squares cut from web ones,
# relative to the page. They have to match the receiver's /portraits/ and /faces/ locations,
# so they are not tunings.
OWN_PORTRAITS_URL = "portraits/"
FACES_URL = "faces/"
FACE_FILES = ".jpg"


def portraits(settings: Settings, tuning: Tuning, http: JsonHttp, clock: Clock, logger: logging.Logger) -> PortraitLookup:
    """Pictures of who notable aircraft belong to: the Pi's own first, then Wikipedia's,
    asked about only when one gets a card."""
    places: list[PortraitLookup] = []
    if settings.own_portraits_dir:
        places.append(LocalPortraits(pathlib.Path(settings.own_portraits_dir), OWN_PORTRAITS_URL))
    if settings.portrait_api_url:
        cache: TtlCache[str | None] = TtlCache(
            clock, tuning.portrait_cache_seconds, tuning.portrait_cache_entries, tuning.portrait_retry_seconds
        )
        web: PortraitLookup = WikipediaPortraits(settings.portrait_api_url, http, tuning.portrait_source_pixels)
        if settings.faces_dir:
            web = FaceCrops(
                web,
                UrllibBytesHttp(tuning.user_agent, tuning.http_timeout_seconds),
                OpenCvPictures(),
                YuNetFaces(YUNET_MODEL, tuning.face_confidence),
                tuning.portrait_framing,
                KeptFiles(pathlib.Path(settings.faces_dir), FACES_URL, tuning.portraits_kept, FACE_FILES),
                tuning.portrait_square_pixels,
                tuning.portrait_jpeg_quality,
                logger,
            )
        places.append(CachedPortraits(web, cache, logger))
    return FirstPortrait(places)


def watcher_for(
    settings: Settings,
    tuning: Tuning,
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
    closest = ClosestApproach(settings.home, tuning.approach_min_speed_kt)
    paths = LearnedPaths(
        JsonPathStore(pathlib.Path(settings.state_dir) / tuning.paths_file, logger),
        tuning.path_likeness,
        tuning.paths_kept,
        tuning.path_kept_for,
        clock,
    )
    bound = DestinationBound(found.known_routes, settings.home, logger)
    misses = LearnedPaths(
        JsonPathStore(pathlib.Path(settings.state_dir) / tuning.misses_file, logger),
        tuning.path_likeness,
        tuning.paths_kept,
        tuning.path_kept_for,
        clock,
    )
    recorder = PathRecorder(
        [CameOverhead(paths, bound, zone.radius_km, logger), MissedIt(misses, bound, zone.radius_km, logger)],
        closest,
        settings.home,
        zone.radius_km,
        tuning.path_km,
        tuning.path_every_seconds,
        tuning.path_gone_seconds,
        clock,
    )
    approaching = FirstFound(
        [
            ApproachFinder(
                closest,
                settings.home,
                zone.radius_km,
                tuning.approach_steady_polls,
                tuning.approach_steady_polls_per_km,
                tuning.approach_max_turn_deg,
                tuning.approach_wander_km,
                [
                    LandsFirst(),
                    SteeredIn(tuning.steered_below_ft, tuning.steered_beyond_km, tuning.descending_fpm),
                    MissedBefore(misses, paths, bound, SameWay(tuning.bound_within_deg), tuning.misses_min),
                ],
            ),
            PathFinder(
                paths,
                bound,
                SameWay(tuning.bound_within_deg),
                settings.home,
                zone.radius_km,
                tuning.path_min_planes,
                tuning.path_held_polls,
            ),
        ]
    )
    cards = OwnedCards(
        CardBuilder(found.routes, found.photos, AircraftNames(), services, logger),
        notables(settings, tuning, clock, logger),
        portraits(settings, tuning, http, clock, logger),
    )

    def planes_message(speech: QuietVoice | Silence) -> PlanesMessageBuilder:
        return PlanesMessageBuilder(
            cards,
            speech,
            settings.home,
            zone.radius_km,
            settings.max_cards,
            Zone(settings.home, tuning.surroundings_km),
            tuning.max_other_planes,
            services,
        )

    emergencies = FirstEmergencies(
        [
            HeldEmergencies(DeclaredEmergency(), settings.home, tuning.emergency_held_polls, tuning.emergency_clear_seconds, clock),
            HeldEmergencies(
                AltitudeBearsOut(SteepClimbOrDescent(tuning.steep_descent_fpm, tuning.steep_climb_fpm), clock, tuning.steep_altitude_share),
                settings.home,
                tuning.steep_held_polls,
                tuning.emergency_clear_seconds,
                clock,
            ),
        ]
    )
    return Watcher(
        source=HeardSource(KnownRotorcraft.bundled(Tar1090AircraftSource(settings.aircraft_url, http)), status),
        zone=ServicesStay(
            OverheadAndApproaching(zone, Observing(recorder, approaching), closest, tuning.overhead_soon_seconds),
            services,
            tuning.services_kept,
            settings.home,
            tuning.service_hold_km,
        ),
        messages=planes_message(voice.planes),
        display=display,
        quiet_hours=QuietHours.parse(settings.quiet_hours),
        linger=MinimumShowing(Linger(settings.linger_seconds, clock), settings.card_min_seconds, clock),
        arrivals=AllObservers([ArrivalLog(logger), DailyTally(status, clock, logger)]),
        clock=clock,
        standby=standby,
        due_seconds=tuning.approach_due_seconds,
        surroundings=Zone(settings.home, tuning.surroundings_km),
        rare=rare,
        emergencies=EmergencyAlert(emergencies, EmergencyMessages(planes_message(Silence()), voice.emergency), EmergencyLog(logger)),
    )
