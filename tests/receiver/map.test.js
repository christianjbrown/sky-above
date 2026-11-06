import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { installMapFakes, load } from "./support.js";

let fakes;
let container;

const HOME = { lat: 51.4769, lon: 0 };

function planeMessage(plane = {}, extra = {}) {
  return {
    home: HOME,
    radiusKm: 1.5,
    planes: [{ hex: "abc123", lat: 51.48, lon: 0.03, trackDeg: 90, category: "A3", ...plane }],
    ...extra
  };
}

// A map that has started and loaded its style.
function readyMap(message = planeMessage()) {
  const flightMap = new window.FlightMap(container);
  flightMap.show(message);
  const map = fakes.maps[fakes.maps.length - 1];
  map.finishLoading();
  return { flightMap, map };
}

beforeEach(async () => {
  vi.resetModules();
  fakes = installMapFakes();
  container = document.createElement("div");
  await load("map");
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("a plane in an emergency", () => {
  const emergency = { kind: "general", squawk: "7700", label: "General emergency" };

  it("draws the world map under the street map, once, for a plane that may be far beyond it", () => {
    const { flightMap, map } = readyMap(planeMessage({ emergency, lat: 52.2 }));
    expect(map.sources.world).toBeDefined();
    expect(map.layers.filter((layer) => layer.source === "world")).toEqual([
      { id: "world-earth", type: "fill", source: "world", "source-layer": "earth", before: "earth" }
    ]);
    flightMap.show(planeMessage({ emergency, lat: 52.1 }));
    expect(map.layers.filter((layer) => layer.source === "world")).toHaveLength(1);
    expect(map.lastBounds.points).toContainEqual([0.03, 52.1]);
  });

  it("leaves the world map out for an ordinary plane", () => {
    const { map } = readyMap();
    expect(map.sources.world).toBeUndefined();
  });
});

describe("starting the map", () => {
  it("waits for the style to load, then draws the plane that arrived meanwhile", () => {
    const flightMap = new window.FlightMap(container);
    flightMap.show(planeMessage());
    const map = fakes.maps[0];
    expect(map.options.center).toEqual([0, 51.4769]);
    expect(map.options.interactive).toBe(false);
    expect(map.options.style.sources.protomaps.url).toMatch(/^pmtiles:\/\/.*\/map\/area\.pmtiles$/);
    expect(map.options.style.glyphs).toMatch(/vendor\/fonts\/\{fontstack\}\/\{range\}\.pbf$/);
    expect(fakes.protocols[0].name).toBe("pmtiles");
    expect(map.sources.trail).toBeUndefined();

    map.finishLoading();
    expect(map.layers.map((layer) => layer.id)).toEqual(["zone", "trail", "bound", "ahead"]);
    expect(map.eased).toHaveLength(1);
  });

  it("keeps only the latest update while the style is loading", () => {
    const flightMap = new window.FlightMap(container);
    flightMap.show(planeMessage({ lon: 0.03 }));
    flightMap.show(planeMessage({ lon: 0.02 }));
    expect(fakes.maps).toHaveLength(1);
    fakes.maps[0].finishLoading();
    expect(fakes.maps[0].sources.trail.data.geometry.coordinates).toEqual([[0.02, 51.48]]);
  });

  it("puts home on the map as a marker", () => {
    const flightMap = new window.FlightMap(container);
    flightMap.show(planeMessage());
    expect(flightMap._homeMarker.lngLat).toEqual([0, 51.4769]);
    expect(flightMap._homeMarker.element.className).toBe("map-home");
  });

  it("logs map errors without stopping", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const flightMap = new window.FlightMap(container);
    flightMap.show(planeMessage());
    fakes.maps[0].handlers.error({ error: new Error("tile 404") });
    fakes.maps[0].handlers.error({});
    expect(warn).toHaveBeenNthCalledWith(1, "map:", "tile 404");
    expect(warn).toHaveBeenNthCalledWith(2, "map:", undefined);
  });

  it("gives up for good, and says so on the card, when the map cannot start", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    vi.stubGlobal("pmtiles", { Protocol: class { constructor() { throw new Error("no pmtiles"); } } });
    const flightMap = new window.FlightMap(container);
    flightMap.show(planeMessage());
    flightMap.show(planeMessage());
    expect(container.classList.contains("failed")).toBe(true);
    expect(warn).toHaveBeenCalledTimes(1);
    expect(fakes.maps).toHaveLength(0);
  });

  it("does not start for an update without home or a position", () => {
    const flightMap = new window.FlightMap(container);
    flightMap.show(planeMessage({}, { home: null }));
    flightMap.show(planeMessage({ lat: null }));
    flightMap.show(planeMessage({ lon: undefined }));
    expect(fakes.maps).toHaveLength(0);
  });
});

