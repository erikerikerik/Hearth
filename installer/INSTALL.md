# Installing Hearth on a Mac (M3 Pro laptop, Brave)

Hearth ships as a disk image: open it, drag **Hearth** onto **Applications**, open it from there. Clicking the icon
starts the companion and its local language model in the background (bound to this Mac only) and opens it in Brave.
On first launch it asks once to download its voice and language models (about 11 GB on a 24–36 GB Mac); after that
Hearth never uses the internet.

## 1. Build the disk image (once, on the Mac mini)

Needs the Xcode Command Line Tools (your full Xcode includes them) and an internet connection. No Xcode window is used.
Open **Terminal** (Finder > Applications > Utilities > Terminal), then:

```sh
xcode-select -p            # prints a path; if not, run: xcode-select --install
cd /path/to/Hearth/installer      # your clone of github.com/erikerikerik/Hearth
git pull                           # make sure you are on the P008 (or later) commit
```

The build installs Python and every package from pinned, hash-checked sources (`requirements-app.lock`), so it needs
internet but nothing else from you. It refuses to continue if any checksum differs. The finished app is about 1 GB
(Python, MLX, the speech front-end); the models are not inside it.

### Signed and notarized (you have a paid Developer ID)

You need the *Developer ID Application* certificate in your login keychain (the Installer certificate is only for `.pkg`).
If you do not have it yet:

1. Open Xcode. In the menu bar click **Xcode > Settings…**, then the **Accounts** tab.
2. Select your Apple ID, click **Manage Certificates…**, click the **+** at the bottom left, choose **Developer ID Application**.
3. In Terminal, copy the exact name:
   ```sh
   security find-identity -v -p codesigning | grep "Developer ID Application"
   ```
4. Create an app-specific password at appleid.apple.com > Sign-In and Security > App-Specific Passwords, then store a
   notarization login once (it saves the password in your keychain and prompts for it):
   ```sh
   xcrun notarytool store-credentials "hearth-notary" --apple-id "you@example.com" --team-id "ABCDE12345"
   ```
