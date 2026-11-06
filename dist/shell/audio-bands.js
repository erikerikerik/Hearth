export const FREQUENCY_BANDS = Object.freeze([
  [80, 160], [160, 300], [300, 500], [500, 800],
  [800, 1300], [1300, 2200], [2200, 3600], [3600, 6000],
]);

function clamp(value, low, high) { return Math.min(high, Math.max(low, Number.isFinite(value) ? value : low)); }

export function dbToUnit(db) {
  return clamp((db + 60) / 40, 0, 1);
}

// Per-band automatic gain: tracks each band's recent peak and scales quiet
// bands up (at most MAX_GAIN) so a low-level microphone still moves the orb.
// Loud bands are never attenuated below their raw value. Pure and testable.
export const AUTO_GAIN = Object.freeze({ floor: 0.3, maxGain: 3, peakDecayPerSecond: 0.08, silence: 0.025 });

export function applyAutoGain(targets, peaks, dt) {
  const seconds = clamp(dt, 0, 0.1);
  const out = new Float32Array(targets.length);
  for (let index = 0; index < targets.length; index += 1) {
    const raw = targets[index];
    peaks[index] = Math.max(raw, peaks[index] - AUTO_GAIN.peakDecayPerSecond * seconds);
    const gain = raw < AUTO_GAIN.silence ? 1 : clamp(1 / Math.max(peaks[index], AUTO_GAIN.floor), 1, AUTO_GAIN.maxGain);
    out[index] = clamp(raw * gain, 0, 1);
  }
  return out;
}

export function aggregateFrequencyBands(dbBins, sampleRate, fftSize = 1024) {
  const nyquist = sampleRate / 2;
  const output = new Float32Array(8);
  for (let band = 0; band < FREQUENCY_BANDS.length; band += 1) {
    const [low, high] = FREQUENCY_BANDS[band];
    const first = Math.max(1, Math.floor(low / nyquist * dbBins.length));
    const last = Math.min(dbBins.length - 1, Math.ceil(high / nyquist * dbBins.length));
    let linear = 0;
    let count = 0;
    for (let index = first; index <= last; index += 1) {
      const db = Number.isFinite(dbBins[index]) ? dbBins[index] : -100;
      linear += Math.pow(10, db / 20);
      count += 1;
    }
    const meanDb = count ? 20 * Math.log10(Math.max(1e-6, linear / count)) : -100;
    output[band] = dbToUnit(meanDb);
  }
  return output;
}

export class AudioBandSource {
  constructor(audioContext, source) {
    this.context = audioContext;
    this.analyser = audioContext.createAnalyser();
    this.analyser.fftSize = 1024;
    this.analyser.smoothingTimeConstant = 0;
    this.dbBins = new Float32Array(this.analyser.frequencyBinCount);
    this.values = new Float32Array(8);
    this.peaks = new Float32Array(8);
    this.source = source instanceof MediaStream ? audioContext.createMediaStreamSource(source) : source;
    this.source.connect(this.analyser);
  }

  read(dt) {
    this.analyser.getFloatFrequencyData(this.dbBins);
    const targets = applyAutoGain(
      aggregateFrequencyBands(this.dbBins, this.context.sampleRate, this.analyser.fftSize), this.peaks, dt);
    const seconds = clamp(dt, 0, 0.1);
    for (let index = 0; index < 8; index += 1) {
      const target = targets[index] < 0.025 ? 0.02 : targets[index];
      const rate = target > this.values[index] ? 20 : 5;
      this.values[index] += (target - this.values[index]) * (1 - Math.exp(-seconds * rate));
    }
    return this.values;
  }

  dispose() {
    try { this.source.disconnect(this.analyser); } catch {}
    try { this.analyser.disconnect(); } catch {}
    this.values.fill(0);
    this.peaks.fill(0);
  }
}

export function quietBands(state, time, paused = false) {
  const values = new Float32Array(8);
  if (paused) { values.fill(0.02);return values; }
  for (let index = 0; index < 8; index += 1) {
    if (state === "think") values[index] = index < 3 ? 0.16 + 0.03 * Math.sin(time * 1.1 + index) : 0.03;
    else values[index] = 0.04 + 0.02 * Math.sin(time * 0.9 + index * 0.8);
  }
  return values;
}
