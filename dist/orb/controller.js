import { resolve } from "./registry.js";

function p95(values) {
  if (!values.length) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.floor((sorted.length - 1) * 0.95)];
}

export class OrbController {
  constructor(host, requested = "filament-v1") {
    this.host = host;
    this.requested = requested;
    this.failures = 0;
    this.timings = [];
    this.slowSince = 0;
    this.factory = resolve(requested);
    this.renderer = this.factory.create(host);
  }
  resize(layout) { try { this.renderer.resize(layout); } catch (error) { this.#failed(error); } }
  frame(input) {
    const start = performance.now();
    try { this.renderer.frame(input); this.failures = 0; } catch (error) { this.#failed(error); }
    const elapsed = performance.now() - start;
    this.timings.push(elapsed);if (this.timings.length > 120) this.timings.shift();
    const slow = p95(this.timings) > 24;
    if (slow && !this.slowSince) this.slowSince = finiteNow(input?.t);
    if (!slow) this.slowSince = 0;
    if (slow && finiteNow(input?.t) - this.slowSince >= 2) {
      if (this.host.quality === "high") this.#quality("balanced");
      else if (this.host.quality === "balanced") this.#quality("low");
      else this.#fallback("slow_renderer");
      this.slowSince = finiteNow(input?.t);this.timings.length = 0;
    }
  }
  event(event) { try { this.renderer.event?.(event); } catch (error) { this.#failed(error); } }
  metrics() {
    return {
      ...(this.renderer.metrics?.() || {}),
      activeRenderer: `${this.factory.name}@${String(this.factory.version).split(".")[0]}`,
      quality: this.host.quality,
      frameP95Ms: p95(this.timings),
    };
  }
  outerRadius() { return this.renderer.outerRadius?.() || 0; }
  forceFallback(reason = "shell_degraded") { this.#fallback(reason); }
  dispose() { this.renderer.dispose(); }
  #quality(next) { this.host.quality = next;this.renderer.setQuality?.(next); }
  #failed(error) { this.host.log("orb renderer failure", { renderer: this.factory.name, error: String(error) });if (++this.failures >= 3) this.#fallback("three_failures"); }
  #fallback(reason) {
    if (this.factory.name === "fallback-ring") return;
    this.renderer.dispose();this.factory = resolve("fallback-ring");this.renderer = this.factory.create(this.host);this.failures = 0;
    this.host.log("orb fallback active", { reason });
  }
}

function finiteNow(value) { return Number.isFinite(value) ? value : 0; }
