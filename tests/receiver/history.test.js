import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { load } from "./support.js";

const html = readFileSync(resolve(process.cwd(), "receiver/history.html"), "utf8");

function mountHistory() {
  const body = html.slice(html.indexOf("<body>") + 6, html.indexOf("</body>"));
  document.body.innerHTML = body.replace(/<script[^>]*><\/script>/g, "");
}

const rows = () => [...document.querySelectorAll("#shown tr")].map((tr) => [...tr.children].map((td) => td.textContent));
const column = (n) => rows().map((r) => r[n]);
const summary = () => document.getElementById("history-summary").textContent;
const count = (name) => document.querySelector('[data-count="' + name + '"]').textContent;
const form = () => document.getElementById("filters");

function tick(selector, checked) {
  const input = form().querySelector(selector);
  input.checked = checked;
  input.dispatchEvent(new Event("input", { bubbles: true }));
}

function search(value) {
  form().elements.search.value = value;
  form().elements.search.dispatchEvent(new Event("input", { bubbles: true }));
}

const BASE = {
  hex: "abc123",
  shown_at: "2026-07-01T12:00:00+00:00",
  kind: "airline",
  callsign: null,
  flight_number: null,
  registration: null,
  aircraft: null,
  type_code: null,
  airline: null,
  origin: null,
  destination: null,
  owner: null,
  owner_category: null,
  emergency: null,
  closest_km: 1.25,
  lowest_ft: null
};
const row = (extra) => ({ ...BASE, ...extra });
const answer = (body, ok = true, status = 200) => vi.fn().mockResolvedValue({ ok, status, json: () => Promise.resolve(body) });

const SKY = [
  row({ flight_number: "U21234", airline: "easyJet", origin: "Alicante (ALC)", destination: "London Stansted (STN)", aircraft: "Airbus A320neo", registration: "G-EZAB", lowest_ft: 3200 }),
  row({ callsign: "EZY34CD", airline: "easyJet", destination: "Paris (ORY)" }),
  row({ flight_number: "BA879", airline: "British Airways", origin: "Faro (FAO)" }),
  row({ kind: "military", callsign: "ASCOT1", airline: "Royal Air Force", aircraft: "Airbus A400M" }),
  row({ kind: "police", registration: "G-POLA", airline: "Police", emergency: "General emergency" }),
  row({ kind: "airline", flight_number: "BA1", airline: "British Airways", destination: "Paris (CDG)", emergency: "Radio failure" }),
  row({ kind: "ambulance", callsign: "HLE01", airline: "Air Ambulance" }),
  row({ kind: "private-helicopter", registration: "G-EUYM", owner: "A Racing Driver", owner_category: "Named" }),
  row({ kind: "private-plane", registration: "N123AB", aircraft: "Dassault Falcon 7X", owner: "A Pop Star", owner_category: "Don't you know who I am?" }),
  row({ kind: "private-plane", hex: "def456", owner: "<b>Club</b>" }),
  row({ kind: "something-new" })
];

beforeEach(() => {
  vi.resetModules();
});

