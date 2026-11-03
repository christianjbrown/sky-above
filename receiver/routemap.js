// The map on a followed flight's card: its whole route as a great circle between
// the two airports, the part flown so far drawn solid, and the plane where it is.
// The street map only covers the area round home, so this one draws from a small world map
// (map/world.pmtiles, down to zoom 6), which is plenty to see a route across Europe.

(function () {
  "use strict";

  var MAP_URL = "map/world.pmtiles";
  var MAX_ZOOM = 6;
  var PLANE_VH = 6;
  var ARC_POINTS = 64;

  function absolute(path) { return new URL(path, window.location.href).href; }

  function radians(degrees) { return degrees * Math.PI / 180; }
  function degrees(radians) { return radians * 180 / Math.PI; }

  // Points along the great circle from a to b, each [lon, lat].
  function arc(a, b) {
    var lat1 = radians(a[1]), lon1 = radians(a[0]), lat2 = radians(b[1]), lon2 = radians(b[0]);
    var d = 2 * Math.asin(Math.sqrt(
      Math.pow(Math.sin((lat2 - lat1) / 2), 2) + Math.cos(lat1) * Math.cos(lat2) * Math.pow(Math.sin((lon2 - lon1) / 2), 2)
    ));
    if (d === 0) { return [a, b]; }
    var points = [];
    for (var i = 0; i <= ARC_POINTS; i++) {
      var f = i / ARC_POINTS;
      var p = Math.sin((1 - f) * d) / Math.sin(d);
      var q = Math.sin(f * d) / Math.sin(d);
      var x = p * Math.cos(lat1) * Math.cos(lon1) + q * Math.cos(lat2) * Math.cos(lon2);
      var y = p * Math.cos(lat1) * Math.sin(lon1) + q * Math.cos(lat2) * Math.sin(lon2);
      var z = p * Math.sin(lat1) + q * Math.sin(lat2);
      points.push([degrees(Math.atan2(y, x)), degrees(Math.atan2(z, Math.sqrt(x * x + y * y)))]);
    }
    return points;
  }

  function line(points) {
    return { type: "Feature", geometry: { type: "LineString", coordinates: points } };
  }

  function where(airport) {
    return airport && airport.lat != null && airport.lon != null ? [airport.lon, airport.lat] : null;
  }

  function labelElement() {
    var element = document.createElement("div");
    element.className = "map-airport";
    return element;
  }

  function RouteMap(container) {
    this._container = container;
    this._map = null;
    this._ready = false;
    this._failed = false;
    this._pending = null;
    this._ident = null;
  }

  RouteMap.prototype.show = function (flight, position) {
    if (this._failed) { return; }
    var from = where(flight.origin), to = where(flight.destination);
    if (!from || !to) { return; }
    if (!this._map) { this._start(); }
    if (!this._ready) { this._pending = [flight, position]; return; }
    this._draw(flight, from, to, position);
  };

  RouteMap.prototype._start = function () {
    var self = this;
    try {
      maplibregl.addProtocol("pmtiles", new pmtiles.Protocol().tile);
      this._map = new maplibregl.Map({
        container: this._container,
        center: [0, 50],
        zoom: 3,
        interactive: false,
        attributionControl: false,
        fadeDuration: 0,
        style: {
          version: 8,
          glyphs: absolute("vendor/fonts/") + "{fontstack}/{range}.pbf",
          sprite: absolute("vendor/sprites/dark"),
          sources: {
            protomaps: { type: "vector", url: "pmtiles://" + absolute(MAP_URL), attribution: "© OpenStreetMap contributors, Protomaps" }
          },
          layers: basemaps.layers("protomaps", basemaps.namedFlavor("dark"), { lang: "en" })
        }
      });
      this._fromMarker = new maplibregl.Marker({ element: labelElement() });
      this._toMarker = new maplibregl.Marker({ element: labelElement() });
      this._planeMarker = new maplibregl.Marker({ element: planeElement(), rotationAlignment: "map" });
      this._map.on("load", function () {
        self._map.addSource("route", { type: "geojson", data: line([]) });
        self._map.addLayer({
          id: "route",
          type: "line",
          source: "route",
          paint: { "line-color": "#ffb347", "line-width": 3, "line-opacity": 0.5, "line-dasharray": [2, 2] }
        });
        self._map.addSource("flown", { type: "geojson", data: line([]) });
        self._map.addLayer({
          id: "flown",
          type: "line",
          source: "flown",
          paint: { "line-color": "#ffb347", "line-width": 4, "line-opacity": 0.9 }
        });
        self._ready = true;
        // show() always holds the flight that started the map until it is ready.
        var pending = self._pending;
        self._pending = null;
        self.show(pending[0], pending[1]);
      });
      this._map.on("error", function (event) { console.warn("route map:", event.error && event.error.message); });
    } catch (error) {
      console.warn("no route map:", error);
      this._failed = true;
      this._container.classList.add("failed");
    }
  };

  function planeElement() {
    var element = document.createElement("div");
    element.className = "map-plane";
    window.PlaneShapes.dress(element, { category: "A3" }, PLANE_VH);
    return element;
  }

  RouteMap.prototype._draw = function (flight, from, to, position) {
    var map = this._map;
    // The container may have been hidden while a plane overhead had the screen.
    map.resize();
    map.getSource("route").setData(line(arc(from, to)));
    this._fromMarker.getElement().textContent = flight.origin.code || "";
    this._toMarker.getElement().textContent = flight.destination.code || "";
    this._fromMarker.setLngLat(from).addTo(map);
    this._toMarker.setLngLat(to).addTo(map);

    var here = position && position.lat != null && position.lon != null ? [position.lon, position.lat] : null;
    map.getSource("flown").setData(line(here ? arc(from, here) : []));
    if (here) {
      this._planeMarker.setLngLat(here).setRotation(position.trackDeg || 0).addTo(map);
    } else {
      this._planeMarker.remove();
    }

    if (flight.ident !== this._ident) {
      this._ident = flight.ident;
      var bounds = new maplibregl.LngLatBounds(from, from).extend(to);
      map.fitBounds(bounds, { padding: 70, maxZoom: MAX_ZOOM, duration: 0 });
    }
  };

  window.RouteMap = RouteMap;
})();
