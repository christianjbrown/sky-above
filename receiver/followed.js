// The card for a flight being followed: ours, or a friend's or family's. From four
// hours before it leaves until half an hour after it gets in, it counts down to
// departure, then landing, with the gate, the baggage belt, any delay and why, and
// the flight on a map of its whole route. Times show in UK time, and also in the
// time at the far end where that differs.
//
// The watcher only sends a message when something might have changed, so the card
// keeps the last one and redraws it every second for the countdown.

(function () {
  "use strict";

  var LATE_MINUTES = 10;
  // How long a position can be carried forward along its track before it is too old to trust.
  var CARRY_FORWARD_MS = 10 * 60 * 1000;

  function escape(text) {
    return String(text).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; });
  }

  function clock(iso, zone) {
    if (!iso) { return "-"; }
    return new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit", timeZone: zone }).format(new Date(iso));
  }

  function unit(text) { return '<span class="unit">' + text + "</span>"; }

  // 2hrs 14mins, then 42mins within the hour, and Now in the last minute.
  function countdown(iso, now) {
    if (!iso) { return "-"; }
    var minutes = Math.floor((new Date(iso).getTime() - now) / 60000);
    if (minutes < 1) { return "Now"; }
    var h = Math.floor(minutes / 60);
    var m = minutes % 60;
    var hours = h ? h + unit(h === 1 ? "hr" : "hrs") : "";
    var mins = m ? m + unit(m === 1 ? "min" : "mins") : "";
    return [hours, mins].filter(Boolean).join(" ");
  }

  function ago(iso, now) {
    if (!iso) { return ""; }
    var minutes = Math.max(0, Math.round((now - new Date(iso).getTime()) / 60000));
    if (minutes < 1) { return "just now"; }
    if (minutes < 60) { return minutes + " min ago"; }
    return Math.floor(minutes / 60) + " h " + (minutes % 60) + " min ago";
  }

  function late(minutes) { return minutes != null && minutes >= LATE_MINUTES; }

  // Delays, and the times they push things to, show in red.
  function red(html) { return '<span class="late">' + html + "</span>"; }

  function FollowedCard(parts, routeMap, smallestFit) {
    var self = this;
    this._parts = parts;
    this._routeMap = routeMap;
    this._smallestFit = smallestFit;
    this._message = null;
    setInterval(function () { if (self._message) { self._draw(Date.now()); } }, 1000);
  }

  FollowedCard.prototype.show = function (message) {
    this._message = message;
    this._draw(Date.now());
  };

  FollowedCard.prototype.hide = function () { this._message = null; };

  FollowedCard.prototype._draw = function (now) {
    var message = this._message;
    var flight = message.flight;
    var parts = this._parts;
    var home = message.homeTimezone;

    parts.showLogo(flight.airlineCode, false);
    parts.setText("airline", flight.airline || flight.airlineCode || "");
    parts.setText("flight", flight.ident);
    parts.showRoute(flight.origin, flight.destination);
    parts.byId("aircraft").innerHTML = status(flight);
    parts.setText("note", note(message, home));
    parts.showStats(stats(flight, home, now));
    parts.fitAll(this._smallestFit);
    try {
      this._routeMap.show(flight, carriedForward(message.position, now));
    } catch (error) {
      console.warn("route map:", error);
    }
  };

  // HTML, so a delay can be red.
  function status(flight) {
    var plane = escape([flight.aircraftType, flight.registration].filter(Boolean).join(" "));
    var words = {
      cancelled: red("Cancelled"),
      taxiing: late(flight.departureDelayMinutes) ? "Leaving the gate, " + red(flight.departureDelayMinutes + " min late") : "Leaving the gate",
      flying: late(flight.arrivalDelayMinutes) ? "In the air, " + red(flight.arrivalDelayMinutes + " min late") : "In the air, on time",
      landed: "Landed, taxiing in",
      arrived: "At the gate"
    }[flight.phase];
    if (flight.diverted) { words = red("Diverted"); }
    if (!words) {
      // Our own sums from the plane's earlier legs, when they say later than the airline does.
      var ours = flight.departureEstimate === "ours";
      words = late(flight.departureDelayMinutes) ? red((ours ? "Likely delayed " : "Delayed ") + flight.departureDelayMinutes + " min") : "On time";
    }
    return plane && flight.phase !== "cancelled" ? words + " · " + plane : words;
  }

  // The line under the status: why it is late, or where its plane is coming from,
  // or in the air how high and fast it is going.
  function note(message, home) {
    var flight = message.flight;
    if (message.reason) { return message.reason; }
    var leg = (message.earlierLegs || [])[0];
    if (flight.phase === "waiting" && leg) { return inbound(leg, home); }
    var position = message.position;
    if (flight.phase === "flying" && position && position.altitudeFt != null) {
      var parts = [Math.round(position.altitudeFt).toLocaleString("en-GB") + " ft"];
      if (position.speedKt != null) { parts.push(Math.round(position.speedKt * 1.852) + " km/h"); }
      return parts.join(" · ");
    }
    return "";
  }

  function inbound(leg, home) {
    var from = window.CardParts.placeName(leg.origin) || "its last stop";
    var behind = late(leg.arrivalDelayMinutes) ? ", " + leg.arrivalDelayMinutes + " min late" : "";
    if (leg.landed) { return "The plane is here, in from " + from + " at " + clock(leg.arrivesAt, home); }
    if (leg.departed) { return "The plane is on its way from " + from + ", landing " + clock(leg.arrivesAt, home) + behind; }
    return "The plane is still to leave " + from + ", due in at " + clock(leg.arrivesAt, home) + behind;
  }

  // A time here, and underneath it the time at the far end if the clocks differ there.
  function there(iso, airport, home) {
    if (!iso || !airport || !airport.timezone || clock(iso, airport.timezone) === clock(iso, home)) { return ""; }
    return clock(iso, airport.timezone) + " in " + escape(window.CardParts.placeName(airport));
  }

  function gate(gateName, terminal) {
    return {
      value: gateName ? escape(gateName) : "-",
      under: terminal ? "Terminal " + escape(terminal) : ""
    };
  }

  function lateIf(minutes, html) { return late(minutes) ? red(html) : html; }

  function stats(flight, home, now) {
    var lands = flight.landsAt || flight.arrivesAt;
    var leaving = gate(flight.gateOrigin, flight.terminalOrigin);
    var arriving = gate(flight.gateDestination, flight.terminalDestination);
    // The time shown is FlightAware's expected landing, so it only says scheduled while the flight is on time.
    var landsStat = {
      label: late(flight.arrivalDelayMinutes) ? "Lands (expected)" : "Lands (scheduled)",
      value: lateIf(flight.arrivalDelayMinutes, clock(lands, home)),
      under: there(lands, flight.destination, home)
    };
    switch (flight.phase) {
      case "cancelled":
        return [
          { label: "Was due out", value: clock(flight.scheduledOut, home) },
          { label: "Gate", value: leaving.value, under: leaving.under },
          { label: "Status", value: "Off" }
        ];
      case "taxiing":
        return [
          { label: "Left the gate", late: late(flight.departureDelayMinutes), value: clock(flight.departsAt, home), under: ago(flight.departsAt, now) },
          { label: "Gate", value: leaving.value, under: leaving.under },
          landsStat
        ];
      case "flying":
        return [
          { label: "Lands in", value: countdown(lands, now), under: "at " + lateIf(flight.arrivalDelayMinutes, clock(lands, home)) },
          { label: "At the gate", value: lateIf(flight.arrivalDelayMinutes, clock(flight.arrivesAt, home)), under: there(flight.arrivesAt, flight.destination, home) },
          { label: "Arrival gate", value: arriving.value, under: arriving.under }
        ];
      case "landed":
      case "arrived":
        return [
          { label: "Landed", value: clock(flight.landsAt, home), under: ago(flight.landsAt, now) },
          { label: "Baggage belt", value: flight.baggageClaim ? escape(flight.baggageClaim) : "-" },
          { label: "Gate", value: arriving.value, under: arriving.under }
        ];
      default:
        return [
          {
            label: "Departs in",
            late: late(flight.departureDelayMinutes),
            value: countdown(flight.departsAt, now),
            under: clock(flight.departsAt, home) + (late(flight.departureDelayMinutes) ? ", was " + clock(flight.scheduledOut, home) : "")
          },
          { label: "Gate", value: leaving.value, under: leaving.under },
          landsStat
        ];
    }
  }

  // Moves a position on along its track for the time since it was taken, so the
  // plane keeps flying between the watcher's updates from FlightAware.
  function carriedForward(position, now) {
    if (!position) { return null; }
    var age = position.at ? now - new Date(position.at).getTime() : 0;
    if (age <= 0 || age > CARRY_FORWARD_MS || position.speedKt == null || position.trackDeg == null) { return position; }
    var km = position.speedKt * 1.852 * age / 3600000;
    var bearing = position.trackDeg * Math.PI / 180;
    var lonKm = 111.32 * Math.cos(position.lat * Math.PI / 180);
    return {
      lat: position.lat + (km * Math.cos(bearing)) / 110.574,
      lon: position.lon + (km * Math.sin(bearing)) / lonKm,
      trackDeg: position.trackDeg
    };
  }

  window.FollowedCard = FollowedCard;
})();
