// Pure helpers for the voice loop. No browser APIs here so they can be unit-tested in Node.

export const TARGET_RATE = 16000;

export function floatToInt16(samples) {
  const out = new Int16Array(samples.length);
  for (let index = 0; index < samples.length; index += 1) {
    const value = Math.max(-1, Math.min(1, Number.isFinite(samples[index]) ? samples[index] : 0));
    out[index] = value < 0 ? Math.round(value * 32768) : Math.round(value * 32767);
  }
  return out;
}

export function int16ToFloat(samples) {
  const out = new Float32Array(samples.length);
  for (let index = 0; index < samples.length; index += 1) out[index] = samples[index] / 32768;
  return out;
}

// Streaming linear-interpolation resampler. Keeps one sample of carry between calls so chunk
// boundaries do not click. Averaging when downsampling by a large factor is left to the
// browser's own anti-aliasing (echoCancellation / noiseSuppression run before this).
export class Resampler {
  constructor(inRate, outRate = TARGET_RATE) {
    this.step = inRate / outRate;
    this.position = 0;      // fractional read position into the next input block, in input samples
    this.previous = 0;      // last sample of the previous block
  }

  process(input) {
    if (this.step === 1) return Float32Array.from(input);
    const out = [];
    let position = this.position;
    while (position < input.length) {
      const index = Math.floor(position);
      const fraction = position - index;
      const left = index === 0 ? this.previous : input[index - 1];
      // position p refers to the point between input[index-1] and input[index]
      out.push(left + (input[index] - left) * fraction);
      position += this.step;
    }
    this.position = position - input.length;
    this.previous = input.length ? input[input.length - 1] : this.previous;
    return Float32Array.from(out);
  }
}

export const INDICATOR_TEXT = Object.freeze({
  starting: "Starting microphone…",
  listening: "Microphone on · listening",
  waiting: "Microphone on · waiting while I speak",
  paused: "Microphone off · curtain open",
  needsTap: "Tap anywhere to start listening",
  blocked: "Microphone blocked · allow it in the browser's site settings",
  unavailable: "Voice is not installed · text only",
  needsLogin: "Voice waits for the password · open Backstage and unlock",
  reconnecting: "Reconnecting voice…",
});

// What the indicator should say, from facts only. "listening" is claimed only when a live
// microphone track exists and the socket is open.
export function indicatorState({ paused, trackLive, socketOpen, blocked, unavailable, needsTap, needsLogin, speaker, starting }) {
  if (unavailable) return "unavailable";
  if (paused) return "paused";
  if (needsLogin) return "needsLogin";
  if (blocked) return "blocked";
  if (needsTap) return "needsTap";
  if (!socketOpen) return "reconnecting";
  if (starting || !trackLive) return "starting";
  return speaker === "think" || speaker === "assistant" ? "waiting" : "listening";
}

export function voiceSocketUrl(location) {
  return (location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ws/voice";
}

export const NO_RECONNECT_CODES = new Set([4401, 4403, 4503]);
