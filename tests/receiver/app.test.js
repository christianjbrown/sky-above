import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { installAudioFake, installCastFake, installMapFakes, load, mountCard } from "./support.js";

const NAMESPACE = "urn:x-cast:sky-above";
const NOW = new Date("2026-06-01T12:00:00Z");

let fakes;
let played;
let context;

const text = (id) => document.getElementById(id).textContent;
const html = (id) => document.getElementById(id).innerHTML;
const screenClasses = () => Array.from(document.getElementById("screen").classList).sort();

// Opens the page the way a browser or the Hub would, and loads the scripts in index.html's order.
async function open({ query = "", hub = false } = {}) {
  vi.resetModules();
  window.history.pushState({}, "", "/" + query);
  mountCard();
  if (hub) {
    vi.spyOn(window.navigator, "userAgent", "get").mockReturnValue("Mozilla/5.0 (Linux) CrKey/1.56.500000");
    context = installCastFake();
  }
  await load("parts", "map", "routemap", "followed", "speaker", "app");
}

function deliver(message) {
  context.handlers[NAMESPACE]({ data: message });
}

function planesMessage(plane = {}, extra = {}) {
  return {
    type: "planes",
    homeCountry: "GB",
    radiusKm: 1.5,
    home: { lat: 51.4769, lon: 0 },
    planes: [{
      hex: "4ca7b5",
      callsign: "BAW86S",
      flightNumber: "BA86S",
      airline: "British Airways",
      airlineCode: "BAW",
      category: "A3",
      origin: { code: "PRG", city: "Prague", country: "CZ" },
      destination: { code: "LHR", city: "London", country: "GB" },
      aircraft: "Airbus A320",
      typeCode: "A320",
      altitudeFt: 4350,
      speedKt: 214,
      verticalRateFpm: 0,
      distanceKm: 8,
      lat: 51.48,
      lon: 0.03,
      ...plane
    }],
    ...extra
  };
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(NOW);
  fakes = installMapFakes();
  played = installAudioFake();
  vi.spyOn(console, "warn").mockImplementation(() => {});
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  delete document.hidden;
});

