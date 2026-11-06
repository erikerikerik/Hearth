# Hearth implementation guardrails

- Local-only AI. No cloud fallback, telemetry, analytics, or remote error reporting. The only permitted network use is `tools/model_manager.py`: a separate, consent-gated, hash-verified model download that never runs inside the companion process.
- One authenticated user. Do not widen the product into a multi-user service.
- Keep LLM, STT, TTS, embedding, vector, prosody, orb, and frontend boundaries replaceable.
- Preserve memory provenance and verifiable deletion, including derived records, ledger entries, exports, and backup handling.
- Crisis prompting never contacts, messages, calls, locates, or notifies any outside party automatically.
- Keywords may raise recall but never make the final crisis decision alone.
- Companion-first behavior; deeper conversation is invited, never imposed.
- Tests and examples use synthetic data only.
- Add tests with architectural changes. Document migrations and measure voice-path latency.
- Document every deviation from the approved proposal and UI handoff.
- Do not claim a privacy, safety, deletion, or clinical behavior works without evidence.

