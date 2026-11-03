import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { installAudioFake, installCastFake, load } from "./support.js";

let played;

beforeEach(async () => {
  vi.resetModules();
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-01-01T12:00:00Z"));
  played = installAudioFake();
  await load("speaker");
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("Speaker", () => {
  it("plays a new clip once the audience says it can be heard", () => {
    const speaker = new window.Speaker(new window.RightAway());
    speaker.say("clips/one.mp3");
    expect(played).toEqual(["clips/one.mp3"]);
  });

  it("does not play the same clip twice in a row", () => {
    const speaker = new window.Speaker(new window.RightAway());
    speaker.say("clips/one.mp3");
    speaker.say("clips/one.mp3");
    expect(played).toHaveLength(1);
    speaker.say("clips/two.mp3");
    expect(played).toEqual(["clips/one.mp3", "clips/two.mp3"]);
  });

  it("says nothing when the update has no clip", () => {
    const speaker = new window.Speaker(new window.RightAway());
    speaker.say(null);
    speaker.say("");
    expect(played).toEqual([]);
  });

  it("carries on when the browser refuses to play before a click", async () => {
    vi.stubGlobal("Audio", class { play() { return Promise.reject(new Error("NotAllowedError")); } });
    const speaker = new window.Speaker(new window.RightAway());
    expect(() => speaker.say("clips/one.mp3")).not.toThrow();
    await vi.advanceTimersByTimeAsync(0);
  });
});

describe("WhenHubUnmuted", () => {
  const SETTLE = 2000;
  const LAUNCH = 20000;
  let context;
  let audibility;

  function volumeChanged(data) { context.listeners.volume({ data }); }

  beforeEach(() => {
    context = installCastFake();
    audibility = new window.WhenHubUnmuted(context, SETTLE, LAUNCH);
  });

  it("plays at once on a Hub that has been unmuted all along", () => {
    const play = vi.fn();
    audibility.whenAudible(play);
    vi.advanceTimersByTime(0);
    expect(play).toHaveBeenCalledTimes(1);
  });

  it("plays at once when the Hub does not report a volume", () => {
    context.volume = null;
    const play = vi.fn();
    audibility.whenAudible(play);
    vi.advanceTimersByTime(0);
    expect(play).toHaveBeenCalledTimes(1);
  });

  it("holds a clip from the launch until the Hub is unmuted, then waits for the sound to settle", () => {
    context.volume = { muted: true };
    const play = vi.fn();
    audibility.whenAudible(play);
    vi.advanceTimersByTime(5000);
    expect(play).not.toHaveBeenCalled();

    context.volume = { muted: false };
    volumeChanged({ muted: false });
    vi.advanceTimersByTime(SETTLE - 1);
    expect(play).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    expect(play).toHaveBeenCalledTimes(1);
  });

  it("waits out the settling time for a clip that arrives just after an unmute", () => {
    volumeChanged({ muted: false });
    const play = vi.fn();
    audibility.whenAudible(play);
    vi.advanceTimersByTime(SETTLE - 1);
    expect(play).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    expect(play).toHaveBeenCalledTimes(1);
  });

  it("drops a clip when the Hub is muted after the launch, because a person muted it", () => {
    vi.advanceTimersByTime(LAUNCH + 1);
    context.volume = { muted: true };
    const play = vi.fn();
    audibility.whenAudible(play);
    context.volume = { muted: false };
    volumeChanged({ muted: false });
    vi.advanceTimersByTime(SETTLE * 2);
    expect(play).not.toHaveBeenCalled();
  });

  it("forgets a clip that was still waiting when the launch ended", () => {
    context.volume = { muted: true };
    const play = vi.fn();
    audibility.whenAudible(play);
    vi.advanceTimersByTime(LAUNCH + 1);
    context.volume = { muted: false };
    volumeChanged({ muted: false });
    vi.advanceTimersByTime(SETTLE * 2);
    expect(play).not.toHaveBeenCalled();
  });

  it("ignores volume changes that leave the Hub muted or carry no data", () => {
    context.volume = { muted: true };
    const play = vi.fn();
    audibility.whenAudible(play);
    volumeChanged({ muted: true });
    volumeChanged(undefined);
    vi.advanceTimersByTime(SETTLE * 2);
    expect(play).not.toHaveBeenCalled();
  });
});
