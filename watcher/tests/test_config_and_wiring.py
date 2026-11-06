from pathlib import Path

import pytest
import yaml

from flights_watcher.chromecast import NAMESPACE
from flights_watcher.config import OPTIONAL_KEYS, REQUIRED_KEYS, ConfigError, Settings
from flights_watcher.geo import Location

REPO = Path(__file__).resolve().parents[2]
FULL_ENV = {
    "AIRCRAFT_URL": "http://localhost:8080/data/aircraft.json",
    "HOME_LAT": "51.4769",
    "HOME_LON": "0.0",
    "ZONE_RADIUS_KM": "3",
    "LINGER_SECONDS": "45",
    "CARD_MIN_SECONDS": "120",
    "POLL_SECONDS": "1",
    "MAX_CARDS": "3",
    "TZ": "Europe/London",
    "CAST_DEVICE_NAME": "Kitchen display",
    "CAST_TIMEOUT_SECONDS": "10",
    "ROUTE_API_URL": "https://api.adsbdb.com/v0",
    "PHOTO_API_URL": "https://api.planespotters.net/pub",
    "QUIET_HOURS": "23:00-07:00",
    "CAST_APP_ID": "",
    "LIVE_PORT": "8091",
    "SPEECH_SERVER": "localhost:10200",
    "SPEECH_DIR": "/var/lib/flights/speech",
    "SPEECH_QUIET_HOURS": "00:00-10:00",
    "AEROAPI_KEY": "",
    "AEROAPI_URL": "https://aeroapi.flightaware.com/aeroapi",
    "AEROAPI_MONTHLY_LIMIT": "1000",
    "STATE_DIR": "/var/lib/flights/state",
    "MUTE_CHIME": "true",
    "FOLLOWED_FILE": "/etc/flights/followed/flights.txt",
    "FOLLOWED_MONTHLY_LIMIT": "600",
    "AIR_AMBULANCE_CALLSIGNS": "hle, xyz",
    "POLICE_CALLSIGNS": "UKP",
    "AIR_AMBULANCE_SQUAWKS": "0020",
    "POLICE_SQUAWKS": "0032, 0045-0051",
    "QUIET_HOURS_EXCEPT": "Helicopters, military",
    "HOME_COUNTRY": " gb",
}


def test_settings_read_every_value():
    settings = Settings.from_env(FULL_ENV)
    assert settings.home == Location(51.4769, 0.0)
    assert settings.radius_km == 3
    assert settings.card_min_seconds == 120
    assert settings.max_cards == 3
    assert settings.cast_device_name == "Kitchen display"
    assert settings.cast_app_id == ""
    assert settings.quiet_hours == "23:00-07:00"
    assert settings.live_port == 8091
    assert settings.speech_server == ("localhost", 10200)
    assert settings.speech_quiet_hours == "00:00-10:00"
    assert settings.aeroapi_monthly_limit == 1000
    assert settings.mute_chime
    assert settings.followed_file == "/etc/flights/followed/flights.txt"
    assert settings.followed_monthly_limit == 600
    assert settings.air_ambulance_callsigns == ("HLE", "XYZ")
    assert settings.police_callsigns == ("UKP",)
    assert settings.air_ambulance_squawks == ("0020",)
    assert settings.police_squawks == ("0032", "0045", "0046", "0047", "0050", "0051")
    assert Settings.from_env({**FULL_ENV, "POLICE_SQUAWKS": ""}).police_squawks == ()
    with pytest.raises(ConfigError, match="0089 is not a squawk"):
        Settings.from_env({**FULL_ENV, "POLICE_SQUAWKS": "0089"})
    with pytest.raises(ConfigError, match="squawk range 0061-0041 runs backwards"):
        Settings.from_env({**FULL_ENV, "POLICE_SQUAWKS": "0061-0041"})
    assert settings.quiet_hours_except == ("helicopters", "military")
    assert settings.home_country == "GB"
    assert Settings.from_env({**FULL_ENV, "QUIET_HOURS_EXCEPT": ""}).quiet_hours_except == ()
    with pytest.raises(ConfigError, match="QUIET_HOURS_EXCEPT"):
        Settings.from_env({**FULL_ENV, "QUIET_HOURS_EXCEPT": "gliders"})
    with pytest.raises(ConfigError, match="SPEECH_QUIET_HOURS: 'Caturday' is not a day of the week"):
        Settings.from_env({**FULL_ENV, "SPEECH_QUIET_HOURS": "00:00-08:00, Caturday 09:00-10:00"})
    with pytest.raises(ConfigError, match="QUIET_HOURS: quiet hours should look like 23:00-07:00"):
        Settings.from_env({**FULL_ENV, "QUIET_HOURS": "all night"})
    assert Settings.from_env({**FULL_ENV, "POLICE_CALLSIGNS": ""}).police_callsigns == ()
    assert Settings.from_env({**FULL_ENV, "SPEECH_SERVER": ""}).speech_server is None
    assert Settings.from_env({**FULL_ENV, "LIVE_PORT": ""}).live_port is None
    with pytest.raises(ConfigError, match="SPEECH_SERVER"):
        Settings.from_env({**FULL_ENV, "SPEECH_SERVER": "nocolon"})


