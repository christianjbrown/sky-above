// Cast receiver for the Nest Hub. The watcher on the Pi sends a "planes"
// message about once a second while something is overhead, and this draws the
// nearest one; in between, it may send a "followed" message for a flight being
// followed, which followed.js draws. Opened in an ordinary browser it follows the
// same card from the Pi instead, ?demo shows a made-up plane and ?demo=followed a
// made-up followed flight. A plane in an emergency comes as a "planes" message whose
// card says what is wrong, and is drawn in red.

(function () {
  "use strict";

  // Must match NAMESPACE in watcher/src/flights_watcher/chromecast.py
  // (tests/test_config_and_wiring.py checks the two agree).
  var NAMESPACE = "urn:x-cast:sky-above";
  var LIVE_URL = "live/planes.json";
  var LIVE_EVERY_MS = 1000;
  var SMALLEST_FIT = 0.45;
  // How long after the Hub reports it is unmuted before its sound is properly back.
  var UNMUTE_SETTLE_MS = 2000;
  // How long after the card loads a mute is taken to be the watcher's chime mute
  // (CHIME_SECONDS plus a slow unmute) rather than someone muting the Hub.
  var CHIME_MUTE_MS = 20000;
  // How long the card has to stay hidden before the watcher is told, so a card
  // being closed does not report itself on the way out.
  var HIDDEN_FOR_MS = 3000;
  // How loud an emergency is read out on the Hub, out of 1, unless it is already louder.
  var EMERGENCY_VOLUME = 0.8;
  var LOOKS = ["waiting", "followed", "emergency", "service-ambulance", "service-police", "service-military"];

  var parts = window.CardParts;
  var screen = document.getElementById("screen");
  var flightMap = new FlightMap(document.getElementById("map"));
  var followedCard = new FollowedCard(parts, new RouteMap(document.getElementById("route-map")), SMALLEST_FIT);
  var speaker = new Speaker(new RightAway());

  var number = parts.number;
  var imperial = parts.imperial;

  function kilometres(km, suffix) {
    if (km < 1) { return number(km * 1000) + "<small>m" + suffix + "</small>"; }
    return km.toFixed(1) + "<small>km" + suffix + "</small>";
  }

  function altitude(plane) {
    if (plane.altitudeFt == null) { return "-"; }
    var trend = "";
    if (plane.verticalRateFpm > 300) { trend = " ↗"; }
    if (plane.verticalRateFpm < -300) { trend = " ↘"; }
    return kilometres(plane.altitudeFt * 0.0003048, trend) + imperial(number(plane.altitudeFt) + " ft");
  }

  function speed(plane) {
    if (plane.speedKt == null) { return "-"; }
    return number(plane.speedKt * 1.852) + "<small>km/h</small>" + imperial(number(plane.speedKt * 1.15078) + " mph");
  }

  function distance(plane) {
    return kilometres(plane.distanceKm, "");
  }

  // "Squawk 7700 · General emergency", or just the label for one only guessed at.
  function emergencyLine(emergency) {
    return emergency.squawk ? "Squawk " + emergency.squawk + " \u00b7 " + emergency.label : emergency.label;
  }

  // Only a browser hears this: the watcher stops casting to the Hub instead, but the
  // live card it serves the browser goes back to "clear" once the plane has gone.
  function showClear() {
    screen.classList.remove.apply(screen.classList, LOOKS);
    screen.classList.add("waiting");
    followedCard.hide();
    flightMap.forget();
  }

  function render(message) {
    if (message && message.type === "clear") {
      showClear();
      return;
    }
    if (message) { parts.setHomeCountry(message.homeCountry); }
    if (message && message.type === "followed" && message.flight) {
      screen.classList.remove.apply(screen.classList, LOOKS);
      screen.classList.add("followed");
      followedCard.show(message);
      speaker.say(message.speech);
      return;
    }
    if (!message || message.type !== "planes" || !message.planes || !message.planes.length) { return; }
    var plane = message.planes[0];

    screen.classList.remove.apply(screen.classList, LOOKS);
    if (plane.emergency) {
      screen.classList.add("emergency");
    } else if (plane.service) {
      screen.classList.add("service-" + plane.service);
    }
    followedCard.hide();

    parts.showLogo(plane.airlineCode, plane.helicopter, plane.ownerPortrait);
    parts.setText("airline", plane.airline || plane.owner || plane.callsign || "");
    parts.setText("flight", plane.flightNumber || plane.callsign || plane.registration || plane.hex.toUpperCase());
    parts.showRoute(plane.origin, plane.destination);
    parts.setText("aircraft", plane.aircraft || plane.typeCode || "");
    parts.setText("note", plane.emergency ? emergencyLine(plane.emergency) : "");

    parts.showStats([
      { label: "Altitude", value: altitude(plane) },
      { label: "Speed", value: speed(plane) },
      { label: "Away", value: distance(plane) }
    ]);

    parts.fitAll(SMALLEST_FIT);
    speaker.say(message.speech, plane.emergency ? EMERGENCY_VOLUME : null);
    // The map goes last, so a map that fails cannot stop the card or the voice.
    try { flightMap.show(message); } catch (error) { console.warn("map:", error); }
  }

  function startCast() {
    // The Hub is only cast to when a plane is on its way, so it shows this
    // for the moment before the first card arrives, not "Watching the sky".
    parts.setText("waiting-line", "Here comes a plane\u2026");
    var context = cast.framework.CastReceiverContext.getInstance();
    var options = new cast.framework.CastReceiverOptions();
    options.disableIdleTimeout = true;
    options.customNamespaces = {};
    options.customNamespaces[NAMESPACE] = cast.framework.system.MessageType.JSON;
    context.addCustomMessageListener(NAMESPACE, function (event) { render(event.data); });
    speaker = new Speaker(new WhenHubUnmuted(context, UNMUTE_SETTLE_MS, CHIME_MUTE_MS), new HubVolume(context));
    context.start(options);
    reportWhenHidden(context);
  }

  // A Nest Hub puts its clock and photos over a card that has been up for about ten
  // minutes, though the card keeps running and talking underneath. Only a fresh launch
  // brings it back, so the card tells the watcher, which relaunches it.
  function reportWhenHidden(context) {
    document.addEventListener("visibilitychange", function () {
      if (!document.hidden) { return; }
      setTimeout(function () {
        if (document.hidden) { context.sendCustomMessage(NAMESPACE, undefined, { type: "hidden" }); }
      }, HIDDEN_FOR_MS);
    });
  }

  function startBrowser() {
    function poll() {
      fetch(LIVE_URL, { cache: "no-store" })
        .then(function (response) { return response.ok ? response.json() : null; })
        .then(render)
        .catch(function () {})
        .then(function () { setTimeout(poll, LIVE_EVERY_MS); });
    }
    poll();
  }

  function onCastDevice() { return /CrKey/.test(navigator.userAgent); }

  // ?demo=ambulance, ?demo=police and ?demo=military swap the plane for one of theirs,
  // and ?demo=emergency has it squawking 7700.
  var HELICOPTER = {
    helicopter: true,
    category: "A7",
    aircraft: "Airbus Helicopters H135",
    typeCode: "EC35",
    altitudeFt: 600,
    speedKt: 122,
    verticalRateFpm: 0
  };
  var SERVICE_DEMOS = {
    ambulance: Object.assign({ callsign: "HLE27", airline: "Air ambulance", airlineCode: "HLE", registration: "G-LAAA" }, HELICOPTER),
    police: Object.assign({ callsign: "UKP15", airline: "Police", airlineCode: "UKP", registration: "G-POLF" }, HELICOPTER),
    military: {
      callsign: "RRR4321", airline: "Royal Air Force", airlineCode: "RRR", registration: "ZM400", military: true,
      helicopter: false, category: "A5", aircraft: "Airbus A400M Atlas", typeCode: "A400",
      altitudeFt: 3200, speedKt: 230, verticalRateFpm: 0
    }
  };

  // A made-up private jet with a made-up owner, as a names file might give it.
  var NOTABLE_DEMO = {
    callsign: "GPOPS", flightNumber: null, airline: null, airlineCode: null, owner: "A Pop Star",
    origin: null, destination: null, aircraft: "Dassault Falcon 7X", typeCode: "FA7X", registration: "G-POPS",
    altitudeFt: 5200, speedKt: 260, verticalRateFpm: -900,
    // A silhouette, as a made-up owner has no picture of their own.
    ownerPortrait: "data:image/svg+xml," + encodeURIComponent(
      '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><rect width="100" height="100" fill="#3d5a80"/>' +
      '<circle cx="50" cy="38" r="20" fill="#e0fbfc"/><ellipse cx="50" cy="95" rx="36" ry="30" fill="#e0fbfc"/></svg>'
    )
  };

  function startDemo(which) {
    var km = 8;
    var sample = {
      type: "planes",
      homeCountry: "GB",
      radiusKm: 1.5,
      home: { lat: 51.4769, lon: 0.0 },
      total: 2,
      planes: [{
        hex: "4ca7b5",
        callsign: "BAW86S",
        flightNumber: "BA86S",
        airline: "British Airways",
        airlineCode: "BAW",
        helicopter: false,
        category: "A3",
        origin: { code: "PRG", name: "Václav Havel Airport Prague", city: "Prague", country: "CZ" },
        destination: { code: "LHR", name: "London Heathrow Airport", city: "London", country: "GB", lat: 51.471, lon: -0.462 },
        aircraft: "Airbus A320",
        typeCode: "A320",
        registration: "G-EUYM",
        altitudeFt: 4350,
        speedKt: 214,
        verticalRateFpm: -704,
        trackDeg: 262,
        lat: 51.4826,
        lon: 0.0336,
        distanceKm: km,
        photo: null
      }],
      others: [
        { hex: "406b2c", lat: 51.4858, lon: 0.0150, trackDeg: 95, category: "A5", typeCode: "B77W" },
        { hex: "4ca9e1", lat: 51.4700, lon: 0.0330, trackDeg: 300, category: "A2", typeCode: "DH8D" },
        { hex: "3c6589", lat: 51.4850, lon: 0.0400, trackDeg: 210, category: "A7", typeCode: "EC35" },
        { hex: "40755a", lat: 51.4690, lon: 0.0100, trackDeg: 40, category: "A1", typeCode: "C172" }
      ]
    };
    var service = SERVICE_DEMOS[which];
    if (which === "notable") {
      Object.assign(sample.planes[0], NOTABLE_DEMO);
    } else if (which === "emergency") {
      sample.planes[0].emergency = { kind: "general", squawk: "7700", label: "General emergency" };
    } else if (service) {
      Object.assign(sample.planes[0], service, { service: which, flightNumber: null, origin: null, destination: null });
    }
    sample.others[2].service = which === "police" ? "ambulance" : "police";
    render(sample);
    // Flies in from the east, over home and away to the west, so the map can be seen
    // zooming in and out again.
    setInterval(function () {
      km = km > -6 ? km - 0.25 : 8;
      sample.planes[0].distanceKm = Math.abs(km);
      sample.planes[0].lon = sample.home.lon + km / 69.4;
      render(sample);
    }, 1000);
  }

  // A made-up BA4321 to Berlin: ?demo=followed waiting to leave on a plane our own sums
  // say will be late, ?demo=taxiing having left the gate late, ?demo=flying over
  // the North Sea, ?demo=landed at the gate.
  function startFollowedDemo(phase) {
    var now = Date.now();
    function at(minutes) { return new Date(now + minutes * 60000).toISOString(); }
    var flight = {
      ident: "BA4321",
      airline: "British Airways",
      airlineCode: "BAW",
      phase: { flying: "flying", taxiing: "taxiing", landed: "arrived" }[phase] || "waiting",
      origin: { code: "LHR", name: "Heathrow", city: "London", country: "GB", lat: 51.471, lon: -0.462, timezone: "Europe/London" },
      destination: { code: "BER", name: "Brandenburg", city: "Berlin", country: "DE", lat: 52.362, lon: 13.501, timezone: "Europe/Berlin" },
      aircraftType: "A320",
      registration: "G-EUYM",
      terminalOrigin: "5",
      gateOrigin: "B32",
      terminalDestination: "1",
      gateDestination: "C12",
      baggageClaim: "7"
    };
    var message = { type: "followed", homeCountry: "GB", homeTimezone: "Europe/London", flight: flight, earlierLegs: [], reason: null, position: null };
    if (flight.phase === "waiting") {
      flight.scheduledOut = at(110);
      flight.departsAt = at(135);
      flight.airlineDepartsAt = at(110);
      flight.departureEstimate = "ours";
      flight.departureDelayMinutes = 25;
      flight.landsAt = at(230);
      flight.arrivesAt = at(240);
      flight.arrivalDelayMinutes = 20;
      message.earlierLegs = [{ ident: "BA4320", origin: { code: "BER", city: "Berlin", country: "DE" }, departed: false, landed: false, arrivesAt: at(100), arrivalDelayMinutes: 25 }];
      message.reason = "Its plane isn't due in from Berlin until " +
        new Date(now + 100 * 60000).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", timeZone: "Europe/London" });
    } else if (flight.phase === "taxiing") {
      flight.scheduledOut = at(-141);
      flight.departsAt = at(-35);
      flight.departureDelayMinutes = 106;
      flight.landsAt = at(80);
      flight.arrivesAt = at(88);
      flight.arrivalDelayMinutes = 52;
    } else if (flight.phase === "flying") {
      flight.departsAt = at(-50);
      flight.landsAt = at(42);
      flight.arrivesAt = at(50);
      flight.arrivalDelayMinutes = 4;
      message.position = { lat: 53.1, lon: 4.6, trackDeg: 96, altitudeFt: 37000, speedKt: 452, at: new Date(now).toISOString() };
    } else {
      flight.departsAt = at(-120);
      flight.landsAt = at(-14);
      flight.arrivesAt = at(-6);
    }
    render(message);
  }

  var demo = new URLSearchParams(window.location.search).get("demo");
  if (["followed", "taxiing", "flying", "landed"].indexOf(demo) >= 0) {
    startFollowedDemo(demo);
  } else if (demo !== null) {
    startDemo(demo);
  } else if (onCastDevice()) {
    startCast();
  } else {
    startBrowser();
  }
})();
