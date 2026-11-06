function finite(value, fallback = 0) { return Number.isFinite(value) ? value : fallback; }
function clamp(value, low, high) { return Math.min(high, Math.max(low, finite(value, low))); }
function smooth(low, high, value) { const t = clamp((value - low) / (high - low), 0, 1);return t * t * (3 - 2 * t); }
function percentile(values, p) {
  if (!values.length) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.min(sorted.length - 1, Math.floor((sorted.length - 1) * p))];
}
function hueBetween(a, b, amount) { return finite(a, 280) + (finite(b, 320) - finite(a, 280)) * clamp(amount, 0, 1); }

export const filamentV1Factory = Object.freeze({
  name: "filament-v1",
  version: "1.1.0",
  contract: "1.x",
  capabilities: { drawsOwnSpark: false, usesWebGL: false, hasReducedVariant: true },
  create(host) {
    const context = host.canvas.getContext("2d");
    let layout = { width: 0, height: 0, dpr: 1, cx: 0, cy: 0, radius: 0, wellRadius: 0 };
    let quality = host.quality;
    let disposed = false;
    let cooldown = 0;
    let serial = 0;
    let minRadiusObserved = Infinity;
    let maxRadiusObserved = 0;
    let maxProminencesObserved = 0;
    let maxProminenceAgeObserved = 0;
    let frameMetrics = emptyMetrics();
    const smoothed = new Float32Array(8);
    const prominences = [];
    const strands = Array.from({ length: 30 }, () => ({
      scale: 0.88 + host.rng() * 0.20,
      phase: host.rng() * Math.PI * 2,
      orientation: host.rng() * Math.PI,
      tilt: 0.10 + host.rng() * 0.28,
      tiltPhase: host.rng() * Math.PI * 2,
      drift: (host.rng() - 0.5) * 0.18,
      width: 0.55 + host.rng() * 0.60,
      alpha: 0.42 + host.rng() * 0.55,
      bandA: Math.floor(host.rng() * 8),
      bandB: Math.floor(host.rng() * 8),
      lobesA: 2 + Math.floor(host.rng() * 4),
      lobesB: 3 + Math.floor(host.rng() * 5),
      responsiveness: 0.12 + 0.88 * Math.pow(host.rng(), 2.2),
    }));
    const blobs = Array.from({ length: 12 }, () => ({
      angle: host.rng() * Math.PI * 2, radius: host.rng() * 0.62,
      size: 0.38 + host.rng() * 0.40, speed: 0.05 + host.rng() * 0.12,
      hue: host.rng(), alpha: 0.05 + host.rng() * 0.07,
    }));
    const dust = Array.from({ length: 70 }, () => ({
      angle: host.rng() * Math.PI * 2, radius: 1.05 + host.rng() * 0.75,
      speed: (host.rng() - 0.5) * 0.03, size: 0.6 + host.rng() * 1.3,
      phase: host.rng() * Math.PI * 2,
    }));

    function emptyMetrics() {
      return {
        minRadius: 1, maxRadius: 1, bodyDeviationP95: 0, prominences: 0,
        wellMaxAlpha: 0.28, minOpaqueRadius: 1, hueMin: 0, hueMax: 0,
        samplesPerStrand: 260, strandCount: 30,
      };
    }

    function sanitizedBands(input) {
      const source = input?.bands && typeof input.bands.length === "number" ? input.bands : [];
      return Array.from({ length: 8 }, (_, index) => clamp(Number(source[index]), 0, 1));
    }

    function update(input) {
      const dt = clamp(input?.dt, 0, 0.05);
      const bands = sanitizedBands(input);
      for (let index = 0; index < 8; index += 1) {
        const rate = bands[index] > smoothed[index] ? 3.2 : 1.6;
        smoothed[index] += (bands[index] - smoothed[index]) * (1 - Math.exp(-dt * rate));
      }
      const energy = clamp(input?.energy, 0, 1);
      cooldown -= dt;
      for (let index = prominences.length - 1; index >= 0; index -= 1) {
        prominences[index].age += dt * (0.8 + energy * 1.4);
        maxProminenceAgeObserved = Math.max(maxProminenceAgeObserved, prominences[index].age);
        if (prominences[index].age >= prominences[index].life) prominences.splice(index, 1);
      }
      if (!host.reducedMotion && energy > 0.035 && cooldown <= 0 && prominences.length < 3) {
        if (host.rng() < Math.min(1, dt * (0.25 + energy * 4))) {
          prominences.push({
            id: serial++, angle: host.rng() * Math.PI * 2, width: 0.2 + host.rng() * 0.38,
            amplitude: (host.rng() < 0.78 ? 1 : -1) * (0.07 + host.rng() * 0.20) * Math.min(1, 0.4 + energy * 2),
            age: 0, life: 3.2 + host.rng() * 3.8, drift: (host.rng() - 0.5) * 0.25,
            strandOffset: Math.floor(host.rng() * strands.length), count: 3 + Math.floor(host.rng() * 5),
          });
          cooldown = 0.4 + host.rng() * 1.4 / (0.4 + energy * 3);
        }
      }
      maxProminencesObserved = Math.max(maxProminencesObserved, prominences.length);
      return { energy };
    }

    function deviationsFor(strand, strandIndex, angle, input, energy) {
      const reduced = host.reducedMotion;
      const drive = reduced ? 0.08 : 0.25 + 0.9 * energy;
      const time = finite(input?.t);
      let body = reduced
        ? 0.012 * Math.sin(time * 0.18 + strand.phase)
        : (smoothed[strand.bandA] * 0.10 * Math.sin(strand.lobesA * angle + strand.phase + time * strand.drift * drive)
          + smoothed[strand.bandB] * 0.06 * Math.sin(strand.lobesB * angle - strand.phase + time * strand.drift * drive * 0.7)) * strand.responsiveness;
      body = clamp(body, reduced ? -0.02 : -0.07, reduced ? 0.02 : 0.07);
      let prominence = 0;
      if (!reduced) {
        for (const active of prominences) {
          const relative = (strandIndex - active.strandOffset + strands.length) % strands.length;
          if (relative >= active.count) continue;
          const centre = active.angle + active.drift * active.age + (relative - active.count / 2) * 0.04;
          const delta = Math.atan2(Math.sin(angle - centre), Math.cos(angle - centre));
          const envelope = Math.pow(Math.sin(Math.PI * active.age / active.life), 1.5);
          prominence += active.amplitude * envelope * Math.exp(-(delta * delta) / (2 * active.width * active.width));
        }
      }
      return { body, total: clamp(body + prominence, -0.22, 0.30) };
    }

    function drawFilaments(input, energy, radius, cx, cy, hueA, hueB, time) {
      const strandCount = quality === "low" ? 18 : quality === "balanced" ? 24 : 30;
      const samples = quality === "low" ? 200 : quality === "balanced" ? 230 : 260;
      const bodyDeviations = [];
      const drawnRadii = [];
      const usedHues = [];
      for (let strandIndex = 0; strandIndex < strandCount; strandIndex += 1) {
        const strand = strands[strandIndex];
        const points = [];
        const tilt = host.reducedMotion ? strand.tilt * 0.25 : strand.tilt * (0.72 + 0.28 * Math.sin(time * 0.08 + strand.tiltPhase));
        const orientation = strand.orientation + time * strand.drift * (0.25 + energy * 0.9);
        const cosine = Math.cos(orientation), sine = Math.sin(orientation);
        for (let sample = 0; sample <= samples; sample += 1) {
          const angle = sample / samples * Math.PI * 2;
          const deviation = deviationsFor(strand, strandIndex, angle, input, energy);
          bodyDeviations.push(Math.abs(deviation.body));
          const actualNorm = clamp(strand.scale * (1 + deviation.total), 0.78, 1.42);
          const actual = radius * actualNorm;
          const localX = Math.cos(angle) * actual;
          const localY = Math.sin(angle) * Math.cos(tilt) * actual;
          const x = localX * cosine - localY * sine;
          const y = localX * sine + localY * cosine;
          const projected = Math.hypot(x, y) / radius;
          drawnRadii.push(projected);
          points.push({ x: cx + x, y: cy + y, z: Math.sin(angle) * Math.sin(tilt), light: x / radius - y / radius * 0.55 });
        }
        const segment = 5;
        for (let start = 0; start < samples; start += segment) {
          const end = Math.min(samples, start + segment);
          const middle = points[Math.floor((start + end) / 2)];
          const facing = Math.pow(1 - Math.min(1, Math.abs(middle.z)), 1.7);
          const alpha = facing * (0.55 + 0.45 * (middle.z + 1) / 2) * (0.6 + 0.4 * strand.alpha);
          const hue = hueBetween(hueA, hueB, smooth(-0.7, 0.7, middle.light));
          usedHues.push(hue);
          const lightness = 66 + 28 * smooth(0.4, 1, middle.light) + 10 * smooth(0.5, 1, -middle.light);
          context.beginPath();context.moveTo(points[start].x, points[start].y);
          for (let index = start + 1; index <= end; index += 1) context.lineTo(points[index].x, points[index].y);
          context.lineJoin = "round";context.lineCap = "butt";
          context.lineWidth = 5;context.strokeStyle = `hsla(${hue},74%,${lightness * 0.9}%,${alpha * 0.08})`;context.stroke();
          context.lineWidth = 1.25 * strand.width;context.strokeStyle = `hsla(${hue},74%,${lightness}%,${Math.min(0.9, alpha * 1.7)})`;context.stroke();
        }
      }
      const minRadius = drawnRadii.length ? Math.min(...drawnRadii) : 1;
      const maxRadius = drawnRadii.length ? Math.max(...drawnRadii) : 1;
      minRadiusObserved = Math.min(minRadiusObserved, minRadius);
      maxRadiusObserved = Math.max(maxRadiusObserved, maxRadius);
      frameMetrics = {
        minRadius, maxRadius, bodyDeviationP95: percentile(bodyDeviations, 0.95),
        prominences: host.reducedMotion ? 0 : prominences.length,
        wellMaxAlpha: 0.28,
        minOpaqueRadius: minRadius,
        hueMin: usedHues.length ? Math.min(...usedHues) : Math.min(hueA, hueB),
        hueMax: usedHues.length ? Math.max(...usedHues) : Math.max(hueA, hueB),
        samplesPerStrand: samples, strandCount,
      };
    }

    return {
      resize(next) { layout = { ...layout, ...(next || {}) }; },
      frame(input = {}) {
        if (disposed || !context) return;
        const dpr = Math.max(1, finite(layout.dpr, 1));
        const width = Math.max(0, finite(layout.width));
        const height = Math.max(0, finite(layout.height));
        context.setTransform(dpr, 0, 0, dpr, 0, 0);context.clearRect(0, 0, width, height);
        if (!width || !height || !finite(layout.radius)) { frameMetrics = emptyMetrics();return; }
        const { energy } = update(input);
        const radius = Math.max(0, finite(layout.radius));
        const cx = finite(layout.cx, width / 2), cy = finite(layout.cy, height / 2);
        const hueA = finite(input?.mood?.hueA, 280), hueB = finite(input?.mood?.hueB, 320);
        const time = finite(input?.t);
        context.globalCompositeOperation = "lighter";
        const haze = context.createRadialGradient(cx - radius * 0.2, cy - radius * 0.12, 0, cx, cy, radius * 1.08);
        haze.addColorStop(0, `hsla(${hueA},76%,52%,0.28)`);haze.addColorStop(1, `hsla(${hueA},76%,42%,0)`);
        context.fillStyle = haze;context.beginPath();context.arc(cx, cy, radius * 1.08, 0, Math.PI * 2);context.fill();
        if (!host.reducedMotion) {
          for (const blob of blobs) {
            const angle = blob.angle + time * blob.speed;
            const bx = cx + Math.cos(angle) * blob.radius * radius, by = cy + Math.sin(angle * 1.2) * blob.radius * radius;
            const size = blob.size * radius, hue = hueBetween(hueA, hueB, blob.hue);
            const glow = context.createRadialGradient(bx, by, 0, bx, by, size);
            glow.addColorStop(0, `hsla(${hue},78%,58%,${blob.alpha * (0.8 + energy * 0.5)})`);glow.addColorStop(1, `hsla(${hue},78%,50%,0)`);
            context.fillStyle = glow;context.beginPath();context.arc(bx, by, size, 0, Math.PI * 2);context.fill();
          }
          for (const mote of dust) {
            const angle = mote.angle + time * mote.speed;
            const alpha = 0.10 + 0.28 * (0.5 + 0.5 * Math.sin(time * 0.7 + mote.phase));
            context.fillStyle = `hsla(${hueB},70%,86%,${alpha})`;context.beginPath();
            context.arc(cx + Math.cos(angle) * mote.radius * radius, cy + Math.sin(angle) * mote.radius * radius * 0.92, mote.size, 0, Math.PI * 2);context.fill();
          }
        }
        drawFilaments(input, energy, radius, cx, cy, hueA, hueB, time);
        if (!host.reducedMotion && input?.speaker === "assistant") {
          for (let index = 0; index < 14; index += 1) {
            const angle = index * 2.399 + time * 0.35;
            const pearlRadius = radius * (0.99 + 0.035 * Math.sin(time * 2 + index));
            const size = 1.5 + 2.2 * (0.5 + 0.5 * Math.sin(time * 6 + index * 3));
            context.fillStyle = `hsla(${hueBetween(hueA, hueB, 0.5)},55%,92%,0.65)`;context.beginPath();
            context.arc(cx + Math.cos(angle) * pearlRadius, cy + Math.sin(angle) * pearlRadius, size, 0, Math.PI * 2);context.fill();
          }
        }
        context.globalCompositeOperation = "source-over";
      },
      event(event) { if (event?.type === "turn-end") cooldown = Math.max(cooldown, 0.3); },
      setQuality(next) { quality = next; },
      outerRadius() { return Math.max(0, finite(layout.radius)) * (Number.isFinite(maxRadiusObserved) ? maxRadiusObserved : 1.42); },
      metrics() {
        return {
          ...frameMetrics,
          minRadiusObserved: Number.isFinite(minRadiusObserved) ? minRadiusObserved : frameMetrics.minRadius,
          maxRadiusObserved,
          maxProminencesObserved,
          maxProminenceAgeObserved,
        };
      },
      dispose() { disposed = true;prominences.length = 0;smoothed.fill(0); },
    };
  },
});
