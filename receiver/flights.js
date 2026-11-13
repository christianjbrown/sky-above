// The flights page, at /flights: every route the watcher has looked up and remembers,
// newest first, to filter by airline, by whether it is still trusted, and by a search.
// It reads the watcher's list once when it opens; reload it for the latest.

(function () {
  "use strict";

  var parts = window.PageParts;
  var ROUTES_URL = "live/routes.json";
  var FRESH = "fresh";
  var STALE = "stale";
  var SEARCHED = ["flight_number", "callsign", "airline", "from", "to"];

  var routes = [];

  // "Bucharest (OTP)", as the card names an airport.
  function place(airport) {
    if (!airport) { return null; }
    var name = airport.city || airport.name;
    if (name && airport.code) { return name + " (" + airport.code + ")"; }
    return name || airport.code;
  }

  function state(row) { return row.fresh ? FRESH : STALE; }

  function line(row) {
    var status = row.fresh ? "Up to date" : '<span class="stale">Due a re-check</span>';
    return "<tr>" +
      "<td>" + parts.text(row.flight_number || row.callsign) + "</td>" +
      "<td>" + parts.escape(row.callsign) + "</td>" +
      "<td>" + parts.text(row.airline) + "</td>" +
      "<td>" + parts.text(row.from) + "</td>" +
      "<td>" + parts.text(row.to) + "</td>" +
      "<td>" + parts.escape(parts.when(row.saved_at)) + "</td>" +
      "<td>" + status + "</td>" +
      "</tr>";
  }

  function draw() {
    var form = document.getElementById("filters");
    var states = parts.ticked(form, "state") || {};
    var airlines = parts.ticked(form, "airline");
    var search = form.elements.search.value.trim().toLowerCase();
    var picked = routes.filter(function (row) {
      if (!states[state(row)]) { return false; }
      if (airlines && !airlines[row.airline]) { return false; }
      return parts.found(row, SEARCHED, search);
    });
    parts.table(document.getElementById("routes"), document.getElementById("flights-summary"), picked, routes.length, "flights", line);
  }

  function render(data) {
    routes = data.routes.map(function (row) { return Object.assign({}, row, { from: place(row.origin), to: place(row.destination) }); });
    var tally = {};
    tally[FRESH] = 0;
    tally[STALE] = 0;
    routes.forEach(function (row) { tally[state(row)] += 1; });
    document.querySelectorAll("#filters [data-count]").forEach(function (span) { span.textContent = tally[span.dataset.count]; });
    parts.chips(document.getElementById("airlines"), "airline", routes.map(function (row) { return row.airline; }));
    draw();
  }

  function load(fetcher) {
    return parts.load(fetcher, ROUTES_URL, document.getElementById("flights-status"), render);
  }

  function start(fetcher) {
    parts.watch(document.getElementById("filters"), draw);
    return load(fetcher);
  }

  window.FlightsPage = { render: render, load: load, start: start };

  if (document.getElementById("flights-status")) { start(window.fetch.bind(window)); }
})();
