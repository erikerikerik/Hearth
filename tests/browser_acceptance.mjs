import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { existsSync } from "node:fs";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { chromium } = require("/Applications/ChatGPT.app/Contents/Resources/cua_node/lib/node_modules/playwright");
const root = new URL("..", import.meta.url).pathname;
const origin = "http://127.0.0.1:4174";
const password = "synthetic-browser-acceptance";
const brave = "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser";
const python = [process.env.HEARTH_TEST_PYTHON, `${root}.venv-ai/bin/python`, `${root}.venv/bin/python`].find((candidate) => candidate && existsSync(candidate));
if (!python) throw new Error("No Hearth test Python found; set HEARTH_TEST_PYTHON");

const server = spawn(python, ["run_dev.py"], {
  cwd: root,
  env: { ...process.env, HEARTH_DEV_PASSWORD: password, HEARTH_COOKIE_SECURE: "0", HEARTH_DEV_TOOLS: "1", HEARTH_PORT: "4174", HEARTH_VOICE_ENABLED: "0", HEARTH_LLM_ENABLED: "0" },
  stdio: "ignore",
});

async function ready() {
  for (let attempt = 0; attempt < 80; attempt += 1) {
    try { if ((await fetch(`${origin}/healthz`)).ok) return; } catch {}
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error("Hearth browser-test server did not start");
}

let browser;
try {
  await ready();
  process.stdout.write("server ready\n");
  browser = await chromium.launch({ headless: true, executablePath: brave });
  process.stdout.write("browser ready\n");
  const context = await browser.newContext({ viewport: { width: 1280, height: 800 }, reducedMotion: "no-preference" });
  const page = await context.newPage();
  page.setDefaultTimeout(15_000);
  const foreignRequests = [];
  const pageErrors = [];
  page.on("request", (request) => { if (new URL(request.url()).origin !== origin) foreignRequests.push(request.url()); });
  page.on("pageerror", (error) => pageErrors.push(error.message));
  await page.goto(origin, { waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => document.documentElement.dataset.orbRenderer === "filament-v1@1");
  process.stdout.write("desktop shell ready\n");
  assert.equal(await page.getAttribute("html", "data-audio-bands"), "v1");
  assert.equal(await page.getAttribute("html", "data-realtime-transport"), "mock-v1-dev");
  assert.equal(await page.locator("#orb").getAttribute("aria-hidden"), "true");
  assert.equal(await page.locator("#cap").getAttribute("aria-hidden"), "true");
  assert.equal(await page.locator(".status").getAttribute("role"), "status");
  assert.equal(await page.evaluate(() => /(?:â.|Ã.|ï¿½|�)/.test(document.body.innerText)), false);
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  await page.evaluate(() => {
    const original = window.hearthOrbRenderer.frame.bind(window.hearthOrbRenderer);
    window.__orbFrameCount = 0;
    window.hearthOrbRenderer.frame = (input) => { window.__orbFrameCount += 1;return original(input); };
  });
  await page.waitForFunction(() => window.__orbFrameCount >= 8, null, { timeout: 3_000 });
  const orbMetrics = await page.evaluate(() => window.hearthOrbRenderer.metrics());
  assert.equal(orbMetrics.activeRenderer, "filament-v1@1");
  assert.equal(orbMetrics.quality, "high");
  assert.ok(Number.isFinite(orbMetrics.frameP95Ms));
  assert.ok(orbMetrics.frameP95Ms < 24, `orb frame p95 ${orbMetrics.frameP95Ms.toFixed(2)} ms exceeds fallback threshold`);
  assert.deepEqual(foreignRequests, []);

  await page.getByRole("button", { name: /Backstage/ }).click();
  await page.waitForTimeout(900);
  assert.equal(await page.locator("#back").getAttribute("inert"), null);
  assert.equal(await page.locator("#front").getAttribute("inert"), null);
  assert.equal(await page.locator("#tabMore").isVisible(), true);
  await page.locator("#tabMore").click();
  await page.waitForTimeout(900);
  assert.notEqual(await page.locator("#fc").getAttribute("inert"), null);
  assert.equal(await page.locator("body").getAttribute("data-mic-paused-ack"), "true");
  assert.equal(await page.evaluate(() => document.querySelector("#back").contains(document.activeElement)), true);
  await page.evaluate(() => { window.__orbFrameCount = 0; });
  await page.waitForTimeout(500);
  assert.ok(await page.evaluate(() => window.__orbFrameCount > 0 && window.__orbFrameCount <= 9));
  await page.keyboard.press("Escape");
  await page.waitForTimeout(900);
  assert.notEqual(await page.locator("#back").getAttribute("inert"), null);
  assert.equal(await page.locator("body").getAttribute("data-mic-paused-ack"), "false");
  assert.equal(await page.evaluate(() => document.activeElement?.id), "tabMain");
  process.stdout.write("curtain checked\n");

  await page.getByRole("button", { name: /Backstage/ }).click();
  await page.waitForTimeout(850);
  await page.locator("#tabMore").click();
  await page.waitForTimeout(850);
  await page.locator("#unlock").click();
  await page.locator("#shelfPassword").fill(password);
  await page.locator("#shelfLogin").press("Enter");
  await page.waitForFunction(() => document.querySelector("#gate")?.hidden === true);
  assert.match(await page.locator("#memlist").innerText(), /Holds back|Dana|meeting/i);
  assert.equal(await page.locator("#egressRow").isVisible(), false);
  assert.equal(await page.locator("#backupRow").isVisible(), false);
  assert.equal(await page.locator(".vchips").isVisible(), false);
  const warmth = page.locator('.vial[data-k="warmth"]');
  await warmth.focus();
  const warmthBefore = Number(await warmth.getAttribute("aria-valuenow"));
  await page.keyboard.press("ArrowUp");
  assert.equal(Number(await warmth.getAttribute("aria-valuenow")), Math.min(100, warmthBefore + 5));
  assert.match(await warmth.getAttribute("aria-valuetext"), /Warmth, \d+ percent/);
  process.stdout.write("shelf checked\n");

  await page.evaluate(() => window.hearthRealtime.receive({ type: "assistant.delivered", v: 1, ts: 100, turn_id: "browser-check", text_so_far: "Only delivered words appear", final: false }));
  assert.equal((await page.locator("#cap").innerText()).trim(), "Only delivered words appear");
  const beadsBefore = await page.locator("#bjars .bead").count();
  await page.evaluate(() => window.hearthRealtime.receive({ type: "memory.candidate", v: 1, ts: 101, id: "browser-memory", category: "patterns", text: "Synthetic browser candidate", status: "candidate" }));
  assert.equal(await page.locator("#bjars .bead").count(), beadsBefore + 1);
  await page.waitForTimeout(3100);
  assert.equal(await page.locator("#tabMain").evaluate((element) => element.classList.contains("glint")), true);

  await page.locator("#melt").click();
  assert.equal(await page.getByRole("dialog").isVisible(), true);
  assert.equal((await page.locator("#mdT").innerText()).trim(), "Enter her password");
  assert.equal(await page.evaluate(() => document.activeElement?.id), "pwIn");
  await page.keyboard.press("Shift+Tab");
  assert.equal((await page.evaluate(() => document.activeElement?.textContent)).trim(), "Unlock");
  await page.keyboard.press("Tab");
  assert.equal(await page.evaluate(() => document.activeElement?.id), "pwIn");
  await page.keyboard.press("Escape");
  assert.equal(await page.getByRole("dialog").isVisible(), false);
  assert.deepEqual(pageErrors, []);
  await context.close();
  process.stdout.write("desktop checked\n");

  const phone = await browser.newContext({ viewport: { width: 360, height: 800 }, reducedMotion: "reduce" });
  const phonePage = await phone.newPage();
  phonePage.setDefaultTimeout(15_000);
  await phonePage.goto(origin, { waitUntil: "domcontentloaded" });
  await phonePage.waitForFunction(() => document.documentElement.dataset.orbRenderer === "filament-v1@1");
  await phonePage.getByRole("button", { name: /Backstage/ }).click();
  await phonePage.waitForTimeout(100);
  assert.notEqual(await phonePage.locator("#fc").getAttribute("inert"), null);
  assert.equal(await phonePage.locator("#tabMore").isVisible(), false);
  assert.equal(await phonePage.locator("body").getAttribute("data-mic-paused-ack"), "true");
  assert.ok(await phonePage.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  await phone.close();
  process.stdout.write("Browser acceptance passed: desktop, phone, reduced motion, privacy, subtitles, spark, curtain and melt dialog.\n");
} finally {
  await browser?.close();
  if (server.exitCode === null) {
    server.kill("SIGTERM");
    await Promise.race([once(server, "exit"), new Promise((resolve) => setTimeout(resolve, 2_000))]);
  }
}
