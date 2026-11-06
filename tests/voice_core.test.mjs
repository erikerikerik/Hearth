import test from "node:test";
import assert from "node:assert/strict";
import { Resampler, floatToInt16, int16ToFloat, indicatorState, voiceSocketUrl, NO_RECONNECT_CODES, INDICATOR_TEXT } from "../dist/shell/voice-core.js";

const sine = (n, rate, hz) => Float32Array.from({ length: n }, (_, i) => Math.sin(2 * Math.PI * hz * i / rate));

test("48 kHz to 16 kHz yields a third of the samples and preserves a tone", () => {
  const r = new Resampler(48000, 16000);
  const out = r.process(sine(4800, 48000, 440));
  assert.ok(Math.abs(out.length - 1600) <= 1);
  const ref = sine(1600, 16000, 440);
  let err = 0;
  for (let i = 5; i < 1590; i += 1) err = Math.max(err, Math.abs(out[i] - ref[i]));
  assert.ok(err < 0.2, `max error ${err}`);
});

test("chunk boundaries do not change the length or add clicks", () => {
  const whole = new Resampler(44100, 16000).process(sine(44100, 44100, 300));
  const r = new Resampler(44100, 16000);
  const input = sine(44100, 44100, 300);
  const parts = [];
  for (let i = 0; i < input.length; i += 2048) parts.push(...r.process(input.slice(i, i + 2048)));
  assert.ok(Math.abs(parts.length - whole.length) <= 2);
  let maxStep = 0;
  for (let i = 1; i < parts.length; i += 1) maxStep = Math.max(maxStep, Math.abs(parts[i] - parts[i - 1]));
  assert.ok(maxStep < 0.2, `step ${maxStep}`);
});

test("same rate passes through", () => {
  const input = sine(100, 16000, 200);
  assert.deepEqual(Array.from(new Resampler(16000, 16000).process(input)), Array.from(input));
});

test("int16 conversion clamps and round-trips", () => {
  const out = floatToInt16(Float32Array.from([0, 1, -1, 2, -2, NaN, 0.5]));
  assert.deepEqual(Array.from(out), [0, 32767, -32768, 32767, -32768, 0, 16384]);
  assert.ok(Math.abs(int16ToFloat(Int16Array.from([16384]))[0] - 0.5) < 1e-6);
});

const base = { needsLogin: false, paused: false, trackLive: true, socketOpen: true, blocked: false, unavailable: false, needsTap: false, speaker: "idle", starting: false };

test("indicator claims listening only with a live track and an open socket", () => {
  assert.equal(indicatorState(base), "listening");
  assert.equal(indicatorState({ ...base, trackLive: false }), "starting");
  assert.equal(indicatorState({ ...base, socketOpen: false }), "reconnecting");
  assert.equal(indicatorState({ ...base, speaker: "assistant" }), "waiting");
  assert.equal(indicatorState({ ...base, speaker: "think" }), "waiting");
});

test("pause, blocked and unavailable outrank everything else", () => {
  assert.equal(indicatorState({ ...base, paused: true }), "paused");
  assert.equal(indicatorState({ ...base, paused: true, trackLive: true }), "paused");
  assert.equal(indicatorState({ ...base, blocked: true, trackLive: false }), "blocked");
  assert.equal(indicatorState({ ...base, unavailable: true, paused: true }), "unavailable");
  assert.equal(indicatorState({ ...base, needsTap: true }), "needsTap");
  for (const key of ["listening", "paused", "needsTap", "blocked", "unavailable", "waiting", "starting", "reconnecting"]) assert.ok(INDICATOR_TEXT[key]);
});

test("socket url follows the page scheme and never leaves the page host", () => {
  assert.equal(voiceSocketUrl({ protocol: "http:", host: "127.0.0.1:4173" }), "ws://127.0.0.1:4173/ws/voice");
  assert.equal(voiceSocketUrl({ protocol: "https:", host: "therapy.local" }), "wss://therapy.local/ws/voice");
  assert.ok(NO_RECONNECT_CODES.has(4401) && NO_RECONNECT_CODES.has(4503));
});

test("waiting for login is stated, and no live-mic claim is made without a socket", () => {
  assert.equal(indicatorState({ ...base, needsLogin: true, socketOpen: false, trackLive: false }), "needsLogin");
  assert.equal(indicatorState({ ...base, socketOpen: false, trackLive: true }), "reconnecting");
  assert.equal(indicatorState({ ...base, trackLive: false }), "starting");
  assert.ok(INDICATOR_TEXT.needsLogin.includes("Backstage"));
});