describe("drawing the nearest plane", () => {
  it("marks the plane, the zone around home and its trail as it flies", () => {
    const { flightMap, map } = readyMap();
    expect(flightMap._planeMarker.lngLat).toEqual([0.03, 51.48]);
    expect(flightMap._planeMarker.rotation).toBe(90);
    expect(flightMap._planeMarker.map).toBe(map);
    const zone = map.sources.zone.data.geometry.coordinates[0];
    expect(zone).toHaveLength(65);
    expect(zone[64][0]).toBeCloseTo(zone[0][0], 9);
    expect(zone[64][1]).toBeCloseTo(zone[0][1], 9);

    flightMap.show(planeMessage({ lon: 0.02 }));
    flightMap.show(planeMessage({ lon: 0.01 }));
    expect(map.sources.trail.data.geometry.coordinates).toEqual([[0.03, 51.48], [0.02, 51.48], [0.01, 51.48]]);
  });

  it("draws the way the plane is heading as a line running off the map", () => {
    const { map } = readyMap(planeMessage({ trackDeg: 0 }));
    const [start, end] = map.sources.ahead.data.geometry.coordinates;
    expect(start).toEqual([0.03, 51.48]);
    expect(end[0]).toBeCloseTo(0.03, 6);
    expect(end[1]).toBeGreaterThan(51.48 + 0.3);
  });

  it("draws no heading and an upright plane when the track is unknown", () => {
    const { flightMap, map } = readyMap(planeMessage({ trackDeg: null }));
    expect(map.sources.ahead.data.geometry.coordinates).toEqual([]);
    expect(flightMap._planeMarker.rotation).toBe(0);
  });

  it("starts a new trail when a different plane becomes the nearest", () => {
    const { flightMap, map } = readyMap();
    flightMap.show(planeMessage({ lon: 0.02 }));
    flightMap.show(planeMessage({ hex: "def456", lon: 0.01 }));
    expect(map.sources.trail.data.geometry.coordinates).toEqual([[0.01, 51.48]]);
  });

  it("starts afresh with the same plane once it has been forgotten", () => {
    const { flightMap, map } = readyMap();
    flightMap.show(planeMessage({ lon: 0.02 }));
    flightMap.forget();
    flightMap.show(planeMessage({ lon: 0.01 }));
    expect(map.sources.trail.data.geometry.coordinates).toEqual([[0.01, 51.48]]);
    expect(map.eased[2].duration).toBe(0);
  });

  it("drops an update that was waiting for the style once forgotten", () => {
    const flightMap = new window.FlightMap(container);
    flightMap.show(planeMessage());
    flightMap.forget();
    const map = fakes.maps[0];
    map.finishLoading();
    expect(map.eased).toEqual([]);
  });

  it("jumps to a new plane but glides between updates of the same one", () => {
    const { flightMap, map } = readyMap();
    expect(map.eased[0].duration).toBe(0);
    flightMap.show(planeMessage({ lon: 0.02 }));
    expect(map.eased[1].duration).toBe(1000);
    expect(map.eased[1].easing(0.3)).toBe(0.3);
    flightMap.show(planeMessage({ hex: "def456" }));
    expect(map.eased[2].duration).toBe(0);
  });

  it("frames home with room round it and the plane, never closer than the zone", () => {
    const { map } = readyMap();
    expect(map.lastBoundsOptions).toEqual({ padding: 60, maxZoom: 14 });
    const [southWest, northEast, plane] = map.lastBounds.points;
    expect(southWest[0]).toBeLessThan(-0.02);
    expect(northEast[0]).toBeGreaterThan(0.02);
    expect(plane).toEqual([0.03, 51.48]);
  });

  it("frames a helicopter closer, with home, the helicopter and the whole trail it has flown", () => {
    const { flightMap, map } = readyMap(planeMessage({ category: "A7", lon: 0.01 }));
    flightMap.show(planeMessage({ category: "A7", lon: 0.012, lat: 51.479 }));
    const [southWest, northEast, ...trail] = map.lastBounds.points;
    expect(southWest[0]).toBeGreaterThan(-0.01);
    expect(northEast[0]).toBeLessThan(0.01);
    expect(trail).toEqual([[0.01, 51.48], [0.012, 51.479]]);
  });

  it("leaves the camera alone when the map cannot frame the bounds", () => {
    const { flightMap, map } = readyMap();
    map.camera = null;
    flightMap.show(planeMessage({ lon: 0.02 }));
    expect(map.eased).toHaveLength(1);
  });
});

