import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { register, resolve } from "../dist/orb/registry.js";
import { fallbackRingFactory } from "../dist/orb/fallback-ring.js";
import { filamentV1Factory } from "../dist/orb/filament-v1.js";
import { createSeededRng } from "../dist/orb/seeded-rng.js";
import { OrbController } from "../dist/orb/controller.js";

register(fallbackRingFactory);
register(filamentV1Factory);
const fixtures = JSON.parse(await readFile(new URL("../dev_ui/synthetic-replays.json", import.meta.url), "utf8"));

function mix(hash, value) {
  if (typeof value === "number") {
    hash ^= Number.isFinite(value) ? Math.round(value * 10000) : 0x7fc00000;
    return Math.imul(hash, 16777619) >>> 0;
  }
  const text = String(value);
  for (let index = 0; index < text.length; index += 1) {
    hash ^= text.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

class FakeGradient {
  constructor(context) { this.context = context; }
  addColorStop(at, color) { this.context.record("stop", at, color); }
}

class FakeContext {
  constructor() { this.hash = 2166136261;this.strokeCalls = 0; }
  record(...values) { for (const value of values) this.hash = mix(this.hash, value); }
  digest() { return this.hash.toString(16).padStart(8, "0"); }
  setTransform(...x) { this.record("transform", ...x); } clearRect(...x) { this.record("clear", ...x); }
  createRadialGradient(...x) { this.record("gradient", ...x);return new FakeGradient(this); }
  beginPath() { this.record("begin"); } arc(...x) { this.record("arc", ...x); }
  fill() { this.record("fill"); } moveTo(...x) { this.record("move", ...x); }
  lineTo(...x) { this.record("line", ...x); } stroke() { this.strokeCalls += 1;this.record("stroke"); }
  set strokeStyle(value) { this.record("strokeStyle", value); }
  set fillStyle(value) { this.record("fillStyle", value); }
  set lineWidth(value) { this.record("lineWidth", value); }
  set lineJoin(value) { this.record("lineJoin", value); }
  set lineCap(value) { this.record("lineCap", value); }
  set globalCompositeOperation(value) { this.record("composite", value); }
}

class FakeCanvas {
  constructor() { this.context = new FakeContext(); }
  getContext(kind) { return kind === "2d" ? this.context : null; }
}

function host(seed, reducedMotion = false, quality = "high") {
  return { canvas: new FakeCanvas(), rng: createSeededRng(seed), reducedMotion, quality, log() {} };
}

function layout(renderer) {
  renderer.resize({ width: 400, height: 400, dpr: 1, cx: 200, cy: 200, radius: 136, wellRadius: 72 });
}

function validateGeometry(metrics, frame, fixtureName) {
  assert.ok(Number.isFinite(metrics.minRadius), `${fixtureName}: real minimum radius`);
  assert.ok(Number.isFinite(metrics.maxRadius), `${fixtureName}: real maximum radius`);
  assert.ok(metrics.minRadius > 0, `${fixtureName}: positive radius`);
  assert.ok(metrics.maxRadius <= 1.42, `${fixtureName}: outer radius bound`);
  assert.ok(metrics.bodyDeviationP95 <= 0.10, `${fixtureName}: body deviation bound`);
  assert.ok(metrics.prominences <= 3, `${fixtureName}: prominence count`);
  assert.ok(metrics.wellMaxAlpha <= 0.5, `${fixtureName}: translucent well`);
  assert.ok(metrics.minOpaqueRadius * 136 >= 72 * 0.95, `${fixtureName}: opaque geometry clears well`);
  const lowHue = Math.min(frame.mood.hueA, frame.mood.hueB);
  const highHue = Math.max(frame.mood.hueA, frame.mood.hueB);
  assert.ok(metrics.hueMin >= lowHue - 0.001, `${fixtureName}: hue floor`);
  assert.ok(metrics.hueMax <= highHue + 0.001, `${fixtureName}: hue ceiling`);
  assert.ok(metrics.samplesPerStrand >= 200, `${fixtureName}: sample floor`);
}

function runFixture(factory, fixture, reducedMotion = false, quality = "high") {
  const instanceHost = host(fixture.seed, reducedMotion, quality);
  const renderer = factory.create(instanceHost);layout(renderer);
  let eventIndex = 0;
  let maxProminences = 0;
  for (const frame of fixture.frames) {
    while (fixture.events[eventIndex]?.at <= frame.t) renderer.event?.(fixture.events[eventIndex++]);
    renderer.frame({ ...frame, dt: 1 / fixture.fps, bands: new Float32Array(frame.bands) });
    const metrics = renderer.metrics();validateGeometry(metrics, frame, fixture.name);
    maxProminences = Math.max(maxProminences, metrics.prominences);
  }
  const result = {
    hash: instanceHost.canvas.context.digest(), metrics: renderer.metrics(), maxProminences,
    strokeCalls: instanceHost.canvas.context.strokeCalls,
  };
  renderer.dispose();return result;
}

const baselineResults = new Map();
function baseline(fixture) {
  if (!baselineResults.has(fixture.name)) baselineResults.set(fixture.name, runFixture(filamentV1Factory, fixture));
  return baselineResults.get(fixture.name);
}

test("registry resolves versioned renderers without coupling them to the shell", () => {
  assert.equal(resolve("filament-v1").name, "filament-v1");
  assert.equal(resolve("filament-v1@1").version, "1.1.0");
  assert.equal(resolve("unknown-orb").name, "filament-v1");
});

test("all seven fixtures cover thirty to sixty seconds", () => {
  assert.deepEqual(fixtures.map((fixture) => fixture.name), ["quiet-room","calm-speaker","agitated-speaker","assistant-reply","interruption","long-silence","memory-kept"]);
  for (const fixture of fixtures) {
    assert.ok(fixture.duration >= 30 && fixture.duration <= 60, fixture.name);
    assert.equal(fixture.frames.length, fixture.duration * fixture.fps, fixture.name);
  }
});

test("all long-form filament replays report measured, bounded geometry", () => {
  for (const fixture of fixtures) {
    const result = baseline(fixture);
    assert.equal(result.metrics.minRadiusObserved <= result.metrics.maxRadiusObserved, true, fixture.name);
  }
});

test("a forty-five-second agitated replay is deterministic", () => {
  const fixture = fixtures.find((item) => item.name === "agitated-speaker");
  assert.equal(baseline(fixture).hash, runFixture(filamentV1Factory, fixture).hash);
});

test("agitated replay exercises bounded, expiring prominences", () => {
  const result = baseline(fixtures.find((fixture) => fixture.name === "agitated-speaker"));
  assert.ok(result.maxProminences > 0);
  assert.ok(result.metrics.maxProminencesObserved <= 3);
  assert.ok(result.metrics.maxProminenceAgeObserved <= 8);
});

test("quiet and reduced variants obey their motion budgets", () => {
  const quiet = baseline(fixtures.find((fixture) => fixture.name === "quiet-room"));
  assert.equal(quiet.maxProminences, 0);
  const reduced = runFixture(filamentV1Factory, fixtures.find((fixture) => fixture.name === "agitated-speaker"), true);
  assert.equal(reduced.maxProminences, 0);
  assert.ok(reduced.metrics.bodyDeviationP95 <= 0.02);
});

test("every quality tier keeps at least two hundred samples", () => {
  const fixture = fixtures.find((item) => item.name === "calm-speaker");
  const tiers = ["high", "balanced", "low"].map((quality) => runFixture(filamentV1Factory, { ...fixture, frames: fixture.frames.slice(0, 1) }, false, quality));
  assert.deepEqual(tiers.map((result) => result.metrics.samplesPerStrand), [260, 230, 200]);
  assert.deepEqual(tiers.map((result) => result.metrics.strandCount), [30, 24, 18]);
  assert.ok(tiers[0].strokeCalls > tiers[1].strokeCalls && tiers[1].strokeCalls > tiers[2].strokeCalls);
});

test("fallback ring reports its drawn geometry", () => {
  const instanceHost = host(300);const renderer = fallbackRingFactory.create(instanceHost);layout(renderer);
  renderer.frame({ energy: 0.5, mood: { hueA: 287 } });
  const metrics = renderer.metrics();
  assert.equal(metrics.minRadius, 1.009);assert.equal(metrics.maxRadius, 1.009);
  assert.ok(Math.abs(metrics.bodyDeviationP95 - 0.009) < 1e-12);assert.equal(metrics.hueMin, 287);
  renderer.dispose();
});

test("filament is fuzz safe", () => {
  const renderer = filamentV1Factory.create(host(400));layout(renderer);
  const values = [NaN, Infinity, -Infinity, -1, 0, 1, 999];
  for (const value of values) {
    assert.doesNotThrow(() => renderer.frame({ t: value, dt: value, bands: [value], energy: value, speaker: "idle", calm: value, mood: { hueA: value, hueB: value } }));
  }
  renderer.resize({ width: 0, height: 0, radius: 0 });assert.doesNotThrow(() => renderer.frame({}));renderer.dispose();
});

test("controller replaces a renderer after three consecutive failures", () => {
  register({ name: "throwing-test", version: "1.0.0", contract: "1.x", capabilities: { drawsOwnSpark: false, usesWebGL: false, hasReducedVariant: true }, create() { return { resize() {}, frame() { throw new Error("synthetic"); }, dispose() {} }; } });
  const controller = new OrbController(host(500), "throwing-test");
  controller.frame({ t: 0 });controller.frame({ t: 0.1 });controller.frame({ t: 0.2 });
  assert.equal(controller.factory.name, "fallback-ring");controller.dispose();
});

test("controller exposes renderer, quality and measured frame timing", () => {
  const controller = new OrbController(host(501), "filament-v1");layout(controller);
  controller.frame({ t: 0, dt: 1 / 30, bands: new Float32Array(8), energy: 0, mood: { hueA: 280, hueB: 320 } });
  const metrics = controller.metrics();
  assert.equal(metrics.activeRenderer, "filament-v1@1");
  assert.equal(metrics.quality, "high");
  assert.ok(Number.isFinite(metrics.frameP95Ms) && metrics.frameP95Ms >= 0);
  controller.dispose();
});

test("one hundred create and dispose cycles complete", () => {
  for (let index = 0; index < 100; index += 1) {
    const renderer = filamentV1Factory.create(host(index + 1));layout(renderer);renderer.dispose();
  }
});
