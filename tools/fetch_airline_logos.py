"""Copies airline icons from Soaring Symbols into receiver/logos/<ICAO>.svg, plus a
few it does not have from elsewhere (EXTRAS).

The receiver page shows them from the Pi, so the Hub never fetches a logo
from the internet. Run it again with a newer commit to pick up new airlines:

    python3 tools/fetch_airline_logos.py
"""

import json
import pathlib
import urllib.error
import urllib.request

SOURCE = "https://raw.githubusercontent.com/anhthang/soaring-symbols"
COMMIT = "c1a63ca2b50376d27408562ae183bcb1f4247d11"
# Callsign codes that fly under another airline's brand.
ALIASES = {
    "RUK": "RYR",  # Ryanair UK
    "MAY": "RYR",  # Malta Air, flying for Ryanair
    "SHT": "BAW",  # BA Shuttle
    "CFE": "BAW",  # BA CityFlyer
    "EFW": "BAW",  # BA Euroflyer
    "EJU": "EZY",  # easyJet Europe
    "EZS": "EZY",  # easyJet Switzerland
    "WUK": "WZZ",  # Wizz Air UK
    "WMT": "WZZ",  # Wizz Air Malta
    "WAZ": "WZZ",  # Wizz Air Abu Dhabi
    "NAX": "NOZ",  # Norwegian
    "NSZ": "NOZ",  # Norwegian Air Sweden
    "IBK": "NOZ",  # Norwegian Air International
    "CLH": "DLH",  # Lufthansa CityLine
    "KLC": "KLM",  # KLM Cityhopper
    "HOP": "AFR",  # Air France Hop
    "EAI": "EIN",  # Emerald, flying Aer Lingus Regional
    "IBS": "IBE",  # Iberia Express
    "TUI": "TOM",  # TUIfly Germany
    "JAF": "TOM",  # TUI fly Belgium
    "TFL": "TOM",  # TUI fly Netherlands
    "BLX": "TOM",  # TUI fly Nordic
}
# Airlines Soaring Symbols has no logo for, from Wikimedia, public domain.
EXTRAS = {
    "TOM": "https://upload.wikimedia.org/wikipedia/commons/6/6f/TUI_Logo_2016.svg",  # TUI Airways
    "LOG": "https://upload.wikimedia.org/wikipedia/en/9/94/Loganair_logo.svg",  # Loganair
}
OUT = pathlib.Path(__file__).resolve().parents[1] / "receiver" / "logos"


def fetch(path: str) -> bytes:
    return download(f"{SOURCE}/{COMMIT}/{path}")


def download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "flights logo fetch"})
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.read()


def first_of(*paths: str) -> bytes | None:
    """The square icon where an airline has one, else its wide logo."""
    for path in paths:
        try:
            return fetch(path)
        except urllib.error.HTTPError as error:
            if error.code != 404:
                raise
    return None


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.svg"):
        old.unlink()
    airlines = json.loads(fetch("airlines.json"))
    written = {}
    for airline in airlines:
        code = airline.get("icao")
        if not code:
            continue
        svg = first_of(f"assets/{airline['slug']}/icon.svg", f"assets/{airline['slug']}/logo.svg")
        if svg is None:
            print(f"no logo for {airline['name']}")
            continue
        (OUT / f"{code}.svg").write_bytes(svg)
        written[code] = svg
    for code, url in EXTRAS.items():
        written[code] = download(url)
        (OUT / f"{code}.svg").write_bytes(written[code])
    for alias, code in ALIASES.items():
        if code in written:
            (OUT / f"{alias}.svg").write_bytes(written[code])
    (OUT / "LICENSE").write_bytes(fetch("LICENSE"))
    print(f"wrote {len(written)} logos and {len(ALIASES)} aliases to {OUT}")


if __name__ == "__main__":
    main()