describe("the airport it is heading for", () => {
  const destination = { code: "LHR", lat: 51.471, lon: -0.462 };

  it("draws a line to the airport and labels it with its code", () => {
    const { flightMap, map } = readyMap(planeMessage({ destination }));
    expect(map.sources.bound.data.geometry.coordinates).toEqual([[0.03, 51.48], [-0.462, 51.471]]);
    expect(flightMap._airportMarker.getElement().textContent).toBe("LHR");
    expect(flightMap._airportMarker.map).toBe(map);
  });

  it("labels an airport with no code with nothing", () => {
    const { flightMap } = readyMap(planeMessage({ destination: { lat: 1, lon: 2 } }));
    expect(flightMap._airportMarker.getElement().textContent).toBe("");
  });

  it("takes the line and label away when the airport's position is not known", () => {
    for (const unknown of [null, { code: "LHR" }, { code: "LHR", lat: 51.4 }, { code: "LHR", lon: 0.1 }]) {
      const { flightMap, map } = readyMap(planeMessage({ destination }));
      flightMap.show(planeMessage({ destination: unknown }));
      expect(map.sources.bound.data.geometry.coordinates).toEqual([]);
      expect(flightMap._airportMarker.map).toBeNull();
    }
  });
});

describe("the other planes around", () => {
  const other = (hex, extra = {}) => ({ hex, lat: 51.49, lon: 0.02, trackDeg: 180, category: "A3", ...extra });

  it("adds a smaller, dimmer marker for each, moved as it flies", () => {
    const { flightMap, map } = readyMap();
    flightMap.show(planeMessage({}, { others: [other("a1"), other("b2", { trackDeg: null })] }));
    const marker = flightMap._others.a1;
    expect(marker.map).toBe(map);
    expect(marker.element.className).toBe("map-plane other");
    expect(marker.rotation).toBe(180);
    expect(flightMap._others.b2.rotation).toBe(0);

    flightMap.show(planeMessage({}, { others: [other("a1", { lon: 0.05 }), other("b2")] }));
    expect(flightMap._others.a1).toBe(marker);
    expect(marker.lngLat).toEqual([0.05, 51.49]);
  });

  it("drops a marker once its plane has gone", () => {
    const { flightMap } = readyMap();
    flightMap.show(planeMessage({}, { others: [other("a1"), other("b2")] }));
    const gone = flightMap._others.a1;
    flightMap.show(planeMessage({}, { others: [other("b2")] }));
    expect(gone.map).toBeNull();
    expect(Object.keys(flightMap._others)).toEqual(["b2"]);
    flightMap.show(planeMessage());
    expect(Object.keys(flightMap._others)).toEqual([]);
  });

  it("skips a plane whose position is not known", () => {
    const { flightMap } = readyMap();
    flightMap.show(planeMessage({}, { others: [other("a1", { lat: null }), other("b2", { lon: null })] }));
    expect(Object.keys(flightMap._others)).toEqual([]);
  });
});

describe("the shape of a plane", () => {
  function shapeOf(plane, size = "plane") {
    const element = document.createElement("div");
    window.PlaneShapes.dress(element, plane, size === "plane" ? 7 : 4.5);
    return element;
  }
  const path = (element) => element.querySelector("path").getAttribute("d");

  it("draws an airliner for a jet", () => {
    const jet = shapeOf({ category: "A3", typeCode: "A320" });
    expect(jet.dataset.kind).toBe("jet");
    expect(jet.style.width).toBe("7vh");
    expect(jet.style.height).toBe("7vh");
  });

  it("draws a bigger plane with extra engines for a heavy", () => {
    const heavy = shapeOf({ category: "A5" });
    expect(heavy.dataset.kind).toBe("heavy");
    expect(path(heavy).length).toBeGreaterThan(path(shapeOf({ category: "A3" })).length);
    expect(heavy.style.width).toBe("9.1vh");
  });

  it("draws a helicopter for a helicopter or a rotorcraft", () => {
    expect(shapeOf({ helicopter: true, category: "A3" }).dataset.kind).toBe("helicopter");
    expect(shapeOf({ category: "A7" }).dataset.kind).toBe("helicopter");
  });

  it("draws straight wings for a light aircraft or a turboprop", () => {
    expect(shapeOf({ category: "A1" }).dataset.kind).toBe("prop");
    expect(shapeOf({ category: "A2", typeCode: "DH8D" }).dataset.kind).toBe("prop");
  });

  it("draws an airliner when the type and category are not known", () => {
    const unknown = shapeOf({});
    expect(unknown.dataset.kind).toBe("jet");
    expect(unknown.style.width).toBe("7vh");
  });

  it("sizes the other planes smaller", () => {
    expect(shapeOf({ category: "A3" }, "other").style.width).toBe("4.5vh");
  });

  it("marks the service whose colours the plane wears", () => {
    expect(shapeOf({ category: "A7", service: "ambulance" }).dataset.service).toBe("ambulance");
    expect(shapeOf({ category: "A3" }).dataset.service).toBe("");
  });

  it("does not redraw a plane whose shape has not changed, but does when it has", () => {
    const element = shapeOf({ category: "A3" });
    const svg = element.querySelector("svg");
    window.PlaneShapes.dress(element, { category: "A3", service: "police" }, 7);
    expect(element.querySelector("svg")).toBe(svg);
    expect(element.dataset.service).toBe("police");
    window.PlaneShapes.dress(element, { category: "A5" }, 7);
    expect(element.querySelector("svg")).not.toBe(svg);
  });
});
