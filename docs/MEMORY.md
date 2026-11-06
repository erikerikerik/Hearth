# Memory

The companion remembers her across conversations and restarts. Everything is local (SQLite `memories` table).

- **Learning:** ~4 s of quiet after a model-answered turn (or when the connection closes), the local model is asked for up to two durable facts. Output is validated: category in people/habits/goals/moments, 10-240 chars, no numbers that look like account IDs, no emails. Junk is dropped silently.
- **Status:** new = `candidate`; repeated (similarity >= 0.55) = `reinforced`; `confirmed`/`corrected` are never downgraded; `retired` and `synthetic-fixture` rows are never used.
- **Use:** the most recent 60 notes are appended to the system prompt each reply (solid ones first, tentative marked).
- **Not stored:** her words. Only the note and provenance (source, session tag).
- **Not mined:** crisis turns, forget requests, canned replies.
- **Forgetting:** saying "forget that" deletes the last note touched, scrubs the WAL, logs the deletion. Melt deletes everything.
- **Locked shelf:** realtime events carry category and status but no text.
- **Limits:** extraction quality with real speech is unmeasured; a note is only as good as the 12B model's judgement; derived summaries do not exist yet, so nothing else needs purging.
