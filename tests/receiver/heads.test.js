import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

// Each page a person can open names itself in the tab, says what it is to a search or a
// link preview, and has the icon, so a tab or a shared link is never a bare address.
const PAGES = ["index", "history", "flights"];
const SITE_NAME = "Sky Above";

function head(page) {
  const html = readFileSync(resolve(process.cwd(), "receiver", page + ".html"), "utf8");
  const doc = new DOMParser().parseFromString(html, "text/html");
  const meta = (attribute, name) => doc.querySelector("meta[" + attribute + '="' + name + '"]')?.getAttribute("content");
  return { doc, meta };
}

describe.each(PAGES)("the %s page", (page) => {
  const { doc, meta } = head(page);

  it("has a title of its own that ends with the site's name", () => {
    expect(doc.title.endsWith(SITE_NAME)).toBe(true);
    expect(meta("property", "og:title")).toBe(doc.title);
  });

  it("describes itself the same way to search and to link previews", () => {
    expect(meta("name", "description")).toBeTruthy();
    expect(meta("property", "og:description")).toBe(meta("name", "description"));
    expect(meta("property", "og:image")).toBe("/og.jpg");
  });

  it("has the icon, and the icon is there", () => {
    const icon = doc.querySelector('link[rel="icon"]').getAttribute("href");
    expect(existsSync(resolve(process.cwd(), "receiver", icon.slice(1)))).toBe(true);
  });
});

it("gives every page a different title", () => {
  expect(new Set(PAGES.map((page) => head(page).doc.title)).size).toBe(PAGES.length);
});
