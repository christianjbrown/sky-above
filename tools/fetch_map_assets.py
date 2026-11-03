"""Copies the map libraries, fonts and icons into receiver/vendor/, so the Hub
draws the map entirely from the Pi. Bump a version and run it again to update:

    python3 tools/fetch_map_assets.py

Place names in other scripts (Greek, Cyrillic, Arabic, Chinese...) need their glyph
ranges too: list them, comma separated, in GLYPH_RANGES, such as
GLYPH_RANGES=0-255,256-511,768-1023,1024-1279,8192-8447 for Greek and Cyrillic.

The map data itself (map/area.pmtiles and map/world.pmtiles) is too big for git; the
README says how to cut it.
"""

import os
import pathlib
import urllib.parse
import urllib.request

NPM = "https://unpkg.com"
LIBRARIES = {
    "maplibre-gl.js": "maplibre-gl@5.24.0/dist/maplibre-gl.js",
    "maplibre-gl.css": "maplibre-gl@5.24.0/dist/maplibre-gl.css",
    "pmtiles.js": "pmtiles@4.5.0/dist/pmtiles.js",
    "basemaps.js": "@protomaps/basemaps@5.7.2/dist/basemaps.js",
}
ASSETS = "https://raw.githubusercontent.com/protomaps/basemaps-assets/028c18f713baecad011301ff7a69acc39bcc2ae7"
FONTS = ["Noto Sans Regular", "Noto Sans Medium", "Noto Sans Italic"]
# Basic Latin, Latin-1 and Latin Extended, and punctuation: enough for place names in
# Latin script, unless GLYPH_RANGES says otherwise.
GLYPH_RANGES = os.environ.get("GLYPH_RANGES", "0-255,256-511,8192-8447").split(",")
SPRITES = ["dark.json", "dark.png", "dark@2x.json", "dark@2x.png"]
OUT = pathlib.Path(__file__).resolve().parents[1] / "receiver" / "vendor"


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "sky-above map asset fetch"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def save(path: pathlib.Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def main() -> None:
    for name, package_path in LIBRARIES.items():
        save(OUT / name, fetch(f"{NPM}/{package_path}"))
    for font in FONTS:
        for glyphs in GLYPH_RANGES:
            save(OUT / "fonts" / font / f"{glyphs}.pbf", fetch(f"{ASSETS}/fonts/{urllib.parse.quote(font)}/{glyphs}.pbf"))
    for sprite in SPRITES:
        save(OUT / "sprites" / sprite, fetch(f"{ASSETS}/sprites/v4/{sprite}"))
    print(f"wrote {len(LIBRARIES)} libraries, {len(FONTS) * len(GLYPH_RANGES)} glyph files and {len(SPRITES)} sprite files")


if __name__ == "__main__":
    main()
