# Privacy and threat-model notes

Status: synthetic V1 release candidate. Not approved for personal use.

- The server binds to loopback and rejects unexpected Host headers.
- Runtime assets are local; the browser loads no third-party runtime asset.
- Password verification uses Argon2id. Sessions are HttpOnly and SameSite strict; mutations require CSRF.
- Login and reauthentication are throttled. Melt requires a fresh, purpose-specific passcode check every time.
- A locked shelf receives memory metadata without text. Ledger access is denied. Closing the curtain locks the shelf.
- SQLite files are `0600`; the runtime directory is `0700`.
- Scheduled melt is executed in the background, survives restarts, cannot be postponed by reposting, and cannot be cancelled once due.
- Synthetic melt removes workshop records and the development ledger, resets settings, checkpoints the WAL and vacuums. It does not claim backup deletion.
- Unmeasured egress and backup rows are hidden.
- The synthetic safety stub is parked behind dev mode and must not receive personal data.

The production LAN service still requires reviewed local HTTPS, name-constrained CA handling, firewall rules, encrypted storage/backups and a clinically reviewed safety gate. No telemetry or cloud fallback is present. The voice loop (1.3.0-rc1) uses the microphone only while the curtain is closed and the page shows the microphone indicator; audio is processed in memory by local speech models and is never written to disk or the database, and the last four spoken exchanges are held in the server process only. The one thing kept from conversation is short memory notes (up to two per turn, written by the local model, never her words) in the local `memories` table, so the companion remembers her across sessions; she can say "forget that" to delete the latest, and melt deletes all (docs/MEMORY.md). Real-device verification is outstanding (see docs/VOICE_LOOP.md).

## 1.2.0 installer notes

- The installed service runs as a per-user LaunchAgent on 127.0.0.1 with `HEARTH_COOKIE_SECURE=0` (loopback http; cookies stay HttpOnly and SameSite=Strict). Do not expose this configuration on a network.
- The password hash lives in `auth.json` (0600) in the data directory; the plaintext is typed into a macOS dialog and piped to the hashing tool on stdin.
- Model download is the only network use. It runs as a separate process (`tools/model_manager.py`, never imported by the companion) after explicit consent, contacts only `huggingface.co` and its download CDN over https (redirects to plain http are refused), fetches each model at one pinned commit and checks every file against the size and hash in `models/manifest.json` before the folder is used. The companion and the language-model service then run with `HF_HUB_OFFLINE=1`. Hugging Face can see the download requests (IP address, which public models, when); nothing about her or her conversations is sent.
- The language model runs as a second per-user LaunchAgent (`com.hearth.llm`) on 127.0.0.1:8081 only.
- Look bundles are verified (checksum when downloaded), cannot contain symlinks or escaping paths, and cannot access the database.
