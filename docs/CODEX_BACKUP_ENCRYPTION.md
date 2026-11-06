# Task for Codex: encrypted backups with provable purge (release gate 4, and part of gate 8)

Read `CLAUDE.md` first. Everything there applies. Claim nothing works without a test or measurement that shows it.

## Why
RELEASE_READINESS gate 4: "Implement encrypted backups and backup purge, or continue omitting backup claims from the UI." Today no backup exists and the Privacy Plate hides the backup row (`id="backupRow" hidden`). Melt (scheduled 2-day delete) must also remove every backup, otherwise "melt everything down" is untrue.

## Requirements
1. **Contents:** a consistent snapshot of the SQLite database only (use the `sqlite3` backup API or `VACUUM INTO`, never a raw file copy while WAL is active). No logs, no TLS keys, no models.
2. **Encryption:** authenticated encryption (for example AES-256-GCM or XChaCha20-Poly1305 via the `cryptography` package, or `age`). A random per-backup data key is wrapped by a key derived from a **separate backup passphrase** with Argon2id (already a dependency). The passphrase is never stored on the Mini. Tampering or a wrong passphrase must fail loudly with no partial output.
3. **Where:** a configurable directory (`HEARTH_BACKUP_DIR`), mode 0700, files 0600. Keep it **inside the directory that the melt verification scans**, or extend that scan to include it. A backup the deletion proof cannot see is a bug.
4. **When:** after any change to memories/notes/lanterns, debounced (for example 10 minutes), plus a daily one. Keep the last N (default 7). Never write a backup during a scheduled melt's execution window.
5. **Purge:** melt execution deletes every backup file and the wrapped keys, in the same transaction ordering as the DB wipe, then writes a `deletion_log` entry that names the count of backups removed (no contents). Also expose a single "delete all backups" action behind step-up re-auth (`purpose: "melt"`).
6. **Honest limits:** `secure_delete` does not guarantee erasure of old file blocks on APFS/SSD. Do not claim physical erasure. Because each backup is encrypted, destroying the wrapped keys plus the files is the strongest honest statement; say exactly that in `privacy.md` and in the UI copy.
7. **Restore:** a CLI `scripts/restore_backup.py <file>` that prompts for the passphrase, verifies, and restores into an empty runtime directory. Test it round-trip.
8. **API/UI:** `GET /api/privacy` returns a real `last_backup_at` and `backup_count` only when backups exist. Show `#backupRow` only then. Do not add any UI claim not backed by a test.

## Tests required (synthetic data only)
- Round trip: write sentinel memories → backup → wipe → restore → sentinels present.
- Wrong passphrase, truncated file, and one flipped byte each fail with no output file.
- Sentinel scan: no sentinel plaintext appears anywhere in the backup file bytes.
- Melt: after executing a scheduled melt, no backup file, wrapped key, or sentinel remains under the scanned directory; `deletion_log` shows the backup count; late cancel still returns 409.
- Permissions: directory 0700, files 0600.
- Backup is skipped while melt is executing.
- No network use anywhere (the existing offline-only browser check must still pass).

## Documentation (CLAUDE.md requires it)
Update `CHANGELOG.md`, `privacy.md`, `RELEASE_READINESS.md` (gate 4 may only move to "implemented, deletion proof pending real-machine run"; gate 8 stays open until run on the Mini), and list every deviation from the approved proposal.

## Do not
- Do not change `personal_use_ready` from false.
- Do not store the backup passphrase, in code, env files, or the keychain, unless Erik explicitly approves it in writing.
- Do not add cloud or off-device copies. Moving backups off the Mini is the owner's manual action.
