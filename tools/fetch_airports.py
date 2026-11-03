"""Writes the country and position of every airport with an IATA code to
watcher/src/flights_watcher/airport_countries.json and airport_places.json, from
OurAirports' public-domain list.

The card puts a flag in front of cities in other countries, and the map draws a line to where
the plane is going, but the routes from FlightAware say neither which country an airport
is in nor where it is. Run it again now and then to pick up new airports:

    python3 tools/fetch_airports.py
"""

import csv
import io
import json
import pathlib
import urllib.request

SOURCE = "https://davidmegginson.github.io/ourairports-data/airports.csv"
PACKAGE = pathlib.Path(__file__).resolve().parent.parent / "watcher/src/flights_watcher"
# Three decimal places is about 100 m, close enough to draw a line to.
PLACES = 3
# When two airports share an IATA code, the busier kind wins.
RANK = {"large_airport": 0, "medium_airport": 1, "small_airport": 2, "seaplane_base": 3, "heliport": 4}


def main() -> None:
    with urllib.request.urlopen(SOURCE, timeout=60) as response:
        rows = csv.DictReader(io.StringIO(response.read().decode("utf-8")))
        best: dict[str, tuple[int, dict[str, str]]] = {}
        for row in rows:
            code, country = row["iata_code"].strip(), row["iso_country"].strip()
            if len(code) != 3 or len(country) != 2 or row["type"] == "closed":
                continue
            rank = (0 if row["scheduled_service"] == "yes" else 10) + RANK.get(row["type"], 5)
            if code not in best or rank < best[code][0]:
                best[code] = (rank, row)
    airports = {code: row for code, (_, row) in sorted(best.items())}
    countries = {code: row["iso_country"].strip() for code, row in airports.items()}
    places = {
        code: [round(float(row["latitude_deg"]), PLACES), round(float(row["longitude_deg"]), PLACES)]
        for code, row in airports.items()
    }
    write("airport_countries.json", {"source": SOURCE, "countries": countries})
    write("airport_places.json", {"source": SOURCE, "places": places})


def write(name: str, table: dict) -> None:
    (PACKAGE / name).write_text(json.dumps(table, separators=(",", ":")) + "\n")
    print(f"wrote {name}")


if __name__ == "__main__":
    main()
