# Hands-free voice loop (1.3.0-rc1)

Microphone -> speech-to-text -> companion (safety first, then the local model) -> text-to-speech -> speaker.
Everything runs on the machine. No audio is stored; nothing is sent anywhere.

## How it behaves

- **Hands-free.** Hearth listens as soon as it opens. There is no button to press.
- **Curtain.** Opening the curtain stops the microphone completely (the browser tracks are stopped, so the macOS
  microphone light goes out). Closing it starts the microphone again.
- **Indicator.** A pill at the top of the page always says what is true: `Microphone on · listening`,
  `Microphone on · waiting while I speak`, `Microphone off · curtain open`, `Tap anywhere to start listening`,
  `Microphone blocked · ...`, or `Voice is not installed · text only`. "Listening" is shown only when a live
  microphone track exists and the socket to the server is open.
- **Half-duplex.** While Hearth is thinking or speaking, microphone audio is not sent and the server drops anything that
  arrives. Hearth cannot interrupt itself by hearing its own voice. The existing interrupt control still works.
- **Safety order is unchanged.** Crisis wording is handled by `app/safety.py` before any model is called; those replies are
  spoken as fixed text. The model is never called for them (tested with a model that fails if touched).
- **Short conversation context** is the last four exchanges, kept in the server process only, per connection. Raw spoken
  words and audio are not written to disk. Separately, the memory module may extract up to two short durable notes after
  about four quiet seconds; see `docs/MEMORY.md`. Crisis, fallback and forget turns are never mined.

## Transport (deviation, documented)

`RELEASE_READINESS.md` named WebRTC. This build uses one same-origin WebSocket, `/ws/voice`:

- browser -> server: binary 16 kHz mono int16 PCM; JSON `ui.mic`, `ui.interrupt`, `playback`.
- server -> browser: JSON realtime events v1 (`turn.state`, `transcript.partial`, `assistant.delivered`, `degraded`,
  `ui.mic.ack`) plus `audio.sentence` / `audio.done`, and binary int16 PCM, one sentence at a time.

Why: the browser and server are on the same machine, so WebRTC's network handling buys nothing and adds ICE/STUN surface.
The socket checks Host, Origin (must equal Host) and the login session; it closes with 4401/4403/4503 and the page does not
retry on those. Closing the session or letting it expire stops the microphone path.

Header changes this required: `Permissions-Policy: microphone=(self)` (it was `microphone=()`, which blocks the mic) and
`connect-src 'self' ws://<validated host>`. The CSP still has no `unsafe-inline` for scripts.

## Dependencies added

`websockets` (pinned in `requirements.txt`). Without it uvicorn cannot upgrade a WebSocket; the unit tests did not show
this because the test client bypasses uvicorn. Found by the real-browser check.

## Evidence and limits

Automated on the Mac mini in Brave with a fake microphone, fake speech engine and fake local model:
`tests/voice_browser_check.py` passes all 18 checks for login gating, live-mic truthfulness, orb states, captions,
playback, CSP, curtain pause/resume and reconnect-after-login. The full build also passes 142 Python tests and 27
JavaScript checks. This does not validate real speech models or real-room behavior.

**Still requires real-device verification:**

1. Brave's microphone permission for `http://127.0.0.1:4173` (it asks once; "Allow" is remembered).
2. The real models: Whisper large-v3-turbo and Kokoro through MLX. Run
   `HEARTH_LLM_ENABLED=1 python run_dev.py` with `scripts/run_llm.sh` in another terminal, speak, and watch the indicator.
3. The voice-activity thresholds (`VadConfig`) are first guesses from synthetic tones. Tune on her room and microphone:
   if it cuts her off mid-thought raise `end_silence_frames`; if it triggers on the fridge raise `min_rms` / `floor_ratio`.
4. Echo: browser echo cancellation is requested, but because the loop is half-duplex it is not relied on. Speaking over
   Hearth (barge-in) is intentionally not offered until echo behaviour is measured on the real speakers.
5. Latency end to end (first audio after she stops talking). Whisper + model + first Kokoro sentence have only been
   measured separately in `bench/`.
6. Whisper sometimes invents text on near-silence; a short list of known phantom phrases is ignored (`looks_like_speech`).
   Real-room behaviour is unmeasured.
7. A first-time Brave tab may keep the audio context suspended until she clicks once; the indicator then says
   "Tap anywhere to start listening".

## Not yet part of the installer

The DMG still packages the web app only. For this loop to work from `/Applications/Hearth.app` the installer must also:
bundle `mlx`, `mlx-lm`, `mlx-audio`, `mlx-whisper` and their data (misaki/spaCy) into the app Python; download the
Hugging Face model snapshots at pinned revisions (the current downloader handles single files); and supervise
`mlx_lm.server` on 127.0.0.1:8081. Until then, voice runs from the developer tree (`scripts/install_models.sh`, `run_llm.sh`).
