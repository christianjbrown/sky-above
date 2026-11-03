import { beforeEach, describe, expect, it, vi } from "vitest";
import { load, mountCard } from "./support.js";

let parts;

beforeEach(async () => {
  vi.resetModules();
  mountCard();
  await load("parts");
  parts = window.CardParts;
  parts.setHomeCountry(null);
});

describe("text and numbers", () => {
  it("writes text into an element, and nothing for a missing value", () => {
    parts.setText("airline", "Ryanair");
    expect(parts.byId("airline").textContent).toBe("Ryanair");
    parts.setText("airline", null);
    expect(parts.byId("airline").textContent).toBe("");
    parts.setText("airline", undefined);
    expect(parts.byId("airline").textContent).toBe("");
  });

  it("rounds numbers and groups the thousands the British way", () => {
    expect(parts.number(12345.6)).toBe("12,346");
  });

  it("puts the imperial figure in its own smaller span", () => {
    expect(parts.imperial("4,350 ft")).toBe('<span class="imperial">4,350 ft</span>');
  });
});

describe("flag", () => {
  it("shows the flag of a foreign country", () => {
    parts.setHomeCountry("GB");
    expect(parts.flag("CZ")).toBe("\u{1F1E8}\u{1F1FF} ");
  });

  it("shows nothing for home's own country", () => {
    parts.setHomeCountry("GB");
    expect(parts.flag("GB")).toBe("");
  });

  it("shows a flag for every country while home is not known", () => {
    parts.setHomeCountry("");
    expect(parts.flag("GB")).toBe("\u{1F1EC}\u{1F1E7} ");
  });

  it("shows nothing for a missing or malformed code", () => {
    expect(parts.flag(undefined)).toBe("");
    expect(parts.flag("gb")).toBe("");
    expect(parts.flag("GBR")).toBe("");
  });
});

describe("placeName", () => {
  it("prefers the city, then the name, then the code", () => {
    expect(parts.placeName({ city: "Prague", name: "Havel", code: "PRG" })).toBe("Prague");
    expect(parts.placeName({ name: "Havel", code: "PRG" })).toBe("Havel");
    expect(parts.placeName({ code: "PRG" })).toBe("PRG");
  });

  it("is empty when there is nothing to name", () => {
    expect(parts.placeName(null)).toBe("");
    expect(parts.placeName({})).toBe("");
  });
});

describe("showRoute", () => {
  const prague = { code: "PRG", city: "Prague", country: "CZ" };
  const heathrow = { code: "LHR", city: "London", country: "GB" };

  it("shows both ends with an arrow in front of the destination", () => {
    parts.setHomeCountry("GB");
    parts.showRoute(prague, heathrow);
    expect(parts.byId("route-from").textContent).toBe("\u{1F1E8}\u{1F1FF} Prague (PRG)");
    expect(parts.byId("route-from").querySelector("b").textContent).toBe("PRG");
    expect(parts.byId("route-to").textContent).toBe("→London (LHR)");
    expect(parts.byId("route-to").querySelector(".arrow")).not.toBeNull();
    expect(parts.byId("route").classList.contains("none")).toBe(false);
  });

  it("shows just the code when the place has no other name", () => {
    parts.showRoute({ code: "XYZ" }, { code: "ABC", city: "ABC" });
    expect(parts.byId("route-from").textContent).toBe("XYZ");
    expect(parts.byId("route-to").textContent).toBe("→ABC");
  });

  it("says where a flight is From when only its origin is known", () => {
    parts.showRoute(prague, null);
    expect(parts.byId("route-from").textContent).toContain("From ");
    expect(parts.byId("route-from").textContent).toContain("Prague (PRG)");
    expect(parts.byId("route-to").textContent).toBe("");
  });

  it("shows only the destination when the origin is unknown", () => {
    parts.setHomeCountry("GB");
    parts.showRoute({ city: "No code" }, heathrow);
    expect(parts.byId("route-from").textContent).toBe("");
    expect(parts.byId("route-to").textContent).toBe("→London (LHR)");
  });

  it("hides the route when neither end is known", () => {
    parts.showRoute(null, undefined);
    expect(parts.byId("route").classList.contains("none")).toBe(true);
    expect(parts.byId("route-from").textContent).toBe("");
    expect(parts.byId("route-to").textContent).toBe("");
  });
});

