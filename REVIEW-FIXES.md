# Review response

## Must-fix items

1. Reauthentication now has a five-attempt/five-minute backoff.
2. Locked workshop responses omit memory text; ledger access returns 403; curtain close locks the shelf.
3. Memory text is escaped and subtitles use `textContent`.
4. A background executor runs melt. Scheduling is single-shot, late cancellation is 409, authorization is fresh and one-time, dev skip calls the real backend, and completion renders from server state.
5. Confirmed memory stays confirmed. The schema includes corrected and retired.
6. Dependencies are exact pins and FastAPI uses lifespan.

## Should-fix items

- SQLite is `0600` in a `0700` runtime directory.
- Dev tools require both `?dev=1` and `HEARTH_DEV_TOOLS=1`; dev endpoints are 404 otherwise.
- Runtime typography uses system stacks only; no font assets ship or load.
- The safety stub is parked behind dev mode.
- The duplicate server is removed; Host validation is present.
- Lantern observation notes are not browser-writable.
- Tone values are corrected server-side instead of rejected.

## U0/U1 gap

Implemented: renderer contract, registry, fallback ring, deterministic filament renderer, guarded controller, seven replay fixtures, `/dev/orb`, contract tests and shell integration. The remaining sign-off item is Erik's visual comparison of calm, agitated and assistant-reply fixtures.
