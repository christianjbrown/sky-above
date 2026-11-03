"""Copies airline icons from Soaring Symbols into receiver/logos/<ICAO>.svg, plus a
few it does not have from elsewhere (EXTRAS).

The receiver page shows them from the Pi, so the Hub never fetches a logo
from the internet. Run it again with a newer commit to pick up new airlines:

    python3 tools/fetch_airline_logos.py
"""

import json
import pathlib
import time
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
    "HLF": "TOM",  # TUIfly
    "LHX": "DLH",  # Lufthansa City Airlines
    "GEC": "DLH",  # Lufthansa Cargo
    "SQC": "SIA",  # Singapore Airlines Cargo
    "BCS": "DHK",  # European Air Transport, flying for DHL
    "EJA": "NJE",  # NetJets in the US
    "LXJ": "FJO",  # Flexjet in the US
    "SWN": "NPT",  # West Atlantic Sweden
}
# Airlines Soaring Symbols has no logo for, from Wikimedia, public domain or CC0. Each
# file's licence was checked by hand; a non-free one never goes in.
EXTRAS = {
    "TOM": "https://upload.wikimedia.org/wikipedia/commons/6/6f/TUI_Logo_2016.svg",  # TUI Airways
    "LOG": "https://upload.wikimedia.org/wikipedia/en/9/94/Loganair_logo.svg",  # Loganair
    "AIH": "https://upload.wikimedia.org/wikipedia/commons/e/e7/AirZeta_logo_2025.svg",  # AirZeta
    "AIZ": "https://upload.wikimedia.org/wikipedia/commons/9/9b/Arkia_Israeli_logo.svg",  # Arkia
    "AJT": "https://upload.wikimedia.org/wikipedia/commons/c/c3/Amerijet_Logo.svg",  # Amerijet International
    "ATC": "https://upload.wikimedia.org/wikipedia/en/0/0b/Air_Tanzania_logo.svg",  # Air Tanzania
    "AUR": "https://upload.wikimedia.org/wikipedia/commons/a/a2/Aurigny_logo.svg",  # Aurigny
    "AWC": "https://upload.wikimedia.org/wikipedia/en/7/75/Titan_Airways_logo.svg",  # Titan Airways
    "AWG": "https://upload.wikimedia.org/wikipedia/en/3/39/Animawings_Logo.svg",  # Animawings
    "AZW": "https://upload.wikimedia.org/wikipedia/commons/8/8b/Air_Zimbabwe_wordmark.svg",  # Air Zimbabwe
    "BBC": "https://upload.wikimedia.org/wikipedia/en/9/9f/Biman_Airlines_classic_logo.svg",  # Biman Bangladesh Airlines
    "CAI": "https://upload.wikimedia.org/wikipedia/commons/8/88/Corendon_Airlines_Logo_2017.svg",  # Corendon Airlines
    "CLX": "https://upload.wikimedia.org/wikipedia/commons/7/76/Cargolux_logo.svg",  # Cargolux
    "CTN": "https://upload.wikimedia.org/wikipedia/commons/e/e0/Croatia_Airlines_2024_logo.svg",  # Croatia Airlines
    "CYP": "https://upload.wikimedia.org/wikipedia/commons/9/93/Cyprus_Airways_%28logo%2C_2017%29.svg",  # Cyprus Airways
    "DHK": "https://upload.wikimedia.org/wikipedia/commons/a/ac/DHL_Logo.svg",  # DHL Aviation
    "ELY": "https://upload.wikimedia.org/wikipedia/commons/d/d7/El_Al_logo.svg",  # El Al
    "FDX": "https://upload.wikimedia.org/wikipedia/commons/9/9d/FedEx_Express.svg",  # FedEx Express
    "FIA": "https://upload.wikimedia.org/wikipedia/commons/6/61/Flyone-logo-1.1.svg",  # FlyOne
    "FJO": "https://upload.wikimedia.org/wikipedia/commons/b/b3/Flexjet_Logo.svg",  # Flexjet
    "FPO": "https://upload.wikimedia.org/wikipedia/commons/a/a5/ASL_Airlines_France_logo.svg",  # ASL Airlines France
    "GFA": "https://upload.wikimedia.org/wikipedia/commons/9/97/Gulf_Air_2018_wordmark.svg",  # Gulf Air
    "GMA": "https://upload.wikimedia.org/wikipedia/en/2/29/Gama_Aviation_logo.svg",  # Gama Aviation
    "ISR": "https://upload.wikimedia.org/wikipedia/commons/9/9c/Israir_Airlines_Logo.svg",  # Israir
    "LBT": "https://upload.wikimedia.org/wikipedia/commons/c/c6/Nouvelair_Logo.svg",  # Nouvelair
    "LGL": "https://upload.wikimedia.org/wikipedia/commons/8/8a/Luxair_Logo.svg",  # Luxair
    "LZB": "https://upload.wikimedia.org/wikipedia/commons/1/18/Bulgaria_Air_logo.svg",  # Bulgaria Air
    "MNB": "https://upload.wikimedia.org/wikipedia/commons/7/73/MNG_Airlines_logo.svg",  # MNG Airlines
    "NBT": "https://upload.wikimedia.org/wikipedia/commons/2/28/Norse.svg",  # Norse Atlantic Airways
    "NCR": "https://upload.wikimedia.org/wikipedia/commons/d/dd/National_Airlines_logo.svg",  # National Airlines
    "NJE": "https://upload.wikimedia.org/wikipedia/commons/9/9d/NetJets_logo.svg",  # NetJets
    "NPT": "https://upload.wikimedia.org/wikipedia/commons/b/bf/West_atlantic_logo.svg",  # West Atlantic UK
    "OCN": "https://upload.wikimedia.org/wikipedia/commons/8/88/Logo_Discover_Airlines.svg",  # Discover Airlines
    "PIA": "https://upload.wikimedia.org/wikipedia/en/d/dd/Pakistan_International_Airlines_logo_%282004%29.svg",  # Pakistan International Airlines
    "QNT": "https://upload.wikimedia.org/wikipedia/en/2/26/Qanot_Sharq_logo.svg",  # Qanot Sharq
    "SEH": "https://upload.wikimedia.org/wikipedia/en/b/ba/Sky_Express_Logo.svg",  # Sky Express
    "SQP": "https://upload.wikimedia.org/wikipedia/commons/1/18/SkyUp_Airlines_logo.svg",  # SkyUp Airlines
    "SWU": "https://upload.wikimedia.org/wikipedia/commons/9/99/SkyAlps_Logo.svg",  # Sky Alps
    "SXE": "https://upload.wikimedia.org/wikipedia/commons/1/1e/Logo_AirSierraLeone.svg",  # Air Sierra Leone
    "SXS": "https://upload.wikimedia.org/wikipedia/commons/d/d9/SunExpress_Logo.svg",  # SunExpress
    "TAM": "https://upload.wikimedia.org/wikipedia/commons/f/fe/Latam-logo_-v_%28Indigo%29.svg",  # LATAM Brasil
    "TAY": "https://upload.wikimedia.org/wikipedia/commons/e/e8/ASL_Airlines_Belgium_Logo.svg",  # ASL Airlines Belgium
    "TKJ": "https://upload.wikimedia.org/wikipedia/commons/3/38/AJet_logo.svg",  # AJet
    "UPS": "https://upload.wikimedia.org/wikipedia/commons/6/6b/United_Parcel_Service_logo_2014.svg",  # UPS Airlines
    "VJT": "https://upload.wikimedia.org/wikipedia/commons/3/3a/VistaJet_logo.svg",  # VistaJet
}
OUT = pathlib.Path(__file__).resolve().parents[1] / "receiver" / "logos"


def fetch(path: str) -> bytes:
    return download(f"{SOURCE}/{COMMIT}/{path}")


def download(url: str) -> bytes:
    """Waits and tries again when told to slow down, as Wikimedia does after a few files."""
    request = urllib.request.Request(url, headers={"User-Agent": "flights logo fetch"})
    for wait in (10, 60, 120):
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            if error.code != 429:
                raise
            time.sleep(wait)
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
        # Wikimedia only allows a few downloads in a row, so one already here is kept.
        # To pick up a new version of one, delete its file first.
        kept = OUT / f"{code}.svg"
        if kept.exists() and kept.stat().st_size and code not in written:
            written[code] = kept.read_bytes()
            continue
        time.sleep(2)
        written[code] = download(url)
        kept.write_bytes(written[code])
    for alias, code in ALIASES.items():
        if code in written:
            (OUT / f"{alias}.svg").write_bytes(written[code])
    for old in OUT.glob("*.svg"):
        if old.stem not in written and old.stem not in ALIASES:
            old.unlink()
    (OUT / "LICENSE").write_bytes(fetch("LICENSE"))
    print(f"wrote {len(written)} logos and {len(ALIASES)} aliases to {OUT}")

if __name__ == "__main__":
    main()
