// The map beside the card: home, the zone around it, and the plane with the
// trail it has flown since it became the nearest (solid), the way it is
// heading (dotted) and a fainter line to the airport it is going to, which it
// rarely points straight at until it is lined up to land. Other planes around
// are smaller and dimmer, with no lines.
// Each plane's shape and size follow its type: airliner, heavy, prop or helicopter.
// A plane in an emergency can be far beyond the street map, which only covers the area
// round home, so for one of those the small world map is drawn underneath it as well.
// Everything it draws comes
// from the Pi: the map extract of the area round home, MapLibre, the Protomaps style, fonts
// and icons all live under vendor/ and map/.

(function () {
  "use strict";

  var MAP_URL = "map/area.pmtiles";
  var WORLD_URL = "map/world.pmtiles";
  var MAX_ZOOM = 14;
  // However close the plane gets, the map still shows this much around home, as a
  // share of the zone's radius, so the zone and the plane passing through it stay in view.
  var CLOSEST_VIEW = 1.3;
  // A helicopter hovers and circles over a few streets rather than crossing the zone, so
  // its map frames home with only this much room round it, the helicopter and the whole
  // trail it has flown, close enough to see where it has been.
  var HELICOPTER_VIEW = 0.3;
  // How long each step of following the plane takes, about one update.
  var FOLLOW_MS = 1000;
  // How big an airliner is drawn: the plane on the card, and the others around it.
  var PLANE_VH = 7;
  var OTHER_PLANE_VH = 4.5;
  // Far enough to run off the edge of the map at any zoom it uses.
  var AHEAD_KM = 40;
  var JET = "M21 16v-2l-8-5V3.5c0-.83-.67-1.5-1.5-1.5S10 2.67 10 3.5V9l-8 5v2l8-2.5V19l-2 1.5V22l3.5-1 3.5 1v-1.5L13 19v-5.5l8 2.5z";
  var SHAPES = {
    jet: JET,
    // The airliner with an engine pod under each wing twice over.
    heavy: JET + "M14.6 11.2h1.4v2.8h-1.4zM17.8 13.1h1.4v2.6h-1.4zM7 11.2h1.4v2.8H7zM3.8 13.1h1.4v2.6H3.8z",
    // Straight wings and a small tailplane, for light aircraft and turboprops.
    prop: "M11 2h2v5h9v2.5h-9V18l3 1.5V21H8v-1.5l3-1.5V9.5H2V7h9z",
    // Two crossed rotor blades over a body and tail boom.
    helicopter: "M12 5c1.7 0 3 1.6 3 3.6S13.7 13 12 13s-3-2.4-3-4.4S10.3 5 12 5zM11.4 12.5h1.2V20h-1.2zM9.5 19.5h5v1.2h-5zM4.6 2.9L6 1.5l13.4 13.4-1.4 1.4zM18 1.5l1.4 1.4L6 16.3l-1.4-1.4z"
  };
  // ADS-B emitter categories: A1 light, A2 small, A3 large, A4 757, A5 heavy,
  // A6 high performance, A7 rotorcraft. Sizes are relative to an airliner.
  var SIZES = { A1: 0.6, A2: 0.8, A3: 1, A4: 1.05, A5: 1.3, A6: 0.9, A7: 0.8 };
  // Turboprops, which report as small or large but look nothing like a jet.
  var TURBOPROPS = /^(AT4|AT7|DH8|SF34|JS4|B350|BE20|C208|PC12|L410|D228|E120|F50|SW4)/;

  function absolute(path) { return new URL(path, window.location.href).href; }

  function circle(home, radiusKm) {
    var points = [];
    var latKm = 110.574;
    var lonKm = 111.32 * Math.cos(home.lat * Math.PI / 180);
    for (var i = 0; i <= 64; i++) {
      var angle = (i / 64) * 2 * Math.PI;
      points.push([home.lon + (radiusKm * Math.sin(angle)) / lonKm, home.lat + (radiusKm * Math.cos(angle)) / latKm]);
    }
    return { type: "Feature", geometry: { type: "Polygon", coordinates: [points] } };
  }

  // A point distance km from start along a compass bearing; flat-earth maths is
  // close enough over the few tens of km the map shows.
  function along(start, bearingDeg, distanceKm) {
    var bearing = bearingDeg * Math.PI / 180;
    var lonKm = 111.32 * Math.cos(start[1] * Math.PI / 180);
    return [start[0] + (distanceKm * Math.sin(bearing)) / lonKm, start[1] + (distanceKm * Math.cos(bearing)) / 110.574];
  }

  // Home with room around it, and the plane: the map shrinks to this as the plane
  // comes in and grows again as it goes, so how close it passes is plain to see.
  // Home with reach km of room round it, and every one of the points.
  function view(home, reach, points) {
    var bounds = new maplibregl.LngLatBounds(along(home, 225, reach * Math.SQRT2), along(home, 45, reach * Math.SQRT2));
    points.forEach(function (point) { bounds.extend(point); });
    return bounds;
  }

  function line(points) {
    return { type: "Feature", geometry: { type: "LineString", coordinates: points } };
  }

  function shape(plane) {
    if (plane.helicopter || plane.category === "A7") { return "helicopter"; }
    if (plane.category === "A5") { return "heavy"; }
    if (plane.category === "A1" || TURBOPROPS.test(plane.typeCode || "")) { return "prop"; }
    return "jet";
  }

  // Draws the plane's shape at its size, in vh, from the size an airliner gets.
  function dress(element, plane, airlinerVh) {
    // An air ambulance or the police wear their own colour.
    element.dataset.service = plane.service || "";
    var kind = shape(plane);
    if (element.dataset.kind === kind && element.dataset.category === String(plane.category)) { return; }
    var size = airlinerVh * (SIZES[plane.category] || 1) + "vh";
    element.dataset.kind = kind;
    element.dataset.category = String(plane.category);
    element.style.width = size;
    element.style.height = size;
    element.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="' + SHAPES[kind] + '"/></svg>';
  }

  function planeElement(className) {
    var element = document.createElement("div");
    element.className = className;
    return element;
  }

  function airportElement() {
    var element = document.createElement("div");
    element.className = "map-airport";
    return element;
  }

  function homeElement() {
    var element = document.createElement("div");
    element.className = "map-home";
    return element;
  }

  function FlightMap(container) {
    this._container = container;
    this._map = null;
    this._ready = false;
    this._failed = false;
    this._hex = null;
    this._trail = [];
    this._pending = null;
    this._others = {};
    this._airportMarker = null;
    this._baseLayers = [];
    this._world = false;
  }

  FlightMap.prototype.show = function (message) {
    if (this._failed) { return; }
    var plane = message.planes[0];
    if (!message.home || plane.lat == null || plane.lon == null) { return; }
    if (!this._map) { this._start(message); }
    if (!this._ready) { this._pending = message; return; }
    this._draw(message, plane);
  };

  FlightMap.prototype._start = function (message) {
    var self = this;
    try {
      var protocol = new pmtiles.Protocol();
      maplibregl.addProtocol("pmtiles", protocol.tile);
      var home = [message.home.lon, message.home.lat];
      this._baseLayers = basemaps.layers("protomaps", basemaps.namedFlavor("dark"), { lang: "en" });
      this._map = new maplibregl.Map({
        container: this._container,
        center: home,
        zoom: 11,
        interactive: false,
        // The credit is a small line drawn by style.css; the built-in control is a large box.
        attributionControl: false,
        fadeDuration: 0,
        style: {
          version: 8,
          // Placeholders added after resolving, so URL() does not percent-encode their braces.
          glyphs: absolute("vendor/fonts/") + "{fontstack}/{range}.pbf",
          sprite: absolute("vendor/sprites/dark"),
          sources: {
            protomaps: {
              type: "vector",
              url: "pmtiles://" + absolute(MAP_URL),
              attribution: "© OpenStreetMap contributors, Protomaps"
            }
          },
          layers: this._baseLayers
        }
      });
      this._homeMarker = new maplibregl.Marker({ element: homeElement() }).setLngLat(home).addTo(this._map);
      this._planeMarker = new maplibregl.Marker({ element: planeElement("map-plane"), rotationAlignment: "map" });
      this._airportMarker = new maplibregl.Marker({ element: airportElement() });
      this._map.on("load", function () {
        self._map.addSource("zone", { type: "geojson", data: circle(message.home, message.radiusKm) });
        self._map.addLayer({ id: "zone", type: "line", source: "zone", paint: { "line-color": "#ffb347", "line-opacity": 0.5, "line-width": 2, "line-dasharray": [2, 2] } });
        self._map.addSource("trail", { type: "geojson", data: line([]) });
        self._map.addLayer({ id: "trail", type: "line", source: "trail", paint: { "line-color": "#ffb347", "line-width": 4, "line-opacity": 0.8 } });
        self._map.addSource("bound", { type: "geojson", data: line([]) });
        self._map.addLayer({
          id: "bound",
          type: "line",
          source: "bound",
          paint: { "line-color": "#ffb347", "line-width": 2, "line-opacity": 0.45, "line-dasharray": [3, 3] }
        });
        self._map.addSource("ahead", { type: "geojson", data: line([]) });
        self._map.addLayer({
          id: "ahead",
          type: "line",
          source: "ahead",
          layout: { "line-cap": "round" },
          paint: { "line-color": "#ffb347", "line-width": 4, "line-opacity": 0.8, "line-dasharray": [0, 2] }
        });
        self._ready = true;
        // show() always holds the message that started the map until it is ready.
        self._draw(self._pending, self._pending.planes[0]);
      });
      this._map.on("error", function (event) { console.warn("map:", event.error && event.error.message); });
    } catch (error) {
      console.warn("no map:", error);
      this._failed = true;
      this._container.classList.add("failed");
    }
  };

  FlightMap.prototype._draw = function (message, plane) {
    var position = [plane.lon, plane.lat];
    var home = [message.home.lon, message.home.lat];
    var fresh = plane.hex !== this._hex;
    if (plane.emergency) { this._addWorld(); }
    if (fresh) {
      this._hex = plane.hex;
      this._trail = [];
      dress(this._planeMarker.getElement(), plane, PLANE_VH);
      this._planeMarker.setLngLat(position).addTo(this._map);
    }
    this._trail.push(position);
    this._map.getSource("trail").setData(line(this._trail));
    var ahead = plane.trackDeg == null ? [] : [position, along(position, plane.trackDeg, AHEAD_KM)];
    this._map.getSource("ahead").setData(line(ahead));
    this._drawDestination(position, plane.destination);
    this._map.getSource("zone").setData(circle(message.home, message.radiusKm));
    this._planeMarker.setLngLat(position).setRotation(plane.trackDeg || 0);
    this._drawOthers(message.others || []);

    var helicopter = shape(plane) === "helicopter";
    var framed = helicopter
      ? view(home, message.radiusKm * HELICOPTER_VIEW, this._trail)
      : view(home, message.radiusKm * CLOSEST_VIEW, [position]);
    var camera = this._map.cameraForBounds(framed, { padding: 60, maxZoom: MAX_ZOOM });
    if (camera) {
      camera.duration = fresh ? 0 : FOLLOW_MS;
      camera.easing = function (t) { return t; };
      this._map.easeTo(camera);
    }
  };

  // The world map's layers, slipped in under the street map's, once.
  FlightMap.prototype._addWorld = function () {
    if (this._world) { return; }
    this._world = true;
    var map = this._map;
    map.addSource("world", { type: "vector", url: "pmtiles://" + absolute(WORLD_URL) });
    var layers = this._baseLayers.filter(function (layer) { return layer.type !== "background"; });
    var under = layers[0].id;
    layers.forEach(function (layer) {
      map.addLayer(Object.assign({}, layer, { id: "world-" + layer.id, source: "world" }), under);
    });
  };

  // The line from the plane to where it is landing, and the airport's code at its end.
  FlightMap.prototype._drawDestination = function (position, destination) {
    var known = destination && destination.lat != null && destination.lon != null;
    var airport = known ? [destination.lon, destination.lat] : null;
    this._map.getSource("bound").setData(line(known ? [position, airport] : []));
    if (!known) {
      this._airportMarker.remove();
      return;
    }
    this._airportMarker.getElement().textContent = destination.code || "";
    this._airportMarker.setLngLat(airport).addTo(this._map);
  };

  // One marker per other plane, moved as it flies and dropped once it is gone.
  FlightMap.prototype._drawOthers = function (others) {
    var self = this;
    var seen = {};
    others.forEach(function (other) {
      if (other.lat == null || other.lon == null) { return; }
      seen[other.hex] = true;
      var marker = self._others[other.hex];
      var position = [other.lon, other.lat];
      if (!marker) {
        // MapLibre needs the position before the marker goes on the map.
        marker = new maplibregl.Marker({ element: planeElement("map-plane other"), rotationAlignment: "map" });
        marker.setLngLat(position).addTo(self._map);
        self._others[other.hex] = marker;
      }
      dress(marker.getElement(), other, OTHER_PLANE_VH);
      marker.setLngLat(position).setRotation(other.trackDeg || 0);
    });
    Object.keys(this._others).forEach(function (hex) {
      if (!seen[hex]) {
        self._others[hex].remove();
        delete self._others[hex];
      }
    });
  };

  window.FlightMap = FlightMap;
  // The route map on a followed flight's card draws its plane the same way.
  window.PlaneShapes = { dress: dress };
})();