5. Build:
   ```sh
   APP_SIGN_ID="Developer ID Application: Your Name (ABCDE12345)" \
   NOTARY_PROFILE="hearth-notary" \
   ./build.sh
   ```
   Output: `installer/build/Hearth-1.3.0-rc1.dmg`. It downloads the pinned Python (checked against its sha256), installs
   the hash-locked packages, runs a self-check inside the bundle (MLX runs a kernel on the GPU, the speech stack and
   spaCy's English model load offline, the bundled eSpeak library loads, the server starts), compiles the bytecode,
   signs every binary with the hardened runtime, runs the same self-check again under the signature, notarizes and
   staples the app, builds the disk image (with the Hearth icon and a "drag to Applications"
   window), then notarizes and staples the image and checks that macOS accepts it.
   The first run may ask "Terminal wants to control Finder" (for the window layout): click **OK**.

If notarization is rejected: `xcrun notarytool log <submission-id> --keychain-profile hearth-notary`, and send me the output.

Unsigned (own Macs only): run `./build.sh` with no variables; on the laptop use right-click > **Open** > **Open**
(or System Settings > Privacy & Security > **Open Anyway**).

Optional `.pkg` as well: `MAKE_PKG=1 INSTALLER_SIGN_ID="Developer ID Installer: …" ./build.sh`.

## 2. Install on the laptop

Copy the `.dmg` over (AirDrop, USB, shared folder), double-click it, drag **Hearth** onto **Applications**, eject the image,
open Hearth **from Applications** (opening it from the image or Downloads is refused with a reminder).

## 3. First launch

Once each:

1. A dialog asks her to choose a password (8+ characters, typed twice). Stored as an Argon2id hash only.
2. A dialog states the download size and offers **Download** / **Not now**. **Download** fetches the models in the
   background (Brave still opens; Hearth can't listen yet). A notification says when the voice is ready; then reload
   the Hearth tab. Quitting or sleeping mid-download is fine: open Hearth again and it resumes where it stopped.
   This is the only time Hearth uses the internet.
3. A dialog offers **Add to Dock**.

Brave then opens Hearth. Closing the tab does not stop the companion; clicking the icon again reopens it.

### What runs in the background

| Service | What | Where |
|---|---|---|
| `com.hearth.local` | companion: page, memory, Whisper (hearing) and Kokoro (voice) | 127.0.0.1:4173 |
| `com.hearth.llm` | the language model (`mlx_lm.server`), started only once its model is verified | 127.0.0.1:8081 |

Both are per-user LaunchAgents: they start at login and macOS restarts them if they stop. Together they keep the models
in memory (about 11 GB with the balanced model), which is what makes replies fast. Logs: `~/Library/Logs/Hearth/`.

## Where things live (the reason updates never lose history)

| Layer | Location | Replaced by |
|---|---|---|
| App (server, safety logic, bundled default look) | `/Applications/Hearth.app` | dragging a newer Hearth.app over it |
| Data (memories, notes, settings, password hash) | `~/Library/Application Support/Hearth/data` | **nothing** — only the in-app melt or `uninstall.sh --erase-data` |
| Look (optional alternative visuals) | `~/Library/Application Support/Hearth/data/ui` | `ui_manager.py` |
| Models | `~/Library/Application Support/Hearth/data/models` | `model_manager.py` |

Dragging a newer Hearth.app into Applications ("Replace") swaps only the app. The next time she opens it, the service restarts on the new code.

## Changing the look without reinstalling

A look bundle is a zip with `ui.json` (`{"name","version","contract":"1.0"}`) and `index.html` at its root.
From Terminal, using the app's own Python:

```sh
R=/Applications/Hearth.app/Contents/Resources
D="$HOME/Library/Application Support/Hearth/data"
"$R/python/bin/python3" "$R/tools/ui_manager.py" --data-dir "$D" install ~/Downloads/warm-look.zip
"$R/python/bin/python3" "$R/tools/ui_manager.py" --data-dir "$D" status
"$R/python/bin/python3" "$R/tools/ui_manager.py" --data-dir "$D" rollback   # back one step
"$R/python/bin/python3" "$R/tools/ui_manager.py" --data-dir "$D" reset      # back to the bundled look
```

Reload the page in Brave; no restart. Bundles for a different UI contract major version, with unsafe paths, symlinks,
or (when downloaded) a wrong checksum, are rejected. If an installed look breaks, Hearth falls back to the bundled one.
The tool never opens the database.

## Models

`models/manifest.json` pins every model to one exact Hugging Face commit and lists every file with its size and hash
(sha256 for weights, git blob sha1 for small text files). It is generated, not hand-edited:

```sh
python3 scripts/pin_models.py --revision-from-cache   # pin exactly what is in your Mac's Hugging Face cache (what you tested)
python3 scripts/pin_models.py                         # or: pin each repo's current main
python3 scripts/pin_models.py --check                 # build.sh runs this and stops if anything is unpinned
```

The language model is chosen from the Mac's memory, with the same rule as `scripts/install_models.sh`: under 24 GB gets
`fast` (Gemma 4 E4B, 5.2 GB), 24–47 GB gets `balanced` (Gemma 4 12B, 9.0 GB), 48 GB or more gets `large` (26B, 15.6 GB).
Whisper (1.6 GB) and Kokoro (0.4 GB) are always installed. Each model is downloaded into a `.partial` folder, every file
is checked, and only then is the folder renamed into place, so the app never sees a half-written model. To check,
re-verify, or force a profile:

```sh
"$R/python/bin/python3" "$R/tools/model_manager.py" --data-dir "$D" list
"$R/python/bin/python3" "$R/tools/model_manager.py" --data-dir "$D" status
"$R/python/bin/python3" "$R/tools/model_manager.py" --data-dir "$D" verify            # re-hashes ~11 GB; slow
"$R/python/bin/python3" "$R/tools/model_manager.py" --data-dir "$D" --profile fast ensure --accept
```

After a manual `ensure`, open Hearth again so it restarts its services on the new model.

## Smoke test on the laptop (evidence for the installer gate)

After the "voice is ready" notification, open **Terminal** (Finder > Applications > Utilities > Terminal) and paste:

```sh
/Applications/Hearth.app/Contents/Resources/python/bin/python3 /Applications/Hearth.app/Contents/Resources/tools/smoke_installed.py
```

It checks that the companion answers, that the local language model streams a reply (with timings), and that Kokoro
speaks a fixed synthetic sentence which Whisper hears back. It prints a JSON report and ends with `"all_ok": true`. Copy
the whole output into the P008 evidence. It does not test the microphone, Brave's permission prompt or a conversation.

## Uninstall

```sh
/Applications/Hearth.app/Contents/Resources/uninstall.sh              # keeps her data
/Applications/Hearth.app/Contents/Resources/uninstall.sh --erase-data # deletes everything (type ERASE)
```

## What this build does NOT do yet

- P008 adds the voice loop to the installed app, but the patch was written and unit-tested on Linux. `build.sh`,
  signing, notarization, the Finder window layout, the LaunchAgents, the real dialogs and the GPU have **not yet run on
  a Mac with this patch**. The first build on the Mac mini and the first install on the laptop are the test.
- Real conversations on the target laptop (microphone, earbuds, echo, latency) are still unmeasured. `personal_use_ready` stays `false`.
- Voice still needs the shelf password before it connects (open design question in CHANGELOG 1.3.0-rc1).
- No automatic update check; no in-app "change look" button yet.
- No pre-migration backup: unencrypted copies of her data would escape verifiable deletion. Wait for the
  encrypted-backup gate.
