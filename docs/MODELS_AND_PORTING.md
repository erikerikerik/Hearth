# Local models and moving Hearth to another computer

## What runs on the 24 GB M4 mini (gate 1, partial)
Profile **fast** (default): `mlx-community/gemma-4-e4b-it-4bit`, 5.1 GB of weights. Speech-to-text `whisper-large-v3-turbo` (~1.6 GB) and text-to-speech `Kokoro-82M` (~0.2 GB) run beside it. Profiles `balanced` (12B, 9.0 GB) and `large` (26B mixture-of-experts, 15.6 GB, needs a raised GPU memory limit on 24 GB) are in `config/models.json`.
Status: repositories and sizes verified on Hugging Face; client and benchmark tested against a fake local server. **Nothing has been loaded on the Mac mini yet, so no speed or memory number exists.** Do not quote one until `bench/bench_models.py` has run there.

## On the mini
1. `scripts/install_models.sh` (needs internet once, to download weights; takes a while).
2. `scripts/run_llm.sh` in one Terminal window (serves on 127.0.0.1:8081 only, offline).
3. `.venv-ai/bin/python bench/bench_models.py` in another. Read `bench/results-*.md`: speed numbers are measured, tone needs your eyes.
4. Watch Activity Monitor → Memory: "Memory Pressure" must stay green during a run. If it goes yellow, the model is too big for the voice stack.
5. To compare: `HEARTH_PROFILE=balanced scripts/install_models.sh`, restart `run_llm.sh`, benchmark again.

## Moving to a stronger computer
Hearth only talks to one local OpenAI-compatible address (`config/models.json` → `endpoint`), and `app/llm.py` refuses anything that is not loopback.
- **Another Apple-silicon Mac:** `scripts/package_bundle.sh`, copy the tarball, untar, make a venv, run `install_models.sh` (auto-picks a profile from RAM: 24 GB → fast, 48 GB+ → large; override with `HEARTH_PROFILE`), then `tls_setup.sh` and `run_https.sh`. Re-issue certificates there; the bundle never contains keys, data or the CA.
- **A PC with an NVIDIA GPU or Linux:** MLX does not run there. Run llama.cpp's server or Ollama on `127.0.0.1:8081` with a GGUF build of the same model family, and keep everything else unchanged. The install script exits with this message on non-Mac hardware. The TLS scripts and the `therapy.local` name also need redoing (Bonjour is Mac/Windows-with-Bonjour only); the Python app, UI and tests are portable.
- Your data does not move with the bundle. Start fresh or export deliberately; do not copy `runtime/`.

## Licence
Gemma weights use the Gemma licence, not Apache-2.0. Read it before sharing or hosting beyond this household.
