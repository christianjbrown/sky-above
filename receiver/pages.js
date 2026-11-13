// What the desktop pages (/history and /flights) share: reading the watcher's JSON once,
// drawing cells safely, the time format, the chips that filter, and the search box.

(function () {
  "use strict";

  var NOTHING = "-";
  var TIME_FORMAT = { weekday: "short", day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" };
  // Drawing more rows than this makes a page slow, and nobody scrolls that far.
  var ROWS_DRAWN = 500;
  // A few chips start out on show; more than this start folded away.
  var CHIPS_OPEN = 12;

  function escape(text) {
    return String(text).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; });
  }

  function text(value) { return escape(value == null ? NOTHING : value); }

  function when(iso) {
    return new Intl.DateTimeFormat("en-GB", TIME_FORMAT).format(new Date(iso));
  }

  // The values of the ticked boxes with this name, as a set, or null when none are ticked.
  function ticked(form, name) {
    var values = {};
    form.querySelectorAll('input[name="' + name + '"]:checked').forEach(function (input) { values[input.value] = true; });
    return Object.keys(values).length ? values : null;
  }

  // A chip for each value seen, the most often seen first, into the container. The fold the
  // container sits in shows only when there is a chip, open when there are only a few.
  function chips(container, name, values) {
    var tally = {};
    values.forEach(function (value) { if (value) { tally[value] = (tally[value] || 0) + 1; } });
    var names = Object.keys(tally).sort(function (a, b) { return tally[b] - tally[a] || a.localeCompare(b); });
    container.innerHTML = names.map(function (value) {
      return '<label class="chip"><input type="checkbox" name="' + name + '" value="' + escape(value) + '"><span>' + escape(value) +
        '<span class="count">' + tally[value] + "</span></span></label>";
    }).join("");
    var fold = container.closest("details");
    fold.hidden = names.length === 0;
    fold.open = names.length <= CHIPS_OPEN;
    fold.querySelector("[data-airline-count]").textContent = names.length;
  }

  // Whether any of the row's fields contains the search, ignoring case.
  function found(row, keys, search) {
    if (!search) { return true; }
    return keys.some(function (key) { return row[key] != null && String(row[key]).toLowerCase().indexOf(search) !== -1; });
  }

  // Draws the first ROWS_DRAWN of the picked rows, and says how many there are.
  function table(body, summary, picked, total, noun, line) {
    body.innerHTML = picked.slice(0, ROWS_DRAWN).map(line).join("");
    var said = picked.length + " of " + total + " " + noun;
    if (picked.length > ROWS_DRAWN) { said += ", the latest " + ROWS_DRAWN + " listed"; }
    summary.textContent = said;
  }

  // Reads url once and hands it to render, or says on the status line what went wrong.
  function load(fetcher, url, status, render) {
    return fetcher(url, { cache: "no-store" })
      .then(function (response) {
        if (!response.ok) { throw new Error("the watcher answered " + response.status); }
        return response.json();
      })
      .then(function (data) {
        render(data);
        status.hidden = true;
      })
      .catch(function (error) {
        status.textContent = "Could not read it: " + error.message;
        status.hidden = false;
      });
  }

  // Redraws on any change to the filters, and keeps the form from being sent anywhere.
  function watch(form, draw) {
    form.addEventListener("input", draw);
    form.addEventListener("submit", function (event) { event.preventDefault(); });
  }

  window.PageParts = { NOTHING: NOTHING, escape: escape, text: text, when: when, ticked: ticked, chips: chips, found: found, table: table, load: load, watch: watch };
})();
