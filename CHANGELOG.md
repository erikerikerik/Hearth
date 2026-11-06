# Changelog

## 1.3.0-rc1+p005 — public readiness and GitHub

- Replaced the stale deployment list with a current evidence chart covering the one-Mac voice path, memory, deletion, safety, installer, accessibility, storage and licensing gates.
- Reframed the README for a public audience without presenting Hearth as therapy or as ready for sensitive personal use.
- Added a security-reporting policy that prohibits personal data in reports and defines loopback-only as the supported boundary.
- Recorded the public repository and kept patch numbering continuous. Runtime data, model weights, credentials and local environments remain outside version control.
- Verification: 147 Python tests, 27 JavaScript checks and 18/18 synthetic voice checks pass; the tracked-file publication scan found no secret patterns or private/generated paths.
- `personal_use_ready` remains false.

## 1.3.0-rc1+p004 — M3 local test-bed launcher

- Added the double-clickable `Launch-Hearth-Testbed.command` and reusable `scripts/launch_testbed.sh` core. The M3 laptop runs Brave, Gemma, Whisper, Kokoro, memory, SQLite and Hearth locally; no Mac mini is involved.
- The launcher binds only to loopback, forces model libraries offline, never stores the temporary password, refuses unknown port occupants, opens only Brave and stops every process it owns with one Control-C.
- Test-bed state and logs live under ignored `runtime/` directories. `--check` validates local prerequisites without starting services.
- Added `docs/LOCAL_LAPTOP.md` and a DMG migration path that reuses the core launcher under launchd later.
- Verified a real offline start, health check, Brave open and clean two-process shutdown on the build Mac. The completed tree passes 147 Python tests, 27 JavaScript checks and 18/18 synthetic voice checks in Brave. Real microphone and conversational quality on the target M3 remain unverified.

## 1.3.0-rc1+p003 — takeover integrity

- Recovered the exact applied state of P001 memory and P002 thinking-simplified, initialized local version control and added `PATCHES.md` plus `.hearth-build.json`. Future changes require a numbered patch, commit and tag.
- Fixed macOS look rollback links that could resolve through `/private/private/var/...` and become unusable.
- Made explicit `voice_engine=None` deterministic while preserving local voice auto-detection when the argument is omitted.
- Made Brave acceptance use `.venv-ai` or `.venv` explicitly and prevented real LLM/voice model startup during synthetic browser checks.
- Fixed an unevidenced UI claim: configured voice names remain hidden unless the local voice loop exists, and warming/failure states are now stated separately.
- Added the pinned test-only Playwright dependency and repaired the real-Brave voice check's memory-call signature, observable synthetic thinking interval and server cleanup.
- Corrected stale voice/memory documentation: durable extraction waits about four seconds and is separate from the four-exchange in-memory conversation context.
- `/healthz` and `dist/release.json` now expose build `1.3.0-rc1+p003` and patch level 3. `personal_use_ready` remains false.
- Verification: 142 Python tests, 27 JavaScript checks and all 18 real-Brave synthetic voice checks pass. Real speech models and real-room behavior remain unverified.

## 1.3.0-rc1 — merged line (installer + mini's post-rc1 patch)

Merges the 1.2.0 installer line with the mini's post-rc1 patch 1 (below). Still synthetic; `personal_use_ready` stays false.

