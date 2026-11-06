import { register } from "./registry.js";
import { fallbackRingFactory } from "./fallback-ring.js";
import { createSeededRng } from "./seeded-rng.js";
import { OrbController } from "./controller.js";

register(fallbackRingFactory);

async function loadConfiguredRenderer() {
  try {
    const response = await fetch("/orb/active-renderer.json", { cache: "no-store" });
    if (!response.ok) throw new Error(`orb config ${response.status}`);
    const config = await response.json();
    const modulePath = String(config.module || "");
    const exportName = String(config.export || "");
    const requested = String(config.renderer || "fallback-ring@1");
    if (!modulePath.startsWith("/orb/") || !modulePath.endsWith(".js") || modulePath.includes("..")) throw new Error("invalid orb module path");
    if (!/^[A-Za-z_$][\w$]*$/.test(exportName)) throw new Error("invalid orb export name");
    const rendererModule = await import(modulePath);
    if (!register(rendererModule[exportName])) throw new Error("incompatible orb contract");
    return requested;
  } catch (error) {
    if (location.search.includes("dev=1")) console.warn("configured orb unavailable; fallback active", error);
    return "fallback-ring@1";
  }
}

const requestedRenderer = await loadConfiguredRenderer();
document.documentElement.dataset.orbRenderer = requestedRenderer;

const canvas = document.querySelector("#orb");
const wrap = document.querySelector("#orbWrap");
if (canvas && wrap) {
  const host = {
    canvas,
    rng: createSeededRng(0x48454152),
    reducedMotion: matchMedia("(prefers-reduced-motion: reduce)").matches,
    quality: "high",
    log(message, data) { if (location.search.includes("dev=1")) console.warn(message, data || ""); },
  };
  const controller = new OrbController(host, requestedRenderer);
  let dimensions = "";
  window.hearthOrbRenderer = {
    frame(input) {
      const width = wrap.clientWidth || 0;
      const height = width;
      const dpr = Math.min(devicePixelRatio || 1, 2);
      const key = `${width}:${height}:${dpr}`;
      if (key !== dimensions) {
        dimensions = key;canvas.width = Math.round(width * dpr);canvas.height = Math.round(height * dpr);
        controller.resize({ width, height, dpr, cx: width / 2, cy: height / 2, radius: width * 0.34, wellRadius: width * 0.18 });
      }
      controller.frame(input);
    },
    event(event) { controller.event(event); },
    metrics() { return controller.metrics(); },
    outerRadius() { return controller.outerRadius(); },
    forceFallback(reason) { controller.forceFallback(reason); },
  };
}
