import test from "node:test";
import assert from "node:assert/strict";
import { normalizeRealtimeEvent, RealtimeClient } from "../dist/shell/realtime.js";
import { MockEventServer } from "../dist/shell/mock-event-server.js";
import { aggregateFrequencyBands, applyAutoGain, dbToUnit, quietBands } from "../dist/shell/audio-bands.js";

test("protocol accepts the U2 event vocabulary and rejects unknown events", () => {
  const event = normalizeRealtimeEvent({ type: "turn.state", v: 1, ts: 1, speaker: "user", turn_id: "t1" });
  assert.equal(event.speaker, "user");
  assert.throws(() => normalizeRealtimeEvent({ type: "made.up", v: 1, ts: 2 }), /unknown/);
  assert.throws(() => normalizeRealtimeEvent({ type: "turn.state", v: 2, ts: 3, speaker: "idle" }), /envelope/);
});

test("calm estimates are bounded and memory text remains data", () => {
  assert.equal(normalizeRealtimeEvent({ type: "calm.estimate", v: 1, ts: 1, value: 9 }).value, 1);
  const memory = normalizeRealtimeEvent({ type: "memory.candidate", v: 1, ts: 2, id: "m1", category: "patterns", text: "<img onerror=alert(1)>", status: "candidate" });
  assert.equal(memory.text, "<img onerror=alert(1)>");
});

test("mock server acknowledges mic pause and resume", async () => {
  const delivered = [];
  const server = new MockEventServer({ clock: () => 10, schedule: (callback) => callback() });
  const client = new RealtimeClient({ onEvent: (event) => delivered.push(event), clock: () => 9 }).connect(server);
  client.send({ type: "ui.mic", paused: true });
  client.send({ type: "ui.mic", paused: false });
  assert.deepEqual(server.received.map((event) => event.paused), [true, false]);
  assert.deepEqual(delivered.map((event) => event.paused), [true, false]);
  client.dispose();
});

test("out-of-order backend events are rejected", () => {
  const client = new RealtimeClient();
  client.receive({ type: "calm.estimate", v: 1, ts: 5, value: 0.5 });
  assert.throws(() => client.receive({ type: "calm.estimate", v: 1, ts: 4, value: 0.6 }), /out-of-order/);
});

test("audio band mapping keeps silence at the floor and locates a synthetic tone", () => {
  assert.equal(dbToUnit(-60), 0);
  assert.equal(dbToUnit(-20), 1);
  const bins = new Float32Array(512);bins.fill(-100);
  const toneBin = Math.round(440 / 24000 * bins.length);bins[toneBin] = -20;
  const bands = aggregateFrequencyBands(bins, 48000, 1024);
  assert.equal(bands.indexOf(Math.max(...bands)), 2);
  assert.deepEqual([...quietBands("idle", 0, true)], Array(8).fill(0.019999999552965164));
});

test("auto-gain lifts a quiet band but never attenuates and never exceeds 1", () => {
  const peaks = new Float32Array(3);
  const quiet = applyAutoGain(Float32Array.from([0.1, 0.9, 0.01]), peaks, 0.016);
  assert.ok(quiet[0] > 0.25 && quiet[0] <= 0.31, "0.1 raw is lifted by about 3x");
  assert.ok(quiet[1] >= 0.9, "a loud band is never attenuated");
  assert.equal(quiet[2], Float32Array.from([0.01])[0], "silence is left alone");
  const clipped = applyAutoGain(Float32Array.from([1, 1, 1]), new Float32Array(3), 0.016);
  assert.ok(clipped.every((v) => v <= 1));
});

test("auto-gain peak decays so a later quiet passage regains gain", () => {
  const peaks = Float32Array.from([1]);
  for (let step = 0; step < 100; step += 1) applyAutoGain(Float32Array.from([0.1]), peaks, 0.1);
  assert.ok(peaks[0] < 0.4);
});
