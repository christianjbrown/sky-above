import copy
from datetime import timedelta
from pathlib import Path

import pytest

from flights_watcher.config import ConfigError
from flights_watcher.estimate import TurnaroundRule
from flights_watcher.faces import Framing
from flights_watcher.paths import Likeness
from flights_watcher.tuning import Tuning, TuningError, load_tuning, read_toml

REPO = Path(__file__).resolve().parents[2]
SHIPPED = REPO / "tuning" / "tuning.toml"


def shipped() -> dict:
    return copy.deepcopy(read_toml(SHIPPED))


def test_the_shipped_tunings_are_read_in_the_units_the_watcher_counts_in():
    tuning = load_tuning(SHIPPED, None)
    assert tuning.lookup_ttl_seconds == 6 * 3600
    assert tuning.operator_ttl_seconds == 30 * 24 * 3600
    assert tuning.no_route_ttl_seconds == 600
    assert tuning.route_kept_fresh == timedelta(days=180)
    assert tuning.follow_timing.lead == timedelta(hours=4)
    assert tuning.follow_timing.position_every == 180
    assert tuning.path_likeness == Likeness(within_km=0.5, within_ft=1500, within_deg=15)
    assert tuning.turnarounds[1] == TurnaroundRule(("E1", "E7", "CRJ", "AT4", "AT7", "DH8", "SF3", "F70", "J41"), timedelta(minutes=25))
    assert tuning.default_turnaround == timedelta(minutes=35)
    assert tuning.notable_reread_seconds == 3600
    assert tuning.portrait_retry_seconds == 600
    assert tuning.portrait_source_pixels == 960
    assert tuning.portrait_framing == Framing(zoom=2.4, headroom=0.4)
    assert tuning.portraits_kept == 200


def test_airports_are_said_by_city_unless_their_city_has_several():
    tuning = load_tuning(SHIPPED, None)
    assert tuning.airport_cities["GOT"] == "Gothenburg"
    assert tuning.airport_cities["STN"] == "London"
    assert "STN" in tuning.named_airports
    assert "GOT" not in tuning.named_airports


def test_a_local_file_changes_only_what_it_names(tmp_path):
    local = tmp_path / "local.toml"
    local.write_text('[paths]\nkept = 10\n\n[airports.cities]\nMadrid = ["MAD"]\n\n[services]\nkept = ["police"]\n')
    tuning = load_tuning(SHIPPED, local)
    assert tuning.paths_kept == 10
    assert tuning.path_min_planes == 2
    assert tuning.airport_cities["MAD"] == "Madrid"
    assert tuning.airport_cities["LHR"] == "London"
    assert tuning.services_kept == ("police",)
    assert load_tuning(SHIPPED, tmp_path / "absent.toml") == load_tuning(SHIPPED, None)


def test_a_local_file_with_a_typo_stops_the_watcher(tmp_path):
    local = tmp_path / "local.toml"
    local.write_text("[paths]\nkpet = 10\n")
    with pytest.raises(TuningError, match="paths has nothing called kpet"):
        load_tuning(SHIPPED, local)
    local.write_text("[paths\n")
    with pytest.raises(TuningError, match=r"local\.toml is not valid TOML"):
        load_tuning(SHIPPED, local)


def broken(change) -> str:
    data = shipped()
    change(data)
    with pytest.raises(ConfigError) as refused:
        Tuning.from_mapping(data)
    return str(refused.value)


def test_every_value_has_to_be_there_and_of_its_kind():
    assert broken(lambda data: data.pop("emergency")) == "emergency is missing"
    assert broken(lambda data: data["paths"].pop("kept")) == "paths.kept is missing"
    assert broken(lambda data: data.update(extra=1)) == "the tuning file has nothing called extra"
    assert "should be a number" in broken(lambda data: data["paths"].update(km="far"))
    assert "should be a number" in broken(lambda data: data["paths"].update(km=True))
    assert "paths.kept should be a whole number" in broken(lambda data: data["paths"].update(kept=6.5))
    assert "http.user_agent should be text" in broken(lambda data: data["http"].update(user_agent=1))
    assert "services.kept should be a list of text" in broken(lambda data: data["services"].update(kept="police"))
    assert "speech.said_as.MAX should be text" in broken(lambda data: data["speech"]["said_as"].update(MAX=1))
    assert "airports.cities.London should be a list of text" in broken(lambda data: data["airports"]["cities"].update(London="LHR"))
    assert "should be a [map] table" in broken(lambda data: data.update(map=1))
    assert "followed.turnarounds should be a list" in broken(lambda data: data["followed"].update(turnarounds={}))
    assert "followed.turnarounds[0] has nothing called extra" in broken(lambda data: data["followed"]["turnarounds"][0].update(extra=1))