def test_missing_or_bad_settings_are_named():
    with pytest.raises(ConfigError, match="HOME_LAT"):
        Settings.from_env({**FULL_ENV, "HOME_LAT": ""})
    assert Settings.from_env({**FULL_ENV, "ROUTE_API_URL": ""}).route_api_url == ""
    with pytest.raises(ConfigError, match="bad setting"):
        Settings.from_env({**FULL_ENV, "ZONE_RADIUS_KM": "three"})


def test_muting_the_chime_is_a_switch():
    assert not Settings.from_env({**FULL_ENV, "MUTE_CHIME": "false"}).mute_chime
    assert not Settings.from_env({**FULL_ENV, "MUTE_CHIME": ""}).mute_chime
    assert Settings.from_env({**FULL_ENV, "MUTE_CHIME": "Yes"}).mute_chime
    with pytest.raises(ConfigError, match="MUTE_CHIME"):
        Settings.from_env({**FULL_ENV, "MUTE_CHIME": "sometimes"})


def test_compose_hands_the_watcher_every_setting():
    compose = yaml.safe_load((REPO / "docker-compose.yml").read_text())
    environment = compose["services"]["watcher"]["environment"]
    names = {entry.split("=", 1)[0] for entry in environment}
    assert set(REQUIRED_KEYS) | set(OPTIONAL_KEYS) <= names


def test_compose_feeds_the_home_location_from_the_feeder_settings():
    compose = yaml.safe_load((REPO / "docker-compose.yml").read_text())
    environment = dict(entry.split("=", 1) for entry in compose["services"]["watcher"]["environment"])
    assert environment["HOME_LAT"] == "${FEEDER_LAT:-}"
    assert environment["HOME_LON"] == "${FEEDER_LONG:-}"


def test_receiver_page_listens_on_the_same_namespace():
    assert f'"{NAMESPACE}"' in (REPO / "receiver" / "app.js").read_text()


def test_compose_serves_the_receiver_page_from_the_pi():
    compose = yaml.safe_load((REPO / "docker-compose.yml").read_text())
    assert "./receiver:/usr/share/nginx/html:ro" in compose["services"]["receiver"]["volumes"]


def test_receiver_reaches_the_watcher_on_the_same_live_port():
    compose = yaml.safe_load((REPO / "docker-compose.yml").read_text())
    watcher = dict(entry.split("=", 1) for entry in compose["services"]["watcher"]["environment"])
    receiver = dict(entry.split("=", 1) for entry in compose["services"]["receiver"]["environment"])
    assert watcher["LIVE_PORT"] == receiver["LIVE_PORT"]
    assert "${LIVE_PORT}" in (REPO / "nginx" / "templates" / "card.locations.template").read_text()


def test_receiver_serves_the_clips_the_watcher_writes():
    compose = yaml.safe_load((REPO / "docker-compose.yml").read_text())
    watcher = dict(entry.split("=", 1) for entry in compose["services"]["watcher"]["environment"])
    assert f"speech:{watcher['SPEECH_DIR']}" in compose["services"]["watcher"]["volumes"]
    assert "speech:/srv/speech:ro" in compose["services"]["receiver"]["volumes"]
    assert "location /speech/" in (REPO / "nginx" / "templates" / "card.locations.template").read_text()


def test_receiver_serves_logos_kept_only_on_the_pi_before_the_repos():
    compose = yaml.safe_load((REPO / "docker-compose.yml").read_text())
    assert "./own-logos:/srv/own/logos:ro" in compose["services"]["receiver"]["volumes"]
    locations = (REPO / "nginx" / "templates" / "card.locations.template").read_text()
    assert "root /srv/own;\n    try_files $uri @repo_logos;" in locations
    assert "own-logos/" in (REPO / ".gitignore").read_text().splitlines()


def test_the_watcher_keeps_its_state_on_a_volume():
    compose = yaml.safe_load((REPO / "docker-compose.yml").read_text())
    watcher = dict(entry.split("=", 1) for entry in compose["services"]["watcher"]["environment"])
    assert f"watcher_state:{watcher['STATE_DIR']}" in compose["services"]["watcher"]["volumes"]


def test_https_uses_the_certificate_the_certs_service_keeps():
    compose = yaml.safe_load((REPO / "docker-compose.yml").read_text())
    assert "certs:/certs" in compose["services"]["certs"]["volumes"]
    assert "certs:/certs:ro" in compose["services"]["receiver"]["volumes"]
    https = (REPO / "nginx" / "templates" / "https.conf.template").read_text()
    assert "/certs/certificates/${CERT_DOMAIN}.crt" in https
    assert "include /etc/nginx/card.locations;" in https
    assert "/certs/certificates/${CERT_DOMAIN}.crt" in (REPO / "nginx" / "https.sh").read_text()