describe("on the Hub", () => {
  beforeEach(() => open({ hub: true }));

  it("starts the Cast receiver on the card's own channel, and never lets it time out", () => {
    expect(text("waiting-line")).toBe("Here comes a plane…");
    expect(context.started.disableIdleTimeout).toBe(true);
    expect(context.started.customNamespaces).toEqual({ [NAMESPACE]: "JSON" });
  });

  it("draws the nearest plane from the watcher's message", () => {
    deliver(planesMessage({ verticalRateFpm: -704 }));
    expect(text("airline")).toBe("British Airways");
    expect(text("flight")).toBe("BA86S");
    expect(text("route-from")).toContain("\u{1F1E8}\u{1F1FF} Prague (PRG)");
    expect(text("route-to")).toContain("London (LHR)");
    expect(text("aircraft")).toBe("Airbus A320");
    expect(text("note")).toBe("");
    expect(text("stat-1-label")).toBe("Altitude");
    expect(html("stat-1")).toBe('1.3<small>km ↘</small><span class="imperial">4,350 ft</span>');
    expect(html("stat-2")).toBe('396<small>km/h</small><span class="imperial">246 mph</span>');
    expect(html("stat-3")).toBe("8.0<small>km</small>");
    expect(screenClasses()).toEqual([]);
  });

  it("shows a climbing plane with an arrow up, and a low one in metres", () => {
    deliver(planesMessage({ verticalRateFpm: 900 }));
    expect(html("stat-1")).toContain("<small>km ↗</small>");
    deliver(planesMessage({ altitudeFt: 300, verticalRateFpm: -100, distanceKm: 0.5 }));
    expect(html("stat-1")).toBe('91<small>m</small><span class="imperial">300 ft</span>');
    expect(html("stat-3")).toBe("500<small>m</small>");
  });

  it("shows a dash for an altitude or speed that is not known", () => {
    deliver(planesMessage({ altitudeFt: null, speedKt: null }));
    expect(html("stat-1")).toBe("-");
    expect(html("stat-2")).toBe("-");
  });

  it("falls back to the callsign, registration, hex code and type when names are missing", () => {
    deliver(planesMessage({ airline: undefined, flightNumber: undefined, aircraft: undefined }));
    expect(text("airline")).toBe("BAW86S");
    expect(text("flight")).toBe("BAW86S");
    expect(text("aircraft")).toBe("A320");
    deliver(planesMessage({ airline: undefined, callsign: undefined, flightNumber: undefined, registration: "G-EUYM", aircraft: undefined, typeCode: undefined }));
    expect(text("airline")).toBe("");
    expect(text("flight")).toBe("G-EUYM");
    expect(text("aircraft")).toBe("");
    deliver(planesMessage({ callsign: undefined, flightNumber: undefined, registration: undefined }));
    expect(text("flight")).toBe("4CA7B5");
  });

  it("leaves out the flag of home's own country", () => {
    deliver(planesMessage());
    expect(text("route-to")).not.toContain("\u{1F1EC}\u{1F1E7}");
  });

  it("dresses the card for an air ambulance, then undresses it for an airliner", () => {
    deliver(planesMessage({ service: "ambulance", helicopter: true }));
    expect(screenClasses()).toEqual(["service-ambulance"]);
    deliver(planesMessage());
    expect(screenClasses()).toEqual([]);
  });

  it("takes the waiting message away when the first plane arrives", () => {
    expect(screenClasses()).toEqual(["waiting"]);
    deliver(planesMessage());
    expect(screenClasses()).toEqual([]);
  });

  it("puts the plane on the map", () => {
    deliver(planesMessage());
    expect(fakes.maps).toHaveLength(1);
    fakes.maps[0].finishLoading();
    expect(fakes.maps[0].sources.trail.data.geometry.coordinates).toEqual([[0.03, 51.48]]);
  });

  it("still draws the card when the map breaks", () => {
    vi.spyOn(window.FlightMap.prototype, "show").mockImplementation(() => { throw new Error("no map"); });
    deliver(planesMessage());
    expect(console.warn).toHaveBeenCalledWith("map:", expect.any(Error));
    expect(text("flight")).toBe("BA86S");
  });

  it("ignores messages that are not about a plane", () => {
    deliver(null);
    deliver({ type: "other" });
    deliver({ type: "planes" });
    deliver({ type: "planes", planes: [] });
    deliver({ type: "followed" });
    expect(screenClasses()).toEqual(["waiting"]);
    expect(text("flight")).toBe("");
  });

  it("draws a followed flight, and goes back to the plane overhead when one arrives", () => {
    deliver({
      type: "followed",
      homeCountry: "GB",
      homeTimezone: "Europe/London",
      flight: { ident: "BA4321", airline: "British Airways", airlineCode: "BAW", phase: "arrived", landsAt: NOW.toISOString() },
      position: null
    });
    expect(screenClasses()).toEqual(["followed"]);
    expect(text("flight")).toBe("BA4321");
    expect(text("aircraft")).toBe("At the gate");

    deliver(planesMessage({ service: "police" }));
    expect(screenClasses()).toEqual(["service-police"]);
    expect(text("flight")).toBe("BA86S");
    // The followed card is no longer redrawn every second over the plane overhead.
    vi.advanceTimersByTime(2000);
    expect(text("flight")).toBe("BA86S");
  });

  it("clears a service colour when a followed flight takes over", () => {
    deliver(planesMessage({ service: "military" }));
    deliver({ type: "followed", homeTimezone: "Europe/London", flight: { ident: "BA1", phase: "waiting" } });
    expect(screenClasses()).toEqual(["followed"]);
  });

  it("plays the announcement that comes with a message", () => {
    deliver(planesMessage({}, { speech: "clips/one.mp3" }));
    vi.advanceTimersByTime(0);
    expect(played).toEqual(["clips/one.mp3"]);
    deliver({ type: "followed", homeTimezone: "Europe/London", flight: { ident: "BA1", phase: "waiting" }, speech: "clips/two.mp3" });
    vi.advanceTimersByTime(0);
    expect(played).toEqual(["clips/one.mp3", "clips/two.mp3"]);
  });

  it("holds the announcement while the Hub is muted for the launch", () => {
    context.volume = { muted: true };
    deliver(planesMessage({}, { speech: "clips/one.mp3" }));
    vi.advanceTimersByTime(5000);
    expect(played).toEqual([]);
    context.volume = { muted: false };
    context.listeners.volume({ data: { muted: false } });
    vi.advanceTimersByTime(2000);
    expect(played).toEqual(["clips/one.mp3"]);
  });
});

describe("telling the watcher the card is hidden", () => {
  const setHidden = (hidden) => {
    Object.defineProperty(document, "hidden", { configurable: true, get: () => hidden });
    document.dispatchEvent(new Event("visibilitychange"));
  };

  beforeEach(() => open({ hub: true }));

  it("reports it once the card has stayed hidden for a few seconds", () => {
    setHidden(true);
    vi.advanceTimersByTime(2999);
    expect(context.sent).toEqual([]);
    vi.advanceTimersByTime(1);
    expect(context.sent).toEqual([{ namespace: NAMESPACE, sender: undefined, message: { type: "hidden" } }]);
  });

  it("says nothing when the card comes back before then", () => {
    setHidden(true);
    vi.advanceTimersByTime(1000);
    setHidden(false);
    vi.advanceTimersByTime(5000);
    expect(context.sent).toEqual([]);
  });
});

