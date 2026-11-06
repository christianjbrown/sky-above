// The pieces both cards are made of: the logo tile, the route lines, flags, and
// text that shrinks to fit. app.js draws the plane overhead with them and
// followed.js a flight being followed.

(function () {
  "use strict";

  function byId(id) { return document.getElementById(id); }

  function setText(id, value) { byId(id).textContent = value == null ? "" : value; }

  function number(value) { return Math.round(value).toLocaleString("en-GB"); }

  // Metric first, with the imperial figure (or any second line) in smaller type underneath.
  function imperial(text) { return '<span class="imperial">' + text + "</span>"; }

  // The country home is in, which the watcher sends with every message.
  var homeCountry = null;

  function setHomeCountry(country) { homeCountry = country || null; }

  // The country's flag emoji, from its two-letter code; none for home's own country.
  function flag(country) {
    if (!country || country === homeCountry || !/^[A-Z]{2}$/.test(country)) { return ""; }
    return String.fromCodePoint(0x1F1E6 + country.charCodeAt(0) - 65, 0x1F1E6 + country.charCodeAt(1) - 65) + " ";
  }

  // The name a departures board would give the place, without the code.
  function placeName(end) {
    if (!end) { return ""; }
    return end.city || end.name || end.code || "";
  }

  // A place with no airport code, such as an airfield FlightAware only knows by its
  // position, goes by its name alone.
  function airport(end) {
    var city = placeName(end);
    if (!end.code) { return [document.createTextNode(flag(end.country) + city)]; }
    var code = document.createElement("b");
    code.textContent = end.code;
    if (!city || city === end.code) { return [document.createTextNode(flag(end.country)), code]; }
    return [document.createTextNode(flag(end.country) + city + " ("), code, document.createTextNode(")")];
  }

  function fill(line, nodes) {
    line.textContent = "";
    nodes.forEach(function (node) { line.appendChild(node); });
  }

  // Flights off the timetable, such as an empty plane being moved, often come with
  // only one end known, so each line shows whichever end there is.
  function showRoute(origin, destination) {
    var from = placeName(origin) ? origin : null;
    var to = placeName(destination) ? destination : null;
    byId("route").classList.toggle("none", !from && !to);
    var arrow = document.createElement("span");
    arrow.className = "arrow";
    arrow.textContent = "→";
    var fromNodes = from ? airport(from) : [];
    if (from && !to) { fromNodes.unshift(document.createTextNode("From ")); }
    fill(byId("route-from"), fromNodes);
    fill(byId("route-to"), to ? [arrow].concat(airport(to)) : []);
  }

  function showLogo(airlineCode, helicopter) {
    var tile = document.querySelector(".logo");
    var logo = byId("logo");
    tile.classList.toggle("helicopter", !!helicopter);
    var src = airlineCode ? "logos/" + airlineCode + ".svg" : "";
    if (!src) {
      logo.removeAttribute("src");
      tile.classList.add("none");
      return;
    }
    if (logo.getAttribute("src") !== src) {
      tile.classList.remove("none");
      logo.onerror = function () { tile.classList.add("none"); };
      logo.setAttribute("src", src);
    }
  }

  // Shrinks a line's text until it fits its width, down to a fraction of its styled size.
  function fit(element, smallestFraction) {
    element.style.fontSize = "";
    var size = parseFloat(window.getComputedStyle(element).fontSize);
    var smallest = size * smallestFraction;
    while (element.scrollWidth > element.clientWidth && size > smallest) {
      size *= 0.94;
      element.style.fontSize = size + "px";
    }
  }

  function fitAll(smallestFraction) {
    Array.prototype.forEach.call(document.querySelectorAll(".fit"), function (line) {
      fit(line, smallestFraction);
    });
  }

  // The three figures along the bottom: each a label, a big value and a smaller line,
  // all in red when the stat is late.
  function showStats(stats) {
    stats.forEach(function (stat, index) {
      var n = index + 1;
      setText("stat-" + n + "-label", stat.label);
      byId("stat-" + n + "-label").parentNode.classList.toggle("late", !!stat.late);
      byId("stat-" + n).innerHTML = stat.value + (stat.under ? imperial(stat.under) : "");
    });
  }

  window.CardParts = {
    byId: byId,
    setText: setText,
    number: number,
    imperial: imperial,
    flag: flag,
    setHomeCountry: setHomeCountry,
    placeName: placeName,
    showRoute: showRoute,
    showLogo: showLogo,
    fitAll: fitAll,
    showStats: showStats
  };
})();
