import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { load } from "./support.js";

const html = readFileSync(resolve(process.cwd(), "receiver/flights.html"), "utf8");

function mountFlights() {
  const body = html.slice(html.indexOf("<body>") + 6, html.indexOf("</body>"));
  document.body.innerHTML = body.replace(/<script[^>]*><\/script>/g, "");
}

const rows = () => [...document.querySelectorAll("#routes tr")].map((tr) => [...tr.children].map((td) => td.textContent));
const column = (n) => rows().map((r) => r[n]);
const summary = () => document.getElementById("flights-summary").textContent;
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

const LHR = { code: "LHR", name: "Heathrow", city: "London", country: "GB" };
const BASE = { callsign: "BAW879", flight_number: "BA879", airline: "British Airways", origin: null, destination: null, saved_at: "2026-11-06T16:46:51+00:00", fresh: true };
const route = (extra) => ({ ...BASE, ...extra });
const answer = (body, ok = true, status = 200) => vi.fn().mockResolvedValue({ ok, status, json: () => Promise.resolve(body) });

const KNOWN = [
  route({ origin: { code: "OTP", name: "Henri Coanda International", city: "Bucharest", country: "RO" }, destination: LHR }),
  route({ callsign: "BAW483Z", flight_number: "BA483", origin: { code: "BCN", name: "El Prat", city: null }, destination: { code: null, name: null, city: "London" }, fresh: false }),
  route({ callsign: "RYR78VA", flight_number: null, airline: "Ryanair", origin: { code: "CRL", name: null, city: null } }),
  route({ callsign: "XYZ1", flight_number: null, airline: null, destination: LHR, fresh: false })
];

beforeEach(() => {
  vi.resetModules();
});

describe("the flights page", () => {
  beforeEach(async () => {
    document.body.innerHTML = "";
    await load("pages", "flights");
    mountFlights();
    window.FlightsPage.start(answer({ routes: [] }));
  });

  it("lists every remembered flight with its airports named as the card names them", () => {
    window.FlightsPage.render({ routes: KNOWN });
    const lookedUp = new Intl.DateTimeFormat("en-GB", { weekday: "short", day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" })
      .format(new Date(BASE.saved_at));
    expect(rows()[0]).toEqual(["BA879", "BAW879", "British Airways", "Bucharest (OTP)", "London (LHR)", lookedUp, "Up to date"]);
    expect(rows().map((r) => [r[0], r[2], r[3], r[4], r[6]])).toEqual([
      ["BA879", "British Airways", "Bucharest (OTP)", "London (LHR)", "Up to date"],
      ["BA483", "British Airways", "El Prat (BCN)", "London", "Due a re-check"],
      ["RYR78VA", "Ryanair", "CRL", "-", "Up to date"],
      ["XYZ1", "-", "-", "London (LHR)", "Due a re-check"]
    ]);
    expect([count("fresh"), count("stale")]).toEqual(["2", "2"]);
    expect(summary()).toBe("4 of 4 flights");
  });

  it("filters by status, airline and a search together", () => {
    window.FlightsPage.render({ routes: KNOWN });
    tick('input[value="fresh"]', false);
    expect(column(1)).toEqual(["BAW483Z", "XYZ1"]);
    tick('input[value="fresh"]', true);
    tick('input[name="airline"][value="British Airways"]', true);
    expect(column(1)).toEqual(["BAW879", "BAW483Z"]);
    search(" bucharest ");
    expect(column(1)).toEqual(["BAW879"]);
    expect(summary()).toBe("1 of 4 flights");
    tick('input[value="fresh"]', false);
    tick('input[value="stale"]', false);
    expect(rows()).toEqual([]);
  });

  it("puts a chip for each airline, the most often seen first", () => {
    window.FlightsPage.render({ routes: KNOWN });
    const fold = document.querySelector("details.more");
    expect([fold.hidden, fold.open, fold.querySelector("[data-airline-count]").textContent]).toEqual([false, true, "2"]);
    const chips = [...document.querySelectorAll('#airlines input[name="airline"]')].map((input) => input.value);
    expect(chips).toEqual(["British Airways", "Ryanair"]);
  });

  it("lists only the latest few hundred, and says so", () => {
    window.FlightsPage.render({ routes: Array.from({ length: 501 }, (_, i) => route({ callsign: "A" + i })) });
    expect(rows()).toHaveLength(500);
    expect(summary()).toBe("501 of 501 flights, the latest 500 listed");
  });

  it("never sends the filters anywhere", () => {
    const event = new Event("submit", { cancelable: true });
    form().dispatchEvent(event);
    expect(event.defaultPrevented).toBe(true);
  });

  it("reads the watcher's flights and hides the note once it has", async () => {
    const fetcher = answer({ routes: [route({})] });
    await window.FlightsPage.load(fetcher);
    expect(fetcher).toHaveBeenCalledWith("live/routes.json", { cache: "no-store" });
    expect(rows()).toHaveLength(1);
    expect(document.getElementById("flights-status").hidden).toBe(true);
  });

  it("says what went wrong when the watcher cannot be read", async () => {
    await window.FlightsPage.load(answer({}, false, 502));
    expect(document.getElementById("flights-status").textContent).toBe("Could not read it: the watcher answered 502");
    expect(document.getElementById("flights-status").hidden).toBe(false);
  });
});

it("reads the flights by itself when it is loaded on its page", async () => {
  mountFlights();
  window.fetch = answer({ routes: [route({})] });
  await load("pages", "flights");
  await vi.waitFor(() => expect(rows()).toHaveLength(1));
});

it("does nothing by itself on a page that is not the flights page", async () => {
  document.body.innerHTML = "";
  window.fetch = vi.fn();
  await load("pages", "flights");
  expect(window.fetch).not.toHaveBeenCalled();
});

describe("the airline chips", () => {
  beforeEach(async () => {
    document.body.innerHTML = "";
    await load("pages", "flights");
    mountFlights();
  });

  it("fold away when there are many, and hide when there are none", () => {
    const fold = () => document.querySelector("details.more");
    window.FlightsPage.render({ routes: Array.from({ length: 13 }, (_, i) => route({ airline: "Airline " + i })) });
    expect([fold().hidden, fold().open]).toEqual([false, false]);
    window.FlightsPage.render({ routes: [route({ airline: null })] });
    expect(fold().hidden).toBe(true);
  });
});
