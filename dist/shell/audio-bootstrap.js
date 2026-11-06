import { AudioBandSource, quietBands } from "./audio-bands.js";

const sources = { user: null, assistant: null };

window.hearthAudioBands = Object.freeze({
  attach(kind, audioContext, source) {
    if (kind !== "user" && kind !== "assistant") throw new TypeError("invalid audio source kind");
    sources[kind]?.dispose();
    sources[kind] = new AudioBandSource(audioContext, source);
  },
  detach(kind) { sources[kind]?.dispose();sources[kind] = null; },
  read(speaker, time, dt, paused) {
    if (paused) return quietBands("idle", time, true);
    if (speaker === "user" || speaker === "assistant") return sources[speaker]?.read(dt) || quietBands("idle", time, true);
    return quietBands(speaker, time, false);
  },
});

document.documentElement.dataset.audioBands = "v1";
