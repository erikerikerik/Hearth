function finite(value, fallback = 0) { return Number.isFinite(value) ? value : fallback; }
function clamp(value, low, high) { return Math.min(high, Math.max(low, finite(value, low))); }

export const fallbackRingFactory = Object.freeze({
  name: "fallback-ring",
  version: "1.0.0",
  contract: "1.x",
  capabilities: { drawsOwnSpark: false, usesWebGL: false, hasReducedVariant: true },
  create(host) {
    const context = host.canvas.getContext("2d");
    let layout = { width: 0, height: 0, dpr: 1, cx: 0, cy: 0, radius: 0, wellRadius: 0 };
    let quality = host.quality;
    let disposed = false;
    let lastScale = 1;
    let lastHue = 280;
    let minRadiusObserved = Infinity;
    let maxRadiusObserved = 0;
    return {
      resize(next) { layout = { ...layout, ...(next || {}) }; },
      frame(input = {}) {
        if (disposed || !context) return;
        const dpr = Math.max(1, finite(layout.dpr, 1));
        const width = Math.max(0, finite(layout.width));
        const height = Math.max(0, finite(layout.height));
        context.setTransform(dpr, 0, 0, dpr, 0, 0);
        context.clearRect(0, 0, width, height);
        if (!width || !height || !layout.radius) return;
        const energy = clamp(input.energy, 0, 1);
        const scale = 1 + (host.reducedMotion ? 0.008 : 0.018) * energy;
        const hue = finite(input.mood?.hueA, 280);
        lastScale = scale;
        lastHue = hue;
        minRadiusObserved = Math.min(minRadiusObserved, scale);
        maxRadiusObserved = Math.max(maxRadiusObserved, scale);
        context.beginPath();
        context.arc(layout.cx, layout.cy, layout.radius * scale, 0, Math.PI * 2);
        context.strokeStyle = `hsla(${hue},70%,72%,${0.45 + energy * 0.3})`;
        context.lineWidth = quality === "low" ? 1.5 : 2.2;
        context.stroke();
      },
      setQuality(next) { quality = next; },
      outerRadius() { return Math.max(0, finite(layout.radius)) * (maxRadiusObserved || lastScale); },
      metrics() {
        return {
          minRadius: lastScale, maxRadius: lastScale,
          minRadiusObserved: Number.isFinite(minRadiusObserved) ? minRadiusObserved : lastScale,
          maxRadiusObserved: maxRadiusObserved || lastScale,
          bodyDeviationP95: Math.abs(lastScale - 1), prominences: 0,
          maxProminencesObserved: 0, maxProminenceAgeObserved: 0,
          wellMaxAlpha: 0, minOpaqueRadius: lastScale,
          hueMin: lastHue, hueMax: lastHue,
          samplesPerStrand: 0, strandCount: 1,
        };
      },
      dispose() { disposed = true; layout = { width: 0, height: 0, dpr: 1, cx: 0, cy: 0, radius: 0, wellRadius: 0 }; },
    };
  },
});
