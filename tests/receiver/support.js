// Shared set-up for the receiver tests: the card's real markup, the scripts loaded
// the way index.html loads them, and small stand-ins for MapLibre and Cast.

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { vi } from "vitest";

const html = readFileSync(resolve(process.cwd(), "receiver/index.html"), "utf8");

// The body of index.html without its script tags, so the tests draw into the real card.
export function mountCard() {
  const body = html.slice(html.indexOf("<body>") + 6, html.indexOf("</body>"));
  document.body.innerHTML = body.replace(/<script[^>]*><\/script>/g, "");
}

// Loads a receiver script for its side effect, as the browser does.
export async function load(...names) {
  for (const name of names) { await import(/* @vite-ignore */ "../../receiver/" + name + ".js"); }
}

// A stand-in for the pieces of MapLibre the maps use; everything they are told is recorded.
export function installMapFakes() {
  const maps = [];
  const markers = [];

  class Marker {
    constructor(options) {
      markers.push(this);
      this.element = options.element;
      this.options = options;
      this.lngLat = null;
      this.rotation = null;
      this.map = null;
    }
    setLngLat(point) { this.lngLat = point; return this; }
    setRotation(degrees) { this.rotation = degrees; return this; }
    addTo(map) { this.map = map; return this; }
    remove() { this.map = null; return this; }
    getElement() { return this.element; }
  }

  class LngLatBounds {
    constructor(southWest, northEast) { this.points = [southWest, northEast]; }
    extend(point) { this.points.push(point); return this; }
  }

  class FakeMap {
    constructor(options) {
      this.options = options;
      this.handlers = {};
      this.sources = {};
      this.layers = [];
      this.eased = [];
      this.fitted = [];
      this.resized = 0;
      this.camera = { zoom: 12, center: [0, 0] };
      maps.push(this);
    }
    on(name, handler) { this.handlers[name] = handler; }
    addSource(id, spec) {
      this.sources[id] = { data: spec.data, setData(data) { this.data = data; } };
    }
    addLayer(layer, before) { this.layers.push(before === undefined ? layer : { ...layer, before }); }
    getSource(id) { return this.sources[id]; }
    cameraForBounds(bounds, options) {
      this.lastBounds = bounds;
      this.lastBoundsOptions = options;
      return this.camera;
    }
    easeTo(camera) { this.eased.push(camera); }
    fitBounds(bounds, options) { this.fitted.push({ bounds, options }); }
    resize() { this.resized += 1; }
    // What MapLibre does once the style has loaded.
    finishLoading() { this.handlers.load(); }
  }

  const protocols = [];
  vi.stubGlobal("maplibregl", {
    Map: FakeMap,
    Marker,
    LngLatBounds,
    addProtocol(name, tile) { protocols.push({ name, tile }); }
  });
  vi.stubGlobal("pmtiles", { Protocol: class { constructor() { this.tile = function tile() {}; } } });
  vi.stubGlobal("basemaps", {
    // A background and one layer drawn from the tiles, as the real style has.
    layers: (source, flavor, options) => [
      { id: "background", type: "background", flavor, options },
      { id: "earth", type: "fill", source, "source-layer": "earth" }
    ],
    namedFlavor: (name) => name
  });
  return { maps, markers, protocols };
}

// A Cast receiver context that remembers what the card asks of it.
export function installCastFake() {
  const handlers = {};
  const context = {
    handlers,
    volume: { muted: false, level: 0.5 },
    levels: [],
    started: null,
    sent: [],
    listeners: {},
    addCustomMessageListener(namespace, handler) { handlers[namespace] = handler; },
    addEventListener(type, handler) { this.listeners[type] = handler; },
    getSystemVolume() { return this.volume; },
    setSystemVolumeLevel(level) { this.levels.push(level); },
    start(options) { this.started = options; },
    sendCustomMessage(namespace, sender, message) { this.sent.push({ namespace, sender, message }); }
  };
  vi.stubGlobal("cast", {
    framework: {
      CastReceiverContext: { getInstance: () => context },
      CastReceiverOptions: class {},
      system: { MessageType: { JSON: "JSON" }, EventType: { SYSTEM_VOLUME_CHANGED: "volume" } }
    }
  });
  return context;
}

// An Audio that records what it is told to play instead of making a sound.
export function installAudioFake() {
  const played = [];
  vi.stubGlobal("Audio", class {
    play() { played.push(this.src); }
  });
  return played;
}
