# Run the complete Hearth test bed on the M3 MacBook

The Mac mini is not part of this layout. Brave, Hearth, Gemma, Whisper, Kokoro, memory and SQLite all run on the same M3 laptop. Both servers bind only to `127.0.0.1`; the launcher forces Hugging Face and Transformers offline.

## First-time preparation

The laptop needs the Hearth folder, Brave in `/Applications`, and the already-downloaded local models. Initial model installation is intentionally separate because it requires network consent:

```sh
bash scripts/install_models.sh
bash scripts/install_voice.sh
```

After installation, check the local prerequisites without starting anything:

```sh
bash scripts/launch_testbed.sh --check
```

## Normal launch

In Finder, double-click `Launch-Hearth-Testbed.command`.

1. Terminal opens a dedicated Hearth window.
2. Type a temporary test-bed password of at least 12 characters. The characters do not appear while typing and the password is never written to disk.
3. The launcher starts Gemma on `127.0.0.1:8081` and Hearth on `127.0.0.1:4173`.
4. Brave opens Hearth automatically.
5. Leave that Terminal window alone. Press **Control-C once** in it when finished; both processes stop cleanly.

Test-bed state persists under `runtime/testbed/`, which Git ignores. Logs are under `runtime/testbed-logs/`. Deleting the test-bed state is a separate deliberate operation; the launcher never deletes it.

## What the launcher refuses to do

- It does not bind to the LAN.
- It does not download a missing model.
- It does not open Chrome or another browser.
- It does not store the password.
- It does not kill an unknown process occupying either port.

## DMG path

The launcher is deliberately split into a small double-click wrapper and `scripts/launch_testbed.sh`. A later DMG can call the same core launcher from `Hearth.app`, replacing the temporary password prompt with the installed app's first-run password and replacing Terminal process ownership with launchd. The runtime remains fully local on the laptop.
