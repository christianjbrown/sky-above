"""Writes the ICAO type designator of every helicopter and gyrocopter to
watcher/src/flights_watcher/rotorcraft_types.json, from the aircraft type table that
tar1090 ships.

A helicopter with only a Mode S transponder says who it is and how high it is flying,
but not what kind of aircraft it is, so the card and the map would draw it as a plane.
The decoder's database still knows its type, and this table says which types have
rotors. Run it again now and then to pick up new types:

    python3 tools/fetch_rotorcraft_types.py
"""

import gzip
import json
import pathlib
import urllib.request

SOURCE = "https://raw.githubusercontent.com/wiedehopf/tar1090-db/master/db/icao_aircraft_types2.js"
PACKAGE = pathlib.Path(__file__).resolve().parent.parent / "watcher/src/flights_watcher"
# The first letter of an ICAO aircraft description: H for a helicopter, G for a gyrocopter.
ROTORCRAFT = ("H", "G")


def main() -> None:
    with urllib.request.urlopen(SOURCE, timeout=60) as response:
        body = response.read()
    # The file is served gzipped, whatever its name says.
    if body[:2] == b"\x1f\x8b":
        body = gzip.decompress(body)
    table = json.loads(body)
    types = sorted(code for code, (_, description, *_) in table.items() if description[:1] in ROTORCRAFT)
    (PACKAGE / "rotorcraft_types.json").write_text(json.dumps({"source": SOURCE, "types": types}, separators=(",", ":")) + "\n")
    print(f"wrote rotorcraft_types.json with {len(types)} types")


if __name__ == "__main__":
    main()
