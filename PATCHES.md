# Hearth patch ledger

Current build: **`1.3.0-rc1+p006`**. Product release remains `1.3.0-rc1`; `+pNNN` records changes applied to that release candidate. `personal_use_ready` remains false.

The live folder became a local Git repository on 2026-11-06. The recovered P002 state is commit `9e7fbb9b49d6`. Runtime databases, model environments and other private/generated data are ignored. The public remote is `https://github.com/erikerikerik/Hearth`.

| Patch | State | Evidence | Purpose |
| --- | --- | --- | --- |
| P001 `memory` | Applied | `HEARTH-PATCH-memory.zip` SHA-256 `df25cb2bb39c926d1cff4e732f6a92a35517f68f7a6d6dd7bd3b3ef775b2bfd8`; every supplied file matched the live tree except `dist/index.html`, which P002 intentionally superseded | Long-term memory extraction, recall and spoken forget path |
| P002 `thinking-simplified` | Applied | `HEARTH-PATCH-thinking-simplified.zip` SHA-256 `bfea98e05450f7381f1c3e38881fc8a3a90f8d15812a55464a572b921fb547e2`; supplied `dist/index.html` exactly matched the live tree | Replace the enlarged indicator with one thin faint sweep and remove redundant text |
| P003 `takeover-integrity` | Applied | Git tag `v1.3.0-rc1-p003`; full test result recorded below | Establish patch tracking and repair three Mac-local test failures found during takeover |
| P004 `m3-local-testbed-launcher` | Applied | Git tag `v1.3.0-rc1-p004`; real start/health/Brave/Control-C shutdown exercised locally | Run Gemma, Whisper, Kokoro, memory, UI and Brave entirely on one Apple-silicon laptop |
| P005 `public-readiness-and-github` | Applied | Git tag `v1.3.0-rc1-p005`; full test and tracked-file scan recorded below | Publish an honest readiness chart, public-project safety boundary and numbered source state |
| P006 `mit-license` | Applied | Git tag `v1.3.0-rc1-p006`; license text and public README agree | Permit use, modification and redistribution while retaining the owner's copyright and license notice |

## P003 repairs

- Makes look-layer rollback symlinks canonical on macOS, avoiding a broken `/private/private/var/...` target.
- Distinguishes an omitted voice engine (production auto-detection) from explicit `None` (deterministic disabled-voice tests).
- Makes browser acceptance select `.venv-ai` or `.venv` explicitly and disables real model startup during synthetic browser checks.
- Keeps configured voice choices hidden unless the local voice loop actually exists, with separate warming and failure states.
- Pins the Python browser-check dependency separately from production requirements and makes the 18-check Brave run deterministic.
- Reconciles stale memory and voice documentation with the implemented four-second extraction delay and durable-note path.
- Exposes `build_id` and `patch_level` in `/healthz` and the release manifest.

## Required process from P007 onward

1. Start from a clean Git worktree and assign the next `P###` before editing.
2. Update `.hearth-build.json`, this ledger and `CHANGELOG.md` in the same commit.
3. Run the full Python, JavaScript and Brave acceptance suites with synthetic data.
4. Commit as `patch P###: <description>` and tag `v<product-version>-p###`.
5. Never copy an unnumbered patch over the live tree. Never commit `runtime/`, `devdata/`, `.venv*`, model weights, credentials or personal data.

## Verification

Before P003, a clean local discovery run found 142 tests with three failures: macOS look rollback, explicit no-engine voice behavior and browser acceptance's hard-coded `.venv` path. These were real reproducible failures, not waived checks.

After P003 on the Mac mini:

- **142 Python tests passed** in 45.271 seconds, with no skips, model downloads or resource warnings.
- **27 JavaScript checks passed** across the three suites.
- **18/18 real-Brave voice checks passed** with a synthetic microphone, fake speech engine and fake local model.

These checks do not verify the real microphone, Whisper, Kokoro, Gemma response quality or real-room latency.

## P004 launcher verification

The launcher prerequisite check passed. A real offline launch started the balanced Gemma endpoint on loopback, started Hearth with isolated persistent test-bed data, returned `/healthz`, opened Brave, and then stopped both owned processes on one Control-C. Ports 4173 and 8081 were confirmed closed afterward. The completed P004 tree passes 147 Python tests, 27 JavaScript checks and 18/18 synthetic voice checks in Brave. This proves process orchestration, not the quality of the real speech loop.

## P005 publication verification

The completed P005 tree passes 147 Python tests, 27 JavaScript checks and 18/18 synthetic voice checks in Brave. A tracked-file scan found no private-key, common token, credential, database, runtime, virtual-environment or model-weight paths. The largest tracked fixture is synthetic. Publication does not change `personal_use_ready`.

## P006 license verification

The completed P006 tree passes 147 Python tests, 27 JavaScript checks and 18/18 synthetic voice checks in Brave. The MIT text, README credit and readiness chart agree on the permission and attribution boundary.
