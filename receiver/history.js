// The history page, at /history: every plane that has had the card, newest first, to
// filter by what sort of flight it was, by airline, by famous owners, by emergencies,
// and by a search. It reads the
// watcher's history once when it opens; reload it for the latest.

(function () {
  "use strict";

  var HISTORY_URL = "live/history.json";
  var TIME_FORMAT = { weekday: "short", day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" };
  var NOTHING = "-";
  // Drawing more rows than this makes the page slow, and nobody scrolls that far.
  var ROWS_DRAWN = 500;
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

  function escape(text) {
    return String(text).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; });
  }

  function text(value) { return escape(value == null ? NOTHING : value); }

  function when(iso) {
    return new Intl.DateTimeFormat("en-GB", TIME_FORMAT).format(new Date(iso));
  }

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
    if (!row.emergency) { return text(where); }
    var emergency = '<span class="emergency">🚨 ' + escape(row.emergency) + "</span>";
    return where ? escape(where) + " " + emergency : emergency;
  }

  function closest(row) {
    var height = row.lowest_ft == null ? "" : ", " + row.lowest_ft.toLocaleString("en-GB") + " ft";
    return row.closest_km.toFixed(1) + " km" + height;
  }

  function owner(row) {
    if (!row.owner) { return NOTHING; }
    var listed = row.owner_category && row.owner_category !== NAMED ? "<small>" + escape(row.owner_category) + "</small>" : "";
    return '<span class="famous">🌟 ' + escape(row.owner) + listed + "</span>";
  }

  function line(row) {
    var aircraft = [row.aircraft, row.registration].filter(Boolean).join(", ");
    return "<tr>" +
      "<td>" + escape(when(row.shown_at)) + "</td>" +
      '<td><span class="kind kind-' + escape(row.kind) + '">' + text(KIND_NAMES[row.kind] || row.kind) + "</span></td>" +
      "<td>" + escape(flight(row)) + "</td>" +
      "<td>" + text(row.airline) + "</td>" +
      "<td>" + routeCell(row) + "</td>" +
      "<td>" + text(aircraft || null) + "</td>" +
      "<td>" + escape(closest(row)) + "</td>" +
      "<td>" + owner(row) + "</td>" +
      "</tr>";
  }

  function chosen(form) {
    var kinds = {};
    form.querySelectorAll('input[name="kind"]:checked').forEach(function (input) { kinds[input.value] = true; });
    var airlines = {};
    form.querySelectorAll('input[name="airline"]:checked').forEach(function (input) { airlines[input.value] = true; });
    return {
      kinds: kinds,
      // None ticked means any airline.
      airlines: Object.keys(airlines).length ? airlines : null,
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
    if (!filter.search) { return true; }
    return SEARCHED.some(function (key) { return row[key] != null && String(row[key]).toLowerCase().indexOf(filter.search) !== -1; });
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

  // A chip for each airline or operator seen, the most often seen first.
  function airlineChips() {
    var tally = {};
    shown.forEach(function (row) { if (row.airline) { tally[row.airline] = (tally[row.airline] || 0) + 1; } });
    var names = Object.keys(tally).sort(function (a, b) { return tally[b] - tally[a] || a.localeCompare(b); });
    document.getElementById("airlines").innerHTML = names.map(function (name) {
      return '<label class="chip"><input type="checkbox" name="airline" value="' + escape(name) + '"><span>' + escape(name) +
        '<span class="count">' + tally[name] + "</span></span></label>";
    }).join("");
  }

  function draw() {
    var form = document.getElementById("filters");
    var picked = shown.filter(function (row) { return matches(row, chosen(form)); });
    document.getElementById("shown").innerHTML = picked.slice(0, ROWS_DRAWN).map(line).join("");
    var summary = picked.length + " of " + shown.length + " planes";
    if (picked.length > ROWS_DRAWN) { summary += ", the latest " + ROWS_DRAWN + " listed"; }
    document.getElementById("history-summary").textContent = summary;
  }

  function render(history) {
    shown = history.shown;
    counts(document.getElementById("filters"));
    airlineChips();
    draw();
  }

  function load(fetcher) {
    var status = document.getElementById("history-status");
    return fetcher(HISTORY_URL, { cache: "no-store" })
      .then(function (response) {
        if (!response.ok) { throw new Error("the watcher answered " + response.status); }
        return response.json();
      })
      .then(function (history) {
        render(history);
        status.hidden = true;
      })
      .catch(function (error) {
        status.textContent = "Could not read the history: " + error.message;
        status.hidden = false;
      });
  }

  function start(fetcher) {
    var form = document.getElementById("filters");
    form.addEventListener("input", draw);
    form.addEventListener("submit", function (event) { event.preventDefault(); });
    return load(fetcher);
  }

  window.HistoryPage = { render: render, load: load, start: start };

  if (document.getElementById("filters")) { start(window.fetch.bind(window)); }
})();