describe("showLogo", () => {
  it("shows the airline's logo", () => {
    parts.showLogo("BAW", false);
    expect(parts.byId("logo").getAttribute("src")).toBe("logos/BAW.svg");
    expect(document.querySelector(".logo").classList.contains("none")).toBe(false);
    expect(document.querySelector(".logo").classList.contains("helicopter")).toBe(false);
  });

  it("marks a helicopter's tile", () => {
    parts.showLogo("HLE", true);
    expect(document.querySelector(".logo").classList.contains("helicopter")).toBe(true);
  });

  it("hides the tile and the picture when there is no airline", () => {
    parts.showLogo("BAW", false);
    parts.showLogo(undefined, false);
    expect(parts.byId("logo").hasAttribute("src")).toBe(false);
    expect(document.querySelector(".logo").classList.contains("none")).toBe(true);
  });

  it("keeps the picture it has when the airline has not changed", () => {
    parts.showLogo("BAW", false);
    const logo = parts.byId("logo");
    const before = logo.onerror;
    parts.showLogo("BAW", false);
    expect(logo.onerror).toBe(before);
  });

  it("hides the tile when the logo does not load", () => {
    parts.showLogo("ZZZ", false);
    parts.byId("logo").onerror();
    expect(document.querySelector(".logo").classList.contains("none")).toBe(true);
  });

  it("brings the tile back for the next airline after one without a logo", () => {
    parts.showLogo("ZZZ", false);
    parts.byId("logo").onerror();
    parts.showLogo("BAW", false);
    expect(document.querySelector(".logo").classList.contains("none")).toBe(false);
  });
});

describe("fitAll", () => {
  // jsdom does not lay anything out, so a line is given a width that grows with its type size.
  function crowdedLine(textWidthAtFullSize, boxWidth) {
    const line = parts.byId("airline");
    line.classList.add("fit");
    line.style.fontSize = "";
    document.head.insertAdjacentHTML("beforeend", "<style>.fit { font-size: 100px; }</style>");
    Object.defineProperty(line, "scrollWidth", {
      configurable: true,
      get: () => textWidthAtFullSize * (parseFloat(line.style.fontSize || "100") / 100)
    });
    Object.defineProperty(line, "clientWidth", { configurable: true, get: () => boxWidth });
    return line;
  }

  it("leaves a line that already fits alone", () => {
    const line = crowdedLine(80, 100);
    parts.fitAll(0.45);
    expect(line.style.fontSize).toBe("");
  });

  it("shrinks a line until it fits", () => {
    const line = crowdedLine(150, 100);
    parts.fitAll(0.45);
    const size = parseFloat(line.style.fontSize);
    expect(size).toBeLessThan(100);
    expect(size).toBeGreaterThanOrEqual(45 * 0.94);
    expect(150 * size / 100).toBeLessThanOrEqual(100);
  });

  it("stops shrinking at the smallest size even if the line still does not fit", () => {
    const line = crowdedLine(1000, 100);
    parts.fitAll(0.45);
    const size = parseFloat(line.style.fontSize);
    expect(size).toBeLessThanOrEqual(45);
    expect(size).toBeGreaterThan(45 * 0.94 * 0.94 - 0.01);
  });
});

describe("showStats", () => {
  it("fills the three figures, with the smaller line under a value when there is one", () => {
    parts.showStats([
      { label: "Altitude", value: "1.3km", under: "4,350 ft" },
      { label: "Speed", value: "396km/h" },
      { label: "Away", value: "8.0km", late: true }
    ]);
    expect(parts.byId("stat-1-label").textContent).toBe("Altitude");
    expect(parts.byId("stat-1").innerHTML).toBe('1.3km<span class="imperial">4,350 ft</span>');
    expect(parts.byId("stat-2").innerHTML).toBe("396km/h");
    expect(parts.byId("stat-3-label").parentNode.classList.contains("late")).toBe(true);
    expect(parts.byId("stat-1-label").parentNode.classList.contains("late")).toBe(false);
  });

  it("clears a late stat when the next figure is on time", () => {
    parts.showStats([{ label: "A", value: "1", late: true }]);
    parts.showStats([{ label: "A", value: "1" }]);
    expect(parts.byId("stat-1-label").parentNode.classList.contains("late")).toBe(false);
  });
});
