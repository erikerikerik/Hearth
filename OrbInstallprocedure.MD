# Orb installation procedure

This guide is for replacing or upgrading Hearth's orb without rebuilding the application shell or backend. The orb is a same-origin JavaScript plug-in selected at runtime by `dist/orb/active-renderer.json`.

## Non-negotiable boundaries

An orb renderer owns only pixels inside its canvas. It must not own or change captions, the center spark, curtain state, workshop state, storage, authentication, network requests, microphone access, timers, or therapeutic behavior. The shell remains authoritative for all of those.

Do not edit `dist/index.html`, the Python server, the database, or the shell to install a compatible renderer. A normal orb replacement consists of one new module, its fixture/test coverage, and one small configuration change.

The current UI contract is `1.0`. A renderer declares compatibility as `contract: "1.x"`. A breaking API change requires a new contract major and coordinated shell work; do not disguise a breaking change as an orb-only update.

## Files involved

- `dist/orb/active-renderer.json` — runtime selector. This is the only production file that must be changed to switch compatible renderers.
- `dist/orb/registry.js` — validates contract compatibility and resolves versioned names.
- `dist/orb/controller.js` — guards renderer calls, lowers quality under sustained load, and activates the fallback after repeated failures.
- `dist/orb/fallback-ring.js` — permanent safe renderer. Do not remove it.
- `dist/orb/seeded-rng.js` — deterministic random source.
- `dev_ui/synthetic-replays.json` — 30–60 second synthetic scenarios.
- `dev_ui/orb.html` — side-by-side local comparison lab.
- `tests/orb_contract.test.mjs` — renderer contract and geometry checks.

## Renderer module contract

Create a new file under `dist/orb/`, for example `filament-v2.js`. Export one frozen factory:

```js
export const filamentV2Factory = Object.freeze({
  name: "filament-v2",
  version: "2.0.0",
  contract: "1.x",
  capabilities: {
    drawsOwnSpark: false,
    usesWebGL: false,
    hasReducedVariant: true,
  },
  create(host) {
    return {
      resize(layout) {},
      frame(input) {},
      event(event) {},
      setQuality(tier) {},
      outerRadius() { return 0; },
      metrics() { return {}; },
      dispose() {},
    };
  },
});
```

`host` provides:

- `canvas`: the renderer's canvas.
- `rng()`: seeded deterministic random values. Use this instead of `Math.random()`.
- `reducedMotion`: whether the reduced-motion variant is required.
- `quality`: `high`, `balanced`, or `low`.
- `log(message, data)`: local development logging.

`resize(layout)` receives `width`, `height`, `dpr`, `cx`, `cy`, `radius`, and `wellRadius`.

`frame(input)` receives time `t`, bounded `dt`, eight normalized audio `bands`, normalized `energy`, `speaker`, `calm`, and `mood` with `activation`, `hueA`, and `hueB`. Treat every value as untrusted: coerce finite numbers and clamp ranges.

`event(event)` is optional and receives shell events such as turn boundaries. `setQuality(tier)` must change cost without changing the public contract. `dispose()` must release references and make later frames harmless.

## Visual and performance requirements

- Keep the center well clear of opaque geometry. Translucent haze may enter it, with reported `wellMaxAlpha <= 0.5`.
- Keep drawn hues between the supplied mood hue endpoints.
- Report real geometry from the points actually drawn; do not return design constants as measurements.
- Report at least `minRadius`, `maxRadius`, `bodyDeviationP95`, `prominences`, `wellMaxAlpha`, `minOpaqueRadius`, `hueMin`, `hueMax`, `samplesPerStrand`, and `strandCount`.
- Keep no more than three prominences active, and expire each within eight seconds.
- Keep at least 200 samples per strand in every quality tier.
- Reduced motion must create no prominences and keep body deviation at or below two percent.
- Preserve deterministic output for the same seed and replay.
- Draw the shell's spark nowhere; `drawsOwnSpark` must stay false.

## Install a candidate

1. Add the candidate module under `dist/orb/`. Do not overwrite the current renderer during development.
2. Add its factory to the dev lab imports and call `register(candidateFactory)` there so it appears in the comparison selectors.
3. Add or extend synthetic fixtures if the renderer introduces a behavior not covered by the seven existing scenarios. Fixtures must remain synthetic and 30–60 seconds long.
4. Add the candidate to `tests/orb_contract.test.mjs` and run the same geometry, determinism, reduced-motion, fuzz, fallback, and disposal checks used by `filament-v1`.
5. Compare the candidate with the approved renderer at `/dev/orb` using quiet, agitated, assistant-reply, interruption, and long-silence fixtures.
6. Verify the normal Hearth page. The orb must not move captions, change the spark, create memories, or affect curtain/workshop state.
7. Switch only `dist/orb/active-renderer.json` after the candidate passes.

Example selector:

```json
{
  "module": "/orb/filament-v2.js",
  "export": "filamentV2Factory",
  "renderer": "filament-v2@2"
}
```

The module path must be same-origin, begin with `/orb/`, end in `.js`, and contain no `..`. The export must be a valid JavaScript identifier. The registry rejects a factory whose contract major does not match the shell.

## Verification commands

```sh
node --test tests/orb_contract.test.mjs
.venv/bin/python -m unittest -v test_app.py test_server.py
```

Run locally with development tools enabled, then open the comparison lab:

```sh
export HEARTH_DEV_PASSWORD='synthetic-development-only'
export HEARTH_COOKIE_SECURE=0
export HEARTH_DEV_TOOLS=1
.venv/bin/python run_dev.py
```

Open `http://127.0.0.1:4173/dev/orb`.

## Rollback

Set `active-renderer.json` back to the last known-good module. If the selected module is missing, invalid, incompatible, or throws three consecutive times, Hearth activates `fallback-ring@1`. Keep the prior renderer file in `dist/orb/` until the replacement has passed browser review.

## Handoff checklist for another AI

- Read this file, `ARCHITECTURE.md`, and the current renderer before editing.
- Preserve system fonts and the approved shell HTML/CSS.
- Work only inside the orb plug-in boundary unless explicitly asked for a contract-major change.
- Never use personal conversation data in fixtures or screenshots.
- Do not weaken the fallback, deterministic RNG, reduced-motion behavior, metrics, or contract tests to make a candidate pass.
- State the renderer name/version, contract version, selector change, tests run, browser fixtures inspected, and rollback target in the handoff.
