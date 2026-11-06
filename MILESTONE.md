# Hearth V1 release-candidate milestone

## Delivered

- Source-aligned front of house and workshop with UTF-8 rendering and local assets.
- UI contract 1.0 renderer seam, registry and one-setting selection.
- Deterministic `filament-v1` using a seeded host RNG.
- Always-registered `fallback-ring` plus guarded failure and slow-frame handling.
- Seven synthetic replay fixtures and the dev-only `/dev/orb` comparison lab.
- Renderer contract tests for registry behavior, determinism, geometry bounds, reduced motion, fuzz safety, fallback and disposal.
- Authenticated synthetic API with pinned dependencies, lifespan management, CSRF, Host validation and throttled login/reauthentication.
- Server-owned shelf lock, redacted locked responses and curtain-close lock.
- Background scheduled melt with single-shot scheduling, late-cancel protection, one-time passcode authorization, completion state and deletion proof.
- SQLite canonical state with private permissions, migrations, WAL checkpoint, secure delete and vacuum.
- System font stacks only; no bundled or fetched font files.
- Runtime orb selector and `OrbInstallprocedure.MD`, so a compatible renderer can be installed or rolled back without rebuilding the shell or backend.
- Real per-segment filament lighting, rim brightness and assistant pearl glints.
- Seven 30–60 second fixtures plus real drawn-geometry, well-clearance, hue-range, quality-tier and prominence-lifetime assertions.
- Versioned realtime shell protocol and mock event server for turn state, delivered subtitles, candidates, calm, settings, melt and degradation events.
- Full-curtain mic pause/resume messages with mock-server acknowledgement; candidate sparks remain visual-only and are queued 400 ms apart.
- U3 backend-owned station flows: memory correction, notes with retry state, lanterns, settings, capability-gated voices, measured-or-hidden privacy facts and side-effect-free tone previews.
- U4 scheduled melt flow with step-up authorization, hold and typed alternatives, restart-safe deadline, late-cancel handling, full data-directory sentinel scan, WAL checkpoint and vacuum.
- U5 hardening: live reduced-motion and breakpoint subscriptions, dialog focus wrapping, focus handoff across inert curtain layers, minimum informational text sizing, strict hidden-state rendering, 15 fps covered-orb cap, browser-storage prohibition, offline fallback and real Web Audio band adapter.

## Verified

- All 45 unittest checks pass, including all 17 JavaScript contract tests and the Brave/Playwright browser acceptance run; nothing is skipped on the build machine.
- Python suite passes: API, mutation, persistence, restart, permissions, redaction, throttling, melt, deletion sentinel, offline assets and dev/production separation.
- The orb modules load in the browser and the `/dev/orb` lab renders `filament-v1` beside `fallback-ring` with live fixture metrics.
- Runtime selection loads `filament-v1@1` from `active-renderer.json`; invalid or incompatible modules retain the safe fallback path.
- Browser checks at desktop and 360 px confirm curtain detents, focus handoff, mic pause/resume acknowledgements, reduced motion, no horizontal overflow, locked-shelf authentication, hidden unmeasured privacy/voice claims, delivered subtitles, memory sparks, slider keyboard operation, dialog focus wrapping and melt entry.
- The workshop remains aligned to the supplied HTML rather than a visual reinterpretation.

## Still intentionally absent

- Real personal data.
- Local inference, STT, TTS, microphone/WebRTC and audio-derived bands.
- LAN HTTPS and target-device service setup.
- Encrypted backup creation and backup deletion.
- A clinically reviewed crisis policy.
- Final accessibility, performance and visual sign-off on the target devices.

These are release gates, not hidden implementation claims. See `RELEASE_READINESS.md`.

The safety classifier and typed synthetic path are development stubs only and return 404 when dev tools are disabled.
