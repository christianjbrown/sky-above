// The history page, at /history: every plane that has had the card, newest first, to
// filter by what sort of flight it was, by airline, by famous owners, by emergencies,
// and by a search. It reads the watcher's history once when it opens; reload it for the
// latest.

(function () {
  "use strict";

  var parts = window.PageParts;
  var HISTORY_URL = "live/history.json";
  var FAMOUS = "famous";
  var EMERGENCY = "emergency";
  // What the watcher files an owner from the names file alone under, which says nothing.
  var NAMED = "Named";
  var KIND_NAMES = {
    airline: "Airline",
    military: "Military",
    police: "Police",
    ambulance: "Air ambulance",
    "private-helicopter": "Private helicopter",
    "private-plane": "Private plane"
  };
  var SEARCHED = ["flight_number", "callsign", "registration", "airline", "origin", "destination", "aircraft", "type_code", "owner", "owner_category"];

  var shown = [];

  function flight(row) {
    return row.flight_number || row.callsign || row.registration || row.hex.toUpperCase();
  }

  function route(row) {
    if (row.origin && row.destination) { return row.origin + " to " + row.destination; }
    if (row.destination) { return "to " + row.destination; }
    if (row.origin) { return "from " + row.origin; }
    return null;
  }

  // The route, and for a plane that was in an emergency, what the emergency was.
  function routeCell(row) {
    var where = route(row);
    if (!row.emergency) { return parts.text(where); }
    var emergency = '<span class="emergency">🚨 ' + parts.escape(row.emergency) + "</span>";
    return where ? parts.escape(where) + " " + emergency : emergency;
  }

  function closest(row) {
    var height = row.lowest_ft == null ? "" : ", " + row.lowest_ft.toLocaleString("en-GB") + " ft";
    return row.closest_km.toFixed(1) + " km" + height;
  }

  function owner(row) {
    if (!row.owner) { return parts.NOTHING; }
    var listed = row.owner_category && row.owner_category !== NAMED ? "<small>" + parts.escape(row.owner_category) + "</small>" : "";
    return '<span class="famous">🌟 ' + parts.escape(row.owner) + listed + "</span>";
  }

  function line(row) {
    var aircraft = [row.aircraft, row.registration].filter(Boolean).join(", ");
    return "<tr>" +
      "<td>" + parts.escape(parts.when(row.shown_at)) + "</td>" +
      '<td><span class="kind kind-' + parts.escape(row.kind) + '">' + parts.text(KIND_NAMES[row.kind] || row.kind) + "</span></td>" +
      "<td>" + parts.escape(flight(row)) + "</td>" +
      "<td>" + parts.text(row.airline) + "</td>" +
      "<td>" + routeCell(row) + "</td>" +
      "<td>" + parts.text(aircraft || null) + "</td>" +
      "<td>" + parts.escape(closest(row)) + "</td>" +
      "<td>" + owner(row) + "</td>" +
      "</tr>";
  }

  function chosen(form) {
    return {
      kinds: parts.ticked(form, "kind") || {},
      // None ticked means any airline.
      airlines: parts.ticked(form, "airline"),
      famous: form.elements.famous.checked,
      emergency: form.elements.emergency.checked,
      search: form.elements.search.value.trim().toLowerCase()
    };
  }

  function matches(row, filter) {
    // A kind this page has no chip for, from a newer watcher, is always listed.
    if (KIND_NAMES[row.kind] && !filter.kinds[row.kind]) { return false; }
    if (filter.famous && !row.owner) { return false; }
    if (filter.emergency && !row.emergency) { return false; }
    if (filter.airlines && !filter.airlines[row.airline]) { return false; }
    return parts.found(row, SEARCHED, filter.search);
  }

  function counts(form) {
    var tally = {};
    tally[FAMOUS] = 0;
    tally[EMERGENCY] = 0;
    shown.forEach(function (row) {
      tally[row.kind] = (tally[row.kind] || 0) + 1;
      if (row.owner) { tally[FAMOUS] += 1; }
      if (row.emergency) { tally[EMERGENCY] += 1; }
    });
    form.querySelectorAll("[data-count]").forEach(function (span) { span.textContent = tally[span.dataset.count] || 0; });
  }

  function draw() {
    var filter = chosen(document.getElementById("filters"));
    var picked = shown.filter(function (row) { return matches(row, filter); });
    parts.table(document.getElementById("shown"), document.getElementById("history-summary"), picked, shown.length, "planes", line);
  }

  function render(history) {
    shown = history.shown;
    counts(document.getElementById("filters"));
    parts.chips(document.getElementById("airlines"), "airline", shown.map(function (row) { return row.airline; }));
    draw();
  }

  function load(fetcher) {
    return parts.load(fetcher, HISTORY_URL, document.getElementById("history-status"), render);
  }

  function start(fetcher) {
    parts.watch(document.getElementById("filters"), draw);
    return load(fetcher);
  }

  window.HistoryPage = { render: render, load: load, start: start };

  if (document.getElementById("history-status")) { start(window.fetch.bind(window)); }
})();