describe("the history page", () => {
  beforeEach(async () => {
    document.body.innerHTML = "";
    await load("pages", "history");
    mountHistory();
    window.HistoryPage.start(answer({ shown: [] }));
  });

  it("lists every plane with its kind, route, aircraft and who it belongs to", () => {
    window.HistoryPage.render({ shown: SKY });
    // In the browser's own time, which differs between machines.
    const shownAt = new Intl.DateTimeFormat("en-GB", { weekday: "short", day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" })
      .format(new Date(BASE.shown_at));
    expect(shownAt).toMatch(/^Wed, 1 Jul 2026, \d\d:00$/);
    expect(rows()[0]).toEqual([shownAt, "Airline", "U21234", "easyJet", "Alicante (ALC) to London Stansted (STN)", "Airbus A320neo, G-EZAB", "1.3 km, 3,200 ft", "-"]);
    expect(column(4)).toEqual([
      "Alicante (ALC) to London Stansted (STN)", "to Paris (ORY)", "from Faro (FAO)", "-", "🚨 General emergency", "to Paris (CDG) 🚨 Radio failure", "-", "-", "-", "-", "-"
    ]);
    expect(column(2).slice(8)).toEqual(["N123AB", "DEF456", "ABC123"]);
    expect(column(7).slice(7, 10)).toEqual(["🌟 A Racing Driver", "🌟 A Pop StarDon't you know who I am?", "🌟 <b>Club</b>"]);
    expect(column(1).slice(3)).toEqual(["Military", "Police", "Airline", "Air ambulance", "Private helicopter", "Private plane", "Private plane", "something-new"]);
    expect(document.querySelector("#shown b")).toBeNull();
    expect(summary()).toBe("11 of 11 planes");
  });

  it("counts each kind and the famous ones, and always lists a kind it has no chip for", () => {
    window.HistoryPage.render({ shown: SKY });
    expect([count("airline"), count("military"), count("private-plane"), count("famous")]).toEqual(["4", "1", "2", "3"]);
    expect(count("emergency")).toBe("2");
    tick('input[value="private-plane"]', false);
    expect(column(1).slice(-2)).toEqual(["Private helicopter", "something-new"]);
    form().querySelectorAll('input[name="kind"]').forEach((input) => { input.checked = false; });
    tick('input[value="airline"]', false);
    expect(column(1)).toEqual(["something-new"]);
  });

  it("filters by any mix of kinds, famous owners, airlines and a search", () => {
    window.HistoryPage.render({ shown: SKY.filter((r) => r.kind !== "something-new") });
    expect(summary()).toBe("10 of 10 planes");
    tick('input[value="airline"]', false);
    tick('input[value="military"]', false);
    expect(column(1)).toEqual(["Police", "Air ambulance", "Private helicopter", "Private plane", "Private plane"]);
    tick('input[name="famous"]', true);
    expect(column(7)).toEqual(["🌟 A Racing Driver", "🌟 A Pop StarDon't you know who I am?", "🌟 <b>Club</b>"]);
    search("  FALCON ");
    expect(column(2)).toEqual(["N123AB"]);
    expect(summary()).toBe("1 of 10 planes");
    search("");
    tick('input[name="famous"]', false);
    tick('input[value="airline"]', true);
    tick('input[name="airline"][value="easyJet"]', true);
    expect(column(2)).toEqual(["U21234", "EZY34CD"]);
    tick('input[name="airline"][value="Police"]', true);
    expect(column(2)).toEqual(["U21234", "EZY34CD", "G-POLA"]);
    tick('input[name="emergency"]', true);
    expect(column(2)).toEqual(["G-POLA"]);
    tick('input[name="airline"][value="Police"]', false);
    tick('input[name="airline"][value="easyJet"]', false);
    expect(column(2)).toEqual(["G-POLA", "BA1"]);
  });

  it("puts a chip for each airline, the most often seen first", () => {
    window.HistoryPage.render({ shown: SKY });
    const fold = document.querySelector("details.more");
    expect([fold.hidden, fold.open, fold.querySelector("[data-airline-count]").textContent]).toEqual([false, true, "5"]);
    const chips = [...document.querySelectorAll('#airlines input[name="airline"]')].map((input) => input.value);
    expect(chips).toEqual(["British Airways", "easyJet", "Air Ambulance", "Police", "Royal Air Force"]);
    expect(document.querySelector("#airlines .count").textContent).toBe("2");
  });

  it("lists only the latest few hundred, and says so", () => {
    window.HistoryPage.render({ shown: Array.from({ length: 501 }, (_, i) => row({ hex: "a" + i })) });
    expect(rows()).toHaveLength(500);
    expect(summary()).toBe("501 of 501 planes, the latest 500 listed");
  });

  it("never sends the filters anywhere", () => {
    const event = new Event("submit", { cancelable: true });
    form().dispatchEvent(event);
    expect(event.defaultPrevented).toBe(true);
  });

  it("reads the watcher's history and hides the note once it has", async () => {
    const fetcher = answer({ shown: [row({})] });
    await window.HistoryPage.load(fetcher);
    expect(fetcher).toHaveBeenCalledWith("live/history.json", { cache: "no-store" });
    expect(rows()).toHaveLength(1);
    expect(document.getElementById("history-status").hidden).toBe(true);
  });

  it("says what went wrong when the watcher cannot be read", async () => {
    await window.HistoryPage.load(answer({}, false, 502));
    expect(document.getElementById("history-status").textContent).toBe("Could not read it: the watcher answered 502");
    expect(document.getElementById("history-status").hidden).toBe(false);
  });
});

it("reads the history by itself when it is loaded on its page", async () => {
  mountHistory();
  window.fetch = answer({ shown: [row({ owner: "A Football Club", kind: "private-plane" })] });
  await load("pages", "history");
  await vi.waitFor(() => expect(rows()).toHaveLength(1));
});

it("does nothing by itself on a page that is not the history", async () => {
  document.body.innerHTML = "";
  window.fetch = vi.fn();
  await load("pages", "history");
  expect(window.fetch).not.toHaveBeenCalled();
});
