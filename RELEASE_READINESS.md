# Hearth V1 readiness chart

- Build: **`1.3.0-rc1+p008`**
- Decision: **public source preview; not personal-use ready**
- Machine boundary: **one Apple-silicon Mac, loopback only**

This chart separates implemented behavior from evidence still needed. A passing test is not treated as clinical review, target-device validation or a privacy claim it cannot prove.

## Status key

| Mark | Meaning |
| --- | --- |
| ✅ | Implemented and supported by the evidence named here |
| 🟨 | Implemented, but target-device or human validation remains |
| ⬜ | Not complete; blocks `personal_use_ready: true` |
| ➖ | Intentionally out of scope |

## Current capability chart

| Area | Status | What exists now | Evidence / remaining work |
| --- | --- | --- | --- |
| Offline boundary | ✅ | Hearth, Gemma, Whisper, Kokoro, SQLite and Brave run on one Mac; application services bind to loopback | Launcher exercised offline; port ownership and shutdown tested. Model installation itself is a separate, consented network step. |
| Authentication | ✅ | Argon2id login/step-up, HttpOnly SameSite cookies, CSRF, per-client throttling and Host validation | Python security tests pass. Production password hash is still an operator setup step. |
| Voice loop | 🟨 | Authenticated WebSocket: microphone → Whisper → companion → Kokoro → speaker; half-duplex and curtain pause | Synthetic Brave checks pass and the build Mac granted a real microphone after reload. Measure a complete real conversation on the target M3 laptop, including earbuds, reconnects, VAD, latency and echo behavior. |
| Local language model | 🟨 | Loopback-only Gemma service with deterministic fallback and output filtering | Real service starts and health-checks. Record response quality, failure recovery and latency on the target M3. P008 pins every model to an exact commit with per-file hashes (`models/manifest.json`); re-pin with `scripts/pin_models.py --revision-from-cache` if the build Mac tested a different commit. |
| Long-term memory | 🟨 | Up to two short derived notes per turn; candidate/reinforced states; recall across restarts; crisis turns excluded | Synthetic tests pass. Validate extraction and recall on real speech. Replace “forget that” deleting the most recent note with a target-and-confirm flow. |
| Shelf privacy | ✅ | Locked responses omit memory text; curtain locks the shelf | Automated redaction and lock tests pass. Login and shelf authorization should still be separated before personal use. |
| Deletion / melt | 🟨 | Scheduled background melt, one-time confirmation, WAL truncation, vacuum and runtime sentinel scan | Synthetic deletion proof passes. Purge every derived reference and run the proof against actual target-machine data, temp and future backup locations. |
| Safety behavior | ⬜ | Deterministic pre-model risk check, no-contact policy, per-sentence output filter and safe fallback | Current keyword baseline is explicitly unreviewed. Requires clinically reviewed policy, uncertain-risk behavior, adversarial evals and documented sign-off. Hearth never contacts anyone. |
| Backups / encryption | ⬜ | No backup claim is shown; FileVault may protect the host disk | Add encrypted backups with deletion propagation, or explicitly ship with no backup feature. App-level at-rest encryption is not implemented. |
| Orb / workshop UI | 🟨 | Replaceable orb contract, fallback renderer, long fixtures, measured geometry and U0–U5 flows | Automated Brave checks pass. Owner sign-off and target-device VoiceOver, 200% zoom, keyboard and performance checks remain. |
| Installer / DMG | ⬜ | P008: pinned Python + hash-locked MLX/speech runtime in the app, consented first-launch download of pinned, per-file-verified model snapshots, launchd-supervised `mlx_lm.server`, in-bundle self-checks before and after signing, and an installed smoke test | Written and unit-tested on Linux only. Build, sign and notarize on the Mac mini, then install, run `tools/smoke_installed.py`, upgrade and uninstall on a clean Apple-silicon Mac (ideally the target M3) and record the results. |
| Networked/LAN mode | ➖ | Loopback-only is the supported V1 direction | LAN scripts are retained as experiments, but V1 does not need a Mac-mini-to-laptop server path. Do not expose Hearth to a LAN or the internet. |
| Telemetry / cloud fallback | ✅ | None in the application runtime | Offline tests and source inspection. Keep model downloads isolated from runtime and consent-gated. |
| Public repository hygiene | ✅ | Runtime data, environments, models and credentials are ignored; public docs state safety limits | Pre-publish tracked-file and secret-pattern scan required for every release. No real user data belongs in tests or issues. |
| Reuse license | ✅ | MIT License with credit retained through the required copyright and license notice | The license covers Hearth's code, not third-party model weights or their separate licenses. |

## Evidence snapshot for P008

| Check | Result |
| --- | --- |
| Python suite | 168 tests on Linux: 167 passed, 1 skipped; the one failure is the macOS-only launcher `--check`, which cannot run on Linux. Not yet run on a Mac for P008 |
| JavaScript suites | 27 checks passed on P008 |
| Brave synthetic voice acceptance | Not run for P008 (needs a Mac with Brave); 18/18 on P007 and P008 does not touch the page or the voice protocol |
| Model download | Real Kokoro snapshot (0.36 GB, 56 files) downloaded from Hugging Face through redirects and verified file by file; `verify` re-hash passed |
| Real launcher orchestration | Gemma and Hearth started on loopback, health passed, Brave opened, and owned processes stopped cleanly |
| Real microphone permission | Build Mac prompted after reload and accepted the selected input device; conversational quality is not yet a recorded test |

## Order of work to V1

1. **Deletion and memory control:** targeted forget/edit, derived-data inventory and machine-wide deletion proof.
2. **Safety evidence:** replace the keyword baseline, build adversarial/uncertain-risk evals and obtain independent clinical review.
3. **Target M3 validation:** voice, earbuds, permissions, VAD, echo, latency, accessibility and sustained-session tests.
4. **Installer closure:** P008 implements pinned revisions/checksums, the bundled environment and supervised services; still needed: Mac build, signing, notarization and a clean-machine DMG test with the smoke report.
5. **Storage decision:** encrypted backups with purge propagation, or a documented no-backup V1.
6. **Release decision:** owner visual sign-off, attach all evidence and only then consider changing `personal_use_ready`.

## Release rule

`personal_use_ready` stays false until every blocking row is closed with evidence. A version number, a successful demo or publication on GitHub does not change that decision.
