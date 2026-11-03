import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { installMapFakes, load } from "./support.js";

let fakes;
let container;

const LONDON = { code: "LHR", lat: 51.471, lon: -0.462 };
const BERLIN = { code: "BER", lat: 52.362, lon: 13.501 };

function flight(extra = {}) {
  return { ident: "BA4321", origin: LONDON, destination: BERLIN, ...extra };
}

function readyMap(first = flight(), position = null) {
  const routeMap = new window.RouteMap(container);
  routeMap.show(first, position);
  const map = fakes.maps[fakes.maps.length - 1];
  map.finishLoading();
  return { routeMap, map };
}

const coordinates = (source) => source.data.geometry.coordinates;

beforeEach(async () => {
  vi.resetModules();
  fakes = installMapFakes();
  container = document.createElement("div");
  window.PlaneShapes = { dress: vi.fn() };
  await load("routemap");
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  delete window.PlaneShapes;
});

describe("starting the route map", () => {
  it("draws from the world map and waits for the style before drawing the flight", () => {
    const routeMap = new window.RouteMap(container);
    routeMap.show(flight(), null);
    const map = fakes.maps[0];
    expect(map.options.style.sources.protomaps.url).toMatch(/map\/world\.pmtiles$/);
    expect(map.options.interactive).toBe(false);
    expect(map.sources.route).toBeUndefined();
    map.finishLoading();
    expect(map.layers.map((layer) => layer.id)).toEqual(["route", "flown"]);
    expect(coordinates(map.sources.route)).toHaveLength(65);
  });

  it("draws the plane marker with the airliner shape", () => {
    const routeMap = new window.RouteMap(container);
    routeMap.show(flight(), null);
    expect(window.PlaneShapes.dress).toHaveBeenCalledWith(routeMap._planeMarker.getElement(), { category: "A3" }, 6);
    expect(routeMap._planeMarker.getElement().className).toBe("map-plane");
  });

  it("draws the latest flight once the style has loaded", () => {
    const routeMap = new window.RouteMap(container);
    routeMap.show(flight({ ident: "A" }), null);
    routeMap.show(flight({ ident: "B" }), null);
    expect(fakes.maps).toHaveLength(1);
    fakes.maps[0].finishLoading();
    expect(routeMap._ident).toBe("B");
  });

  it("logs map errors without stopping", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const routeMap = new window.RouteMap(container);
    routeMap.show(flight(), null);
    fakes.maps[0].handlers.error({ error: new Error("tile 404") });
    fakes.maps[0].handlers.error({});
    expect(warn).toHaveBeenNthCalledWith(1, "route map:", "tile 404");
    expect(warn).toHaveBeenNthCalledWith(2, "route map:", undefined);
  });

  it("gives up for good, and says so on the card, when the map cannot start", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    vi.stubGlobal("pmtiles", { Protocol: class { constructor() { throw new Error("no pmtiles"); } } });
    const routeMap = new window.RouteMap(container);
    routeMap.show(flight(), null);
    routeMap.show(flight(), null);
    expect(container.classList.contains("failed")).toBe(true);
    expect(warn).toHaveBeenCalledTimes(1);
  });

  it("does not start until both airports have a position", () => {
    const routeMap = new window.RouteMap(container);
    routeMap.show(flight({ origin: null }), null);
    routeMap.show(flight({ destination: null }), null);
    routeMap.show(flight({ origin: { code: "LHR", lat: 51 } }), null);
    routeMap.show(flight({ destination: { code: "BER", lon: 13 } }), null);
    expect(fakes.maps).toHaveLength(0);
  });
});

describe("drawing a flight's route", () => {
  it("draws the great circle between the airports and labels both ends", () => {
    const { routeMap, map } = readyMap();
    const route = coordinates(map.sources.route);
    expect(route[0][0]).toBeCloseTo(-0.462, 6);
    expect(route[0][1]).toBeCloseTo(51.471, 6);
    expect(route[64][0]).toBeCloseTo(13.501, 6);
    expect(route[64][1]).toBeCloseTo(52.362, 6);
    // A great circle between two places at this latitude bulges north of the straight line.
    expect(route[32][1]).toBeGreaterThan(52.0);
    expect(routeMap._fromMarker.getElement().textContent).toBe("LHR");
    expect(routeMap._toMarker.getElement().textContent).toBe("BER");
    expect(routeMap._fromMarker.lngLat).toEqual([-0.462, 51.471]);
    expect(routeMap._toMarker.map).toBe(map);
    expect(map.resized).toBe(1);
  });

  it("draws a straight line when both airports are in the same place", () => {
    const { map } = readyMap(flight({ destination: { ...LONDON, code: "LON" } }));
    expect(coordinates(map.sources.route)).toEqual([[-0.462, 51.471], [-0.462, 51.471]]);
  });

  it("labels an airport with no code with nothing", () => {
    const { routeMap } = readyMap(flight({ origin: { lat: 1, lon: 2 }, destination: { lat: 3, lon: 4 } }));
    expect(routeMap._fromMarker.getElement().textContent).toBe("");
    expect(routeMap._toMarker.getElement().textContent).toBe("");
  });

  it("draws the part flown and the plane where it is, pointing the way it is heading", () => {
    const { routeMap, map } = readyMap(flight(), { lat: 53, lon: 5, trackDeg: 80 });
    const flown = coordinates(map.sources.flown);
    expect(flown[64][0]).toBeCloseTo(5, 6);
    expect(flown[64][1]).toBeCloseTo(53, 6);
    expect(routeMap._planeMarker.lngLat).toEqual([5, 53]);
    expect(routeMap._planeMarker.rotation).toBe(80);
    expect(routeMap._planeMarker.map).toBe(map);
  });

  it("keeps the plane upright when its track is not known", () => {
    const { routeMap } = readyMap(flight(), { lat: 53, lon: 5 });
    expect(routeMap._planeMarker.rotation).toBe(0);
  });

  it("shows no plane and nothing flown when the position is not known", () => {
    for (const position of [null, { lon: 5 }, { lat: 53 }]) {
      const { routeMap, map } = readyMap(flight(), { lat: 53, lon: 5 });
      routeMap.show(flight(), position);
      expect(coordinates(map.sources.flown)).toEqual([]);
      expect(routeMap._planeMarker.map).toBeNull();
    }
  });

  it("fits the whole route in view for a new flight, then leaves the view alone", () => {
    const { routeMap, map } = readyMap();
    expect(map.fitted).toHaveLength(1);
    expect(map.fitted[0].options).toEqual({ padding: 70, maxZoom: 6, duration: 0 });
    expect(map.fitted[0].bounds.points).toEqual([[-0.462, 51.471], [-0.462, 51.471], [13.501, 52.362]]);
    routeMap.show(flight(), { lat: 53, lon: 5 });
    expect(map.fitted).toHaveLength(1);
    routeMap.show(flight({ ident: "BA1" }), null);
    expect(map.fitted).toHaveLength(2);
  });
});
