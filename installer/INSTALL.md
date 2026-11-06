# Installing Hearth on a Mac (M3 Pro laptop, Brave)

Hearth ships as a disk image: open it, drag **Hearth** onto **Applications**, open it from there. Clicking the icon
starts the companion in the background (bound to this Mac only) and opens it in Brave.

## 1. Build the disk image (once, on the Mac mini)

Needs the Xcode Command Line Tools (your full Xcode includes them) and an internet connection. No Xcode window is used.
Open **Terminal** (Finder > Applications > Utilities > Terminal), then:

```sh
xcode-select -p            # prints a path; if not, run: xcode-select --install
cd /path/to/Hearth-V1-1.3.0-rc1/installer
```

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
   Output: `installer/build/Hearth-1.3.0-rc1.dmg`. It downloads a checksum-verified Python, installs the pinned
   dependencies, signs every binary with the hardened runtime, re-runs the bundled Python to prove it still works when
   signed, notarizes and staples the app, builds the disk image (with the Hearth icon and a "drag to Applications"
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
2. If model downloads are configured (below) and any are missing: a dialog states the size and offers **Download** / **Not now**.
   This is the only time Hearth uses the internet.
3. A dialog offers **Add to Dock**.

Brave then opens Hearth. Closing the tab does not stop the companion; clicking the icon again reopens it.

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

Edit `models/manifest.json` (in the source tree before building) with, for each model, its real `url`, `sha256`,
`size_bytes`, `min_ram_gb` and `license`. Entries still marked `PLACEHOLDER` are refused. At first launch the largest
tier that fits this Mac's RAM is chosen per role (`llm`, `stt`, `tts`). Downloads resume, are hash-verified, and a
corrupt partial file is discarded. Check with:

```sh
"$R/python/bin/python3" "$R/tools/model_manager.py" --data-dir "$D" list
```

## Uninstall

```sh
/Applications/Hearth.app/Contents/Resources/uninstall.sh              # keeps her data
/Applications/Hearth.app/Contents/Resources/uninstall.sh --erase-data # deletes everything (type ERASE)
```

## What this build does NOT do yet

- **It does not listen.** The icon opens the orb, but microphone capture, speech-to-text, the language model and
  text-to-speech are not implemented (release gates 1, 2 and 5). `personal_use_ready` stays `false`.
- The launcher flow was exercised here only with stubs for `osascript`, `launchctl` and `open`; `hdiutil`, signing,
  notarization, the Finder window layout and the real dialogs first run on your Mac.
- No automatic update check; no in-app "change look" button yet.
- No pre-migration backup: unencrypted copies of her data would escape verifiable deletion. Wait for the
  encrypted-backup gate.
