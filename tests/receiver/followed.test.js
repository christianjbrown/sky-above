import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { load, mountCard } from "./support.js";

const NOW = new Date("2026-06-01T12:00:00Z");
const HOME = "Europe/London";

let routeMap;
let card;

const at = (minutes) => new Date(NOW.getTime() + minutes * 60000).toISOString();
const text = (id) => document.getElementById(id).textContent;
const html = (id) => document.getElementById(id).innerHTML;
// A figure's big value, and the smaller line under it.
function figure(id) {
  const copy = document.getElementById(id).cloneNode(true);
  const under = copy.querySelector(".imperial");
  const small = under ? under.textContent : "";
  if (under) { under.remove(); }
  return [copy.textContent, small];
}
const main = (id) => figure(id)[0];
const stats = () => [1, 2, 3].map((n) => [text("stat-" + n + "-label"), ...figure("stat-" + n)]);

const LONDON = { code: "LHR", city: "London", country: "GB", timezone: "Europe/London", lat: 51.471, lon: -0.462 };
const BERLIN = { code: "BER", city: "Berlin", country: "DE", timezone: "Europe/Berlin", lat: 52.362, lon: 13.501 };

function message(flight = {}, extra = {}) {
  return {
    type: "followed",
    homeTimezone: HOME,
    flight: { ident: "BA4321", airline: "British Airways", airlineCode: "BAW", phase: "waiting", origin: LONDON, destination: BERLIN, ...flight },
    earlierLegs: [],
    reason: null,
    position: null,
    ...extra
  };
}

function show(flight, extra) {
  card.show(message(flight, extra));
}

