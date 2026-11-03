// Plays the watcher's announcement clip through the device's own speaker, once
// for each new clip. The watcher sends the same clip with every update while a
// plane stays nearest, and none for a plane it has already announced.
//
// The watcher mutes the Hub while the card launches, to hide its chime, and the
// sound takes a moment to come back after it is unmuted. During the launch a clip
// waits until the Hub says it is unmuted, then a little longer, so the start is
// not lost. A Hub that is still muted after that was muted by someone in the
// room, and its announcements are dropped rather than saved for later.

(function () {
  "use strict";

  // In a browser there is nothing to wait for.
  function RightAway() {}

  RightAway.prototype.whenAudible = function (play) { play(); };

  // On the Hub, follows its system volume through the Cast receiver context.
  function WhenHubUnmuted(context, settleMs, launchMs) {
    var self = this;
    this.context = context;
    this.settleMs = settleMs;
    this.launchEndsAt = Date.now() + launchMs;
    this.audibleAt = 0;
    this.waiting = null;
    // Whatever is still waiting when the launch is over was muted by a person.
    setTimeout(function () { self.waiting = null; }, launchMs);
    context.addEventListener(cast.framework.system.EventType.SYSTEM_VOLUME_CHANGED, function (event) {
      if (event.data && !event.data.muted) {
        self.audibleAt = Date.now() + settleMs;
        if (self.waiting) {
          var play = self.waiting;
          self.waiting = null;
          self.whenAudible(play);
        }
      }
    });
  }

  WhenHubUnmuted.prototype.whenAudible = function (play) {
    var volume = this.context.getSystemVolume();
    if (volume && volume.muted) {
      this.waiting = Date.now() < this.launchEndsAt ? play : null;
      return;
    }
    setTimeout(play, Math.max(0, this.audibleAt - Date.now()));
  };

  function Speaker(audibility) {
    this.audibility = audibility;
    this.audio = new Audio();
    this.played = null;
  }

  Speaker.prototype.say = function (url) {
    if (!url || url === this.played) { return; }
    this.played = url;
    var speaker = this;
    this.audibility.whenAudible(function () { speaker.play(url); });
  };

  Speaker.prototype.play = function (url) {
    this.audio.src = url;
    // A browser tab may refuse to play before anyone has clicked; the card still shows.
    var playing = this.audio.play();
    if (playing && playing.catch) { playing.catch(function () {}); }
  };

  window.Speaker = Speaker;
  window.RightAway = RightAway;
  window.WhenHubUnmuted = WhenHubUnmuted;
})();
