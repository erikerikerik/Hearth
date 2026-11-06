# Hearth architecture status

The supplied prototype remains the visual reference. The orb is a replaceable runtime-selected renderer behind UI contract 1.0; the shell owns captions, state, curtain and spark. FastAPI owns authentication and synthetic state; SQLite is canonical.

```text
browser shell
  ├─ realtime protocol + mock event transport
  ├─ captions, curtain/mic state, spark, workshop stations
  └─ orb controller
      ├─ active-renderer.json (runtime selector)
      ├─ registry (contract 1.0)
      ├─ filament-v1 (default)
      └─ fallback-ring (always registered)
             │ same-origin session + CSRF
             ▼
FastAPI lifespan
  ├─ Argon2id login and purpose-specific reauthentication throttles
  ├─ background melt executor
  ├─ validation and host boundary
  └─ SQLite canonical store (0600)
```

## Orb contract

Each factory declares name, semantic version, contract range and capabilities, then creates a renderer with `resize`, `frame`, optional event/quality/metrics hooks, and `dispose`. Renderers receive a canvas, seeded RNG, reduced-motion flag, quality tier and local logger. They do not own captions, storage, network or timers.

`active-renderer.json` names a same-origin module and export. The bootstrap dynamically imports it, registers it only when contract-compatible, and otherwise starts the fallback ring. A compatible orb update therefore changes an isolated module and the selector, not the shell or Python application. `OrbInstallprocedure.MD` is the maintainer handoff.

The controller replaces a renderer after three consecutive errors. Sustained slow frames reduce quality from high to balanced to low, then fall back to the built-in ring. Seven 30–60 second synthetic fixtures drive the dev lab and contract suite. Metrics come from rendered points and segments, including well clearance and hue bounds.

## U2 event seam

The shell accepts versioned realtime messages through a transport-independent client. The current mock event server acknowledges `ui.mic` pause/resume messages and can replay synthetic events; a later WebRTC data channel or WebSocket implements the same `connect`/`send` boundary. Subtitle text is applied with text nodes, candidate events add their visual bead before starting a purely visual spark, and a fully open curtain pauses the mic path within the same `apply()` frame.

## Data migrations

- Migration 1 creates workshop state, settings, melt state and metadata-only deletion proof.
- Migration 2 adds the development-only conversation ledger.
- Migration 3 records melt completion.
- Migration 4 adds corrected and retired memory statuses.

SQLite enables foreign keys, WAL, `synchronous=FULL` and `secure_delete`. Melt checkpoints the WAL and vacuums. Backups are not implemented, so the UI does not claim to erase them.

LAN access, HTTPS, microphone permission, WebRTC, local models, real transcripts, encrypted backups and a clinically reviewed policy remain absent. The keyword safety stub and typed path are available only with `HEARTH_DEV_TOOLS=1`.

## Installed layout (1.2.0)

```text
/Applications/Hearth.app            app layer: server, tools, bundled default look, bundled Python
~/Library/Application Support/Hearth/data
   hearth.sqlite3, auth.json        data layer: never touched by installs or look updates
   ui/versions/*, ui/current        look layer: optional, contract-checked, rollback-able
   models/*                         model layer: downloaded on consent, hash-verified
~/Library/LaunchAgents/com.hearth.local.plist   service, 127.0.0.1 only
```