describe("in an ordinary browser", () => {
  let responses;

  beforeEach(async () => {
    responses = [];
    vi.stubGlobal("fetch", vi.fn(() => responses.shift()()));
  });

  it("follows the card from the Pi once a second", async () => {
    responses.push(() => Promise.resolve({ ok: true, json: () => Promise.resolve(planesMessage()) }));
    responses.push(() => Promise.resolve({ ok: true, json: () => Promise.resolve(planesMessage({ flightNumber: "BA87" })) }));
    await open();
    await vi.advanceTimersByTimeAsync(0);
    expect(fetch).toHaveBeenCalledWith("live/planes.json", { cache: "no-store" });
    expect(text("flight")).toBe("BA86S");
    await vi.advanceTimersByTimeAsync(1000);
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(text("flight")).toBe("BA87");
  });

  it("keeps asking after an answer that is not OK, or no answer at all", async () => {
    responses.push(() => Promise.resolve({ ok: false }));
    responses.push(() => Promise.reject(new Error("offline")));
    responses.push(() => Promise.resolve({ ok: true, json: () => Promise.resolve(planesMessage()) }));
    await open();
    await vi.advanceTimersByTimeAsync(0);
    expect(screenClasses()).toEqual(["waiting"]);
    await vi.advanceTimersByTimeAsync(1000);
    expect(screenClasses()).toEqual(["waiting"]);
    await vi.advanceTimersByTimeAsync(1000);
    expect(fetch).toHaveBeenCalledTimes(3);
    expect(text("flight")).toBe("BA86S");
  });

  it("speaks as soon as the clip arrives, there being no Hub to unmute", async () => {
    responses.push(() => Promise.resolve({ ok: true, json: () => Promise.resolve(planesMessage({}, { speech: "clips/one.mp3" })) }));
    await open();
    await vi.advanceTimersByTimeAsync(0);
    expect(played).toEqual(["clips/one.mp3"]);
  });
});

describe("the demo plane", () => {
  it("shows a made-up plane that flies in over home and out again", async () => {
    await open({ query: "?demo=" });
    expect(text("flight")).toBe("BA86S");
    expect(text("airline")).toBe("British Airways");
    expect(html("stat-3")).toBe("8.0<small>km</small>");
    vi.advanceTimersByTime(4000);
    expect(html("stat-3")).toBe("7.0<small>km</small>");
    // It passes overhead, goes on to the west, then starts again from the east.
    vi.advanceTimersByTime(53000);
    expect(html("stat-3")).toBe("8.0<small>km</small>");
  });

  it("shows the other planes around it, one of them a police helicopter", async () => {
    await open({ query: "?demo=" });
    fakes.maps[0].finishLoading();
    const helicopter = fakes.markers.find((marker) => marker.element.className === "map-plane other" && marker.element.dataset.category === "A7");
    expect(helicopter.element.dataset.service).toBe("police");
  });

  it.each([
    ["ambulance", "HLE27", "Air ambulance", "police"],
    ["police", "UKP15", "Police", "ambulance"],
    ["military", "RRR4321", "Royal Air Force", "police"]
  ])("shows the %s demo in its own colours", async (which, callsign, airline, otherHelicopter) => {
    await open({ query: "?demo=" + which });
    expect(screenClasses()).toEqual(["service-" + which]);
    expect(text("airline")).toBe(airline);
    expect(text("flight")).toBe(callsign);
    expect(text("route-from")).toBe("");
    fakes.maps[0].finishLoading();
    const helicopter = fakes.markers.find((marker) => marker.element.className === "map-plane other" && marker.element.dataset.category === "A7");
    expect(helicopter.element.dataset.service).toBe(otherHelicopter);
  });

  it("treats an unknown demo name as the plain demo plane", async () => {
    await open({ query: "?demo=banana" });
    expect(text("flight")).toBe("BA86S");
    expect(screenClasses()).toEqual([]);
  });
});

describe("the demo followed flight", () => {
  const london = (minutes) => new Date(NOW.getTime() + minutes * 60000).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", timeZone: "Europe/London" });

  it("shows a flight waiting to leave on a plane that is itself late", async () => {
    await open({ query: "?demo=followed" });
    expect(screenClasses()).toEqual(["followed"]);
    expect(text("flight")).toBe("BA4321");
    expect(text("aircraft")).toBe("Likely delayed 25 min · A320 G-EUYM");
    expect(text("note")).toBe("Its plane isn't due in from Berlin until " + london(100));
    expect(text("stat-1-label")).toBe("Departs in");
  });

  it("shows a flight that has left the gate late", async () => {
    await open({ query: "?demo=taxiing" });
    expect(text("aircraft")).toBe("Leaving the gate, 106 min late · A320 G-EUYM");
    expect(text("stat-1-label")).toBe("Left the gate");
  });

  it("shows a flight over the North Sea", async () => {
    await open({ query: "?demo=flying" });
    expect(text("aircraft")).toBe("In the air, on time · A320 G-EUYM");
    expect(text("note")).toBe("37,000 ft · 837 km/h");
    expect(text("stat-1-label")).toBe("Lands in");
  });

  it("shows a flight at the gate", async () => {
    await open({ query: "?demo=landed" });
    expect(text("aircraft")).toBe("At the gate · A320 G-EUYM");
    expect(text("stat-2-label")).toBe("Baggage belt");
    expect(text("stat-2")).toBe("7");
  });
});