- CSP script hashes are now computed per served `index.html` (bundled or installed look), cached by path and mtime, so a look update keeps a correct CSP with no `unsafe-inline`.
- **Hands-free voice loop** (`app/voice.py`, `dist/shell/voice*.js`, `docs/VOICE_LOOP.md`): mic -> Whisper -> companion (safety first) -> Kokoro -> speaker over one authenticated same-origin WebSocket. Listens on open; the curtain stops the microphone; a permanent indicator states the real mic state; half-duplex so it cannot hear itself. Nothing is stored. Deviation: WebSocket instead of WebRTC.
- `Permissions-Policy` now `microphone=(self)` (was `microphone=()`, which blocked the mic); `connect-src` names the validated host's `ws://`.
- `requirements.txt` gains `websockets` (uvicorn could not upgrade WebSockets without it; found by the browser check).
- Fixed in `stream_reply` (mini's code): a model chunk ending in a space glued the next sentence onto the previous one.
- Tests: 91 -> 119 Python, 19 -> 26 JavaScript, plus `tests/voice_browser_check.py` (real Chrome, fake microphone and engine; 14 checks).
- Voice connection fixes (found on the Mac mini): the server now accepts then closes with 4401/4403 so the page can tell "log in" from "broken" (before, a bare 403 looked like a network failure and it retried forever); the server sends `voice.ready` and the microphone opens only after it, so the mic is never hot without an authenticated connection; the page says "Voice waits for the password" and connects as soon as login succeeds (`hearth:authenticated`). Open design question: voice currently needs the shelf password before it connects, which conflicts with "listens when Hearth opens".
- "Hear it" in Her Voice now plays the real voice (it was a silent animation); falls back to the animation when voice is not connected.
- Voice is on by default; with `HEARTH_DEV_TOOLS=1` (acceptance suite) it is off unless the page is opened with `?voice=1`.
- **Long-term memory** (`app/remember.py`, `docs/MEMORY.md`): after a spoken turn the local model extracts at most two durable facts (people, habits, goals, moments); they are stored as `candidate`, become `reinforced` when she repeats them, and are fed into every later reply, so the companion remembers across sessions and restarts. Her words are not stored, only the short note plus provenance. Crisis turns are never mined. "Forget that" (spoken) deletes the last note, logs it in `deletion_log`, and leaves no residue. Locked shelf: the page learns a note exists but not its text. Notes are written when the connection closes. Seeds (`synthetic-fixture`) are never used. 22 new tests (`test_remember.py`), including a new-connection recall test. **Not verified:** extraction quality with the real Gemma model on real speech; note review/edit UI beyond the existing shelf.
- Thinking indicator was added, then P002 simplified it to one thin faint moving sweep; the redundant italic text and "her calm" line are removed.
- **Not verified:** real microphone, Whisper and Kokoro on the M3 Pro, Brave permission flow, VAD thresholds, latency. **Not in the installer yet:** MLX packages, Hugging Face snapshot download, `mlx_lm.server` supervision.

## 1.2.0-rc1 — installable app (macOS, Apple silicon)

Still a synthetic candidate: the installer packages what exists; it does not close any release gate.

- **Installer:** `installer/build.sh` builds a drag-to-Applications `Hearth-<version>.dmg` (own icon and window background; `MAKE_PKG=1` also builds a `.pkg`). `/Applications/Hearth.app` bundles a checksum-verified Python 3.12. A per-user LaunchAgent runs the
  server on 127.0.0.1 only; clicking the app starts it and opens Brave. Developer ID signing (hardened runtime + entitlements), notarization and stapling of both the app and the image.
- **Launcher:** refuses to run from a disk image/Downloads (the service would point at a vanishing path); restarts the service when a different build is dropped over the old one (VERSION stamp); offers "Add to Dock" once.
- **Data separated from app:** `HEARTH_DATA_DIR` (default `~/Library/Application Support/Hearth/data`) holds the database,
  password hash, look bundles and models. Reinstalling or upgrading the app never touches it.
- **First-run password:** stored as an Argon2id hash in `auth.json` (0600). `tools/set_password.py` reads from stdin.
  The `HEARTH_PASSWORD_HASH` env var still wins; the dev password is still dev-only.
- **Swappable look layer:** the server resolves its UI per request from `data/ui/current` (validated `ui.json`, contract major 1)
  and falls back to the bundled UI if absent or broken. `tools/ui_manager.py` installs, rolls back and resets bundles with
  zip-slip/symlink/size protection, atomic symlink switching and mandatory checksums for downloaded bundles. Look changes never
  open the database. `/healthz` reports the active look. Static serving moved from `StaticFiles` to an equivalent traversal-safe route.
- **Model downloader:** `tools/model_manager.py` — resumable, disk-checked, SHA-256-verified, https-only, consent-gated, RAM-tiered.
  Unpinned manifest entries are refused; the shipped manifest is placeholders until real models are chosen.
- Tests: 50 -> 70 Python checks (`test_installer.py` adds 20). Launcher flow smoke-tested end to end with stubbed macOS commands.

### Deviations (documented per CLAUDE.md)

- Network use at install/first-run time for model download, by a separate consent-gated process; the running companion remains offline.
- `HEARTH_COOKIE_SECURE=0` in the LaunchAgent: loopback http only, SameSite=Strict, HttpOnly. Not for any LAN exposure.
- No automatic pre-migration backup (would create unencrypted copies outside deletion proof). No schema migration ships in this release.

### Not verified here

`hdiutil`/Finder window layout, signing/notarization, real `osascript` dialogs and launchd behavior; `pkgbuild` (optional path); the Brave acceptance suite.

## 1.1.0-rc1 — deletion and access hardening

Found in the 1.0.0-rc1 code review; still a synthetic candidate (`personal_use_ready: false`).

- **Deletion residue:** deleting or editing a memory, note or lantern left the old text in the SQLite `-wal` file until an automatic checkpoint. These writes now run `wal_checkpoint(TRUNCATE)` immediately after commit. New tests scan the whole runtime directory, WAL included.
- **Shelf lock:** memory `keep` and `delete` now require an unlocked shelf, matching `PATCH`. The UI resyncs to the locked state on a 403 instead of silently doing nothing.
- **Login throttle:** failed-login backoff is now per client address, not one global bucket, so a stranger's failed guesses can no longer lock the owner out for five minutes. Reauthentication stays per session.
- **Lock scope:** Argon2 verification (login and reauthentication) runs outside the global runtime lock, and reauthentication bookkeeping is now lock-protected.
- **Host handling:** IPv6 loopback (`[::1]`) is accepted; rejected-Host responses now carry the security headers.
- Tests: 45 -> 50 Python checks; JavaScript suites unchanged (17).

### Known open items carried forward

- CSP still allows `script-src 'unsafe-inline'`; fixing it means moving the inline script out of `index.html` and needs the Brave acceptance run.
- Deleting a memory does not purge conversation-ledger rows that mention it. The ledger is dev-only; this becomes a real gate once real transcripts or embeddings exist.
- The browser acceptance suite was not re-run for this build (needs macOS + Playwright + Brave).

## Unreleased — post-rc1 patch 1 (Claude takeover)

Still synthetic-only; `personal_use_ready` remains false. Evidence: 19 JS tests and 47 Python tests pass in a cloud workspace (1 skipped: Brave acceptance needs the Mac); manual Chromium check shows no CSP violations in dev and production modes. Brave acceptance has not been re-run on the Mac mini.

- Bottom bar replaced by a black tab one third of the orb's diameter (minimum 124 px so the label fits on phones); `--orbw` is shared by orb and tab, status line moved down 6 px. Visual-only change.
- `POST /api/memories/{id}/keep` and `DELETE /api/memories/{id}` now return 403 `shelf_locked` while the shelf is locked (tests added).
- Deviation: `script-src` no longer contains `'unsafe-inline'`; the server computes SHA-256 hashes of the page's inline classic scripts at startup. `style-src` still allows `'unsafe-inline'` because the page uses style attributes.
- Deviation: production exposes only `window.hearthRealtime.send`. `receive`, `replay` and `mockServer` are exposed only when `/healthz` reports `dev_tools: true`. Browser acceptance therefore needs `HEARTH_DEV_TOOLS=1`.
- Added per-band automatic gain to the Web Audio adapter (peak tracker, minimum reference 0.3, maximum 3x gain, silence untouched). Constants are first guesses and need tuning on the real microphone.
- Voice: default voice is the Kokoro blend `af_heart,af_nicole` (id `willow`), with `bm_george` (id `moss`) as the alternate. `config/models.json` `voices` holds the map; `app/voices.py` resolves a saved id (unknown ids fall back to default). `/api/voices` now lists the two voices so the existing Voice panel shows two chips and hides the others; pitch and preview remain unsupported. `scripts/voice_smoke.py` uses the default voice. Deviation planned for step 2: mic transport will be WebSocket, not the WebRTC named in RELEASE_READINESS.md.
- Added `scripts/tls_setup.sh`, `tls_issue.sh`, `run_https.sh`, `check_lan.sh` and `docs/LAN_HTTPS.md` (gate 3, partial). Tested on Linux with OpenSSL against this app: name-constrained CA, 365-day server cert, Secure cookie over TLS, untrusted when CA is absent. Not yet run on the Mac mini or her laptop. Target browser: Brave on macOS.
- Added `config/models.json`, `app/llm.py` (loopback-only OpenAI-compatible client, tested), `scripts/install_models.sh`, `run_llm.sh`, `package_bundle.sh`, `bench/` and `docs/MODELS_AND_PORTING.md` (gate 1, partial). Model repositories and sizes were checked on Hugging Face; nothing has been loaded or measured on the Mac mini. The conversation endpoint still uses the synthetic safety stub; the model is not wired into it yet.
- Model wired into `/api/conversation/turn` (dev-tools only, `HEARTH_LLM_ENABLED=1`): safety check first (crisis text never reaches the model), then the local model, then per-sentence filtering, role-claim and diagnosis removal, 3-sentence cap, deterministic fallback if the model is down. 14 new tests. New: `app/companion.py`, `config/system_prompt.txt`, `scripts/chat_cli.py`, `docs/CODEX_BACKUP_ENCRYPTION.md`. Safety wording is still the unreviewed keyword baseline.
- Known and unchanged: `window.__hearth` is still a global used by the shell modules; the tone-preview sentence from the server is still fixed text; the voices panel is empty until a local TTS is installed.

## 1.0.0-rc1 — U3–U5 acceptance candidate

- Completed backend-owned workshop flows without browser persistence of private text.
- Added memory correction, exponential note-save retry, honest voice capability gating, measured-or-hidden privacy fields and side-effect-free tone preview.
- Removed backup promises from melt copy because encrypted backup creation and purge are not installed.
- Added typed confirmation alongside the 2.6-second melt hold, focus wrapping and late-cancel handling.
- Strengthened deletion verification to scan the entire runtime data directory for sentinels.
- Added the real Web Audio FFT adapter with eight specified bands, attack/release smoothing and source isolation; production falls to the noise floor when no mic/TTS source is attached.
- Added live reduced-motion and responsive-breakpoint subscriptions, minimum 12 px informational labels, strict hidden-state CSS and backend-outage fallback.
- Added randomized backend tone-invariant coverage and browser-storage/privacy checks.
- Verified all JavaScript suites with the app-bundled Node runtime and removed the local skip.
- Added the user-visible memory correction path and true lantern deletion endpoint.
- Added automated Brave acceptance at desktop and 360 px, fixed the curtain's whole-workshop hit target, preserved readable subtitle spacing, transferred focus across inert layers, exposed slider value text, verified modal focus wrapping and capped covered-orb rendering at 15 fps without slowing wall-clock animations.
- Exposed active renderer, quality tier and measured frame-time p95 through the orb controller so future renderer installs can be compared without changing the shell.

## 0.7.0 — U2 event seam and replaceable-orb handoff

- Made the active orb a runtime configuration: a compatible same-origin renderer can be installed or rolled back without rebuilding the shell or backend.
- Added `OrbInstallprocedure.MD` with the renderer boundary, contract, install, verification and rollback procedure for future implementers.
- Restored per-segment hue/light position, rim lighting, glow passes and assistant pearl glints in `filament-v1`.
- Replaced two-frame fixtures with seven deterministic 30–60 second replays.
- Replaced claimed orb metrics with measurements from drawn geometry and added well, hue, quality-tier and prominence coverage.
- Added a versioned realtime shell client, mock event server and front-of-house handlers for U2 events.
- Wired full curtain state to same-frame mic pause/resume events with acknowledgement, and queued visual-only memory sparks 400 ms apart.
- Removed `testserver` from the production Host allowlist.

## 0.6.0 — U0/U1 and review hardening

- Added the renderer contract, registry, guarded controller, fallback ring and deterministic `filament-v1`.
- Added seven synthetic replay fixtures, `/dev/orb` and a JavaScript contract suite.
- Replaced orb randomness with seeded RNG and stopped spark arrival from creating memory.
- Fixed reauthentication throttling, shelf redaction, HTML injection paths and melt state semantics.
- Prevented confirmed-memory demotion and added corrected/retired statuses.
- Pinned dependencies, moved to FastAPI lifespan, hardened file permissions and Host validation.
- Parked the safety stub and dev tray behind dev mode and removed the duplicate server.
- Replaced bundled webfonts with basic system font stacks; no font assets ship or load.

## 0.5.0 — Synthetic conversation safety ledger

- Added a deterministic, unreviewed synthetic safety decision path for UI and invariant testing.
- Added a durable conversation ledger with exact delivered-text recording.
- Added an output filter that blocks false claims of contacting emergency services, family, police, or monitoring.
- Connected the authenticated typed prototype to the synthetic conversation endpoint.
- Added high-risk, uncertain-risk, ordinary-vent, synthetic-only, ledger, and no-outside-contact tests.
- Extended scheduled melt to erase the conversation ledger, restore house settings, checkpoint the WAL, vacuum the database, and record completion.

## 0.4.0 — Durable synthetic workshop

- Added a SQLite canonical store with recorded schema migration 1.
- Made memories, lanterns, notes, tone, voice, pattern settings, and melt schedules durable.
- Added metadata-only deletion logging and due-melt execution for synthetic records.
- Wired notes, lanterns, voice, tone, and pattern controls to authenticated APIs.
- Added restart-persistence, migration, CRUD, validation, and deletion-proof tests.
- Verified note and settings persistence through a real server restart.

## 0.3.0 — Authenticated synthetic workshop

- Added a FastAPI application boundary and loopback-only Uvicorn entry point.
- Added Argon2id password verification, HttpOnly SameSite sessions, CSRF checks, and login backoff.
- Added server-owned synthetic workshop, settings, memory, and melt endpoints.
- Wired the approved Jar Shelf key and memory actions to the authenticated API.
- Removed the literal prototype password from the browser.
- Added nine authenticated API tests; thirteen total tests pass.

## 0.2.0 — Offline scaffold

- Bundled the approved prototype's fonts locally and removed the Google Fonts runtime request.
- Added a loopback-only Python preview server.
- Added explicit security headers and non-production health metadata.
- Added tests for offline assets, headers, health state, and unimplemented API behavior.
- Added implementation guardrails and early privacy notes.

## 0.1.1 — Source alignment

- Restored the supplied `hearth.html` as the visual and interaction source of truth.
- Added a UTF-8 document shell to fix mojibake in direct browser rendering.
- Removed the divergent reinterpretation and its unused assets.

## 0.1.0 — Initial draft

- Created an exploratory UI implementation. Superseded by 0.1.1.