beforeEach(async () => {
  vi.resetModules();
  vi.useFakeTimers();
  vi.setSystemTime(NOW);
  mountCard();
  await load("parts", "followed");
  routeMap = { show: vi.fn() };
  card = new window.FollowedCard(window.CardParts, routeMap, 0.45);
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("the header", () => {
  it("shows the airline, flight number, route and logo", () => {
    show();
    expect(text("airline")).toBe("British Airways");
    expect(text("flight")).toBe("BA4321");
    expect(text("route-to")).toContain("Berlin (BER)");
    expect(document.getElementById("logo").getAttribute("src")).toBe("logos/BAW.svg");
  });

  it("falls back to the airline's code, then to nothing", () => {
    show({ airline: undefined });
    expect(text("airline")).toBe("BAW");
    show({ airline: undefined, airlineCode: undefined });
    expect(text("airline")).toBe("");
  });

  it("gives the route map the flight and its position", () => {
    const position = { lat: 53, lon: 5, trackDeg: 90 };
    show({}, { position });
    expect(routeMap.show).toHaveBeenCalledWith(expect.objectContaining({ ident: "BA4321" }), position);
  });

  it("carries on drawing the card when the route map fails", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    routeMap.show.mockImplementation(() => { throw new Error("no map"); });
    show();
    expect(warn).toHaveBeenCalledWith("route map:", expect.any(Error));
    expect(text("flight")).toBe("BA4321");
  });
});

describe("the status line", () => {
  it("says on time before departure, with the plane after a dot", () => {
    show({ aircraftType: "A320", registration: "G-EUYM" });
    expect(text("aircraft")).toBe("On time · A320 G-EUYM");
  });

  it("escapes the plane's details", () => {
    show({ aircraftType: "<b>A&B</b>", registration: 'G"X' });
    expect(html("aircraft")).toContain('&lt;b&gt;A&amp;B&lt;/b&gt; G"X');
  });

  it("shows a delay to departure in red, and says when it is our own sum", () => {
    show({ departureDelayMinutes: 25 });
    expect(html("aircraft")).toBe('<span class="late">Delayed 25 min</span>');
    show({ departureDelayMinutes: 25, departureEstimate: "ours" });
    expect(html("aircraft")).toBe('<span class="late">Likely delayed 25 min</span>');
  });

  it("does not call a short delay late", () => {
    show({ departureDelayMinutes: 9 });
    expect(text("aircraft")).toBe("On time");
  });

  it("says cancelled in red, without the plane", () => {
    show({ phase: "cancelled", aircraftType: "A320" });
    expect(html("aircraft")).toBe('<span class="late">Cancelled</span>');
  });

  it("says diverted in red whatever the phase", () => {
    show({ phase: "flying", diverted: true });
    expect(html("aircraft")).toBe('<span class="late">Diverted</span>');
  });

  it("says when the flight has left the gate, late or not", () => {
    show({ phase: "taxiing", departureDelayMinutes: 40, arrivalDelayMinutes: 40 });
    expect(html("aircraft")).toBe('Leaving the gate, <span class="late">40 min late</span>');
    show({ phase: "taxiing", departureDelayMinutes: 0, arrivalDelayMinutes: 0 });
    expect(text("aircraft")).toBe("Leaving the gate");
  });

  it("says when the flight is in the air, late or on time", () => {
    show({ phase: "flying", departureDelayMinutes: 0, arrivalDelayMinutes: 30 });
    expect(html("aircraft")).toBe('In the air, <span class="late">30 min late</span>');
    show({ phase: "flying", departureDelayMinutes: 0, arrivalDelayMinutes: 0 });
    expect(text("aircraft")).toBe("In the air, on time");
  });

  it("says when the flight has landed and when it is at the gate", () => {
    show({ phase: "landed" });
    expect(text("aircraft")).toBe("Landed, taxiing in");
    show({ phase: "arrived" });
    expect(text("aircraft")).toBe("At the gate");
  });
});

describe("the note under the status", () => {
  it("gives the reason for a delay when there is one", () => {
    show({}, { reason: "Its plane is late" });
    expect(text("note")).toBe("Its plane is late");
  });

  it("says where a waiting flight's plane is coming from", () => {
    const leg = { origin: BERLIN, arrivesAt: at(100), arrivalDelayMinutes: 25 };
    show({}, { earlierLegs: [{ ...leg }] });
    expect(text("note")).toBe("The plane is still to leave Berlin, due in at 14:40, 25 min late");
    show({}, { earlierLegs: [{ ...leg, departed: true }] });
    expect(text("note")).toBe("The plane is on its way from Berlin, landing 14:40, 25 min late");
    show({}, { earlierLegs: [{ ...leg, departed: true, arrivalDelayMinutes: 3 }] });
    expect(text("note")).toBe("The plane is on its way from Berlin, landing 14:40");
    show({}, { earlierLegs: [{ ...leg, landed: true }] });
    expect(text("note")).toBe("The plane is here, in from Berlin at 14:40");
  });

  it("names the last stop when the plane's origin is not known", () => {
    show({}, { earlierLegs: [{ origin: null, arrivesAt: at(100), landed: true }] });
    expect(text("note")).toBe("The plane is here, in from its last stop at 14:40");
  });

  it("shows the altitude and speed of a flight in the air", () => {
    show({ phase: "flying" }, { position: { lat: 1, lon: 1, altitudeFt: 37000.4, speedKt: 450 } });
    expect(text("note")).toBe("37,000 ft · 833 km/h");
  });

  it("shows only the altitude when the speed is not known", () => {
    show({ phase: "flying" }, { position: { lat: 1, lon: 1, altitudeFt: 12000 } });
    expect(text("note")).toBe("12,000 ft");
  });

  it("has no note when there is nothing to say", () => {
    show({ phase: "waiting" });
    expect(text("note")).toBe("");
    show({ phase: "flying" });
    expect(text("note")).toBe("");
    show({ phase: "flying" }, { position: { lat: 1, lon: 1 } });
    expect(text("note")).toBe("");
    show({ phase: "landed" }, { position: { lat: 1, lon: 1, altitudeFt: 0 } });
    expect(text("note")).toBe("");
  });

  it("copes with a message that has no earlier legs", () => {
    const withoutLegs = message();
    delete withoutLegs.earlierLegs;
    card.show(withoutLegs);
    expect(text("note")).toBe("");
  });
});

describe("the three figures before departure", () => {
  it("counts down to departure and shows the gate and the landing time", () => {
    show({ departsAt: at(135), gateOrigin: "B32", terminalOrigin: "5", landsAt: at(230), arrivesAt: at(240) });
    expect(stats()).toEqual([
      ["Departs in", "2hrs 15mins", "15:15"],
      ["Gate", "B32", "Terminal 5"],
      ["Lands (scheduled)", "16:50", "17:50 in Berlin"]
    ]);
  });

  it("shows a late departure in red with the time it was due", () => {
    show({ departsAt: at(135), scheduledOut: at(110), departureDelayMinutes: 25, arrivalDelayMinutes: 20, landsAt: at(230) });
    expect(stats()[0]).toEqual(["Departs in", "2hrs 15mins", "15:15, was 14:50"]);
    expect(document.getElementById("stat-1-label").parentNode.classList.contains("late")).toBe(true);
    expect(stats()[2][0]).toBe("Lands (expected)");
    expect(html("stat-3")).toContain('<span class="late">16:50</span>');
  });

  it("uses singular units for one hour and one minute", () => {
    show({ departsAt: at(61) });
    expect(main("stat-1")).toBe("1hr 1min");
  });

  it("drops the minutes on the hour, and the hours within the hour", () => {
    show({ departsAt: at(120.5) });
    expect(main("stat-1")).toBe("2hrs");
    show({ departsAt: at(42.5) });
    expect(main("stat-1")).toBe("42mins");
  });

  it("says Now in the last minute, and a dash when there is no time", () => {
    show({ departsAt: at(0.5) });
    expect(main("stat-1")).toBe("Now");
    show({ departsAt: undefined });
    expect(main("stat-1")).toBe("-");
  });

  it("shows a dash for a gate that is not known, and the landing from the arrival time when needed", () => {
    show({ arrivesAt: at(240) });
    expect(main("stat-2")).toBe("-");
    expect(figure("stat-3")).toEqual(["17:00", "18:00 in Berlin"]);
  });

  it("shows no far-end time when the clocks agree there, or the airport is not known", () => {
    show({ landsAt: at(230), destination: { ...BERLIN, timezone: HOME } });
    expect(html("stat-3")).not.toContain(" in ");
    show({ landsAt: at(230), destination: { code: "BER" } });
    expect(html("stat-3")).not.toContain(" in ");
    show({ landsAt: at(230), destination: undefined });
    expect(html("stat-3")).not.toContain(" in ");
    show({ landsAt: undefined, arrivesAt: undefined });
    expect(text("stat-3")).toBe("-");
  });
});

describe("the three figures once under way", () => {
  it("shows how long since a flight left the gate", () => {
    show({ phase: "taxiing", departsAt: at(-35), departureDelayMinutes: 106, gateOrigin: "A1", landsAt: at(80), arrivalDelayMinutes: 52 });
    expect(stats()).toEqual([
      ["Left the gate", "12:25", "35 min ago"],
      ["Gate", "A1", ""],
      ["Lands (expected)", "14:20", "15:20 in Berlin"]
    ]);
    expect(document.getElementById("stat-1-label").parentNode.classList.contains("late")).toBe(true);
  });

  it("counts down to landing and shows the arrival gate", () => {
    show({ phase: "flying", landsAt: at(42), arrivesAt: at(50), arrivalDelayMinutes: 4, gateDestination: "C12", terminalDestination: "1" });
    expect(stats()).toEqual([
      ["Lands in", "42mins", "at 13:42"],
      ["At the gate", "13:50", "14:50 in Berlin"],
      ["Arrival gate", "C12", "Terminal 1"]
    ]);
  });

  it("shows a late arrival in red", () => {
    show({ phase: "flying", landsAt: at(42), arrivesAt: at(50), arrivalDelayMinutes: 30 });
    expect(html("stat-1")).toContain('at <span class="late">13:42</span>');
    expect(html("stat-2")).toContain('<span class="late">13:50</span>');
  });

  it("shows when it landed and where the bags are", () => {
    show({ phase: "arrived", landsAt: at(-14), baggageClaim: "7", gateDestination: "C12" });
    expect(stats()).toEqual([
      ["Landed", "12:46", "14 min ago"],
      ["Baggage belt", "7", ""],
      ["Gate", "C12", ""]
    ]);
  });

  it("shows how long ago it landed in hours, and a dash for an unknown belt", () => {
    show({ phase: "landed", landsAt: at(-65) });
    expect(html("stat-1")).toContain("1 h 5 min ago");
    expect(text("stat-2")).toBe("-");
  });

  it("never shows a time in the future as ago", () => {
    show({ phase: "landed", landsAt: at(5) });
    expect(html("stat-1")).toContain("just now");
    show({ phase: "landed", landsAt: undefined });
    expect(text("stat-1")).toBe("-");
  });

  it("shows what a cancelled flight was due out", () => {
    show({ phase: "cancelled", scheduledOut: at(60), gateOrigin: "B1" });
    expect(stats()).toEqual([
      ["Was due out", "14:00", ""],
      ["Gate", "B1", ""],
      ["Status", "Off", ""]
    ]);
  });
});

describe("keeping the card live", () => {
  it("redraws every second so the countdown moves", () => {
    show({ departsAt: at(135) });
    expect(main("stat-1")).toBe("2hrs 15mins");
    vi.advanceTimersByTime(60000);
    expect(main("stat-1")).toBe("2hrs 14mins");
  });

  it("does not draw before a message arrives, or after the card is hidden", () => {
    vi.advanceTimersByTime(2000);
    expect(routeMap.show).not.toHaveBeenCalled();
    show();
    routeMap.show.mockClear();
    card.hide();
    vi.advanceTimersByTime(2000);
    expect(routeMap.show).not.toHaveBeenCalled();
  });
});

describe("the plane's position between updates", () => {
  const position = (extra = {}) => ({ lat: 52, lon: 4, trackDeg: 90, speedKt: 360, at: at(-5), ...extra });
  const passed = () => routeMap.show.mock.calls[routeMap.show.mock.calls.length - 1][1];

  it("moves it on along its track for the time since it was taken", () => {
    show({ phase: "flying" }, { position: position() });
    // 360 kt for five minutes is 55.6 km, due east.
    expect(passed().lat).toBeCloseTo(52, 3);
    expect(passed().lon).toBeCloseTo(4 + 55.56 / (111.32 * Math.cos(52 * Math.PI / 180)), 3);
    expect(passed().trackDeg).toBe(90);
  });

  it("moves it north along a northward track", () => {
    show({ phase: "flying" }, { position: position({ trackDeg: 0 }) });
    expect(passed().lat).toBeCloseTo(52 + 55.56 / 110.574, 3);
    expect(passed().lon).toBeCloseTo(4, 6);
  });

  it("leaves a position alone when it is new, from the future, or has no time", () => {
    const fresh = position({ at: at(0) });
    show({ phase: "flying" }, { position: fresh });
    expect(passed()).toBe(fresh);
    const future = position({ at: at(5) });
    show({ phase: "flying" }, { position: future });
    expect(passed()).toBe(future);
    const untimed = position({ at: undefined });
    show({ phase: "flying" }, { position: untimed });
    expect(passed()).toBe(untimed);
  });

  it("leaves a position alone when it is too old to trust", () => {
    const old = position({ at: at(-11) });
    show({ phase: "flying" }, { position: old });
    expect(passed()).toBe(old);
  });

  it("leaves a position alone when the speed or track is not known", () => {
    const noSpeed = position({ speedKt: null });
    show({ phase: "flying" }, { position: noSpeed });
    expect(passed()).toBe(noSpeed);
    const noTrack = position({ trackDeg: null });
    show({ phase: "flying" }, { position: noTrack });
    expect(passed()).toBe(noTrack);
  });

  it("passes on no position when there is none", () => {
    show({ phase: "flying" });
    expect(passed()).toBeNull();
  });
});
