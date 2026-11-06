"""Renders the same two sentences in many voices so you can pick by ear. Synthetic text only.
Run:  .venv-ai/bin/python scripts/voice_audition.py [--play]
Files land in bench/voices/. --play speaks each name, then plays the clip.
"""
import gc, json, subprocess, sys, time, wave
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "bench" / "voices"; OUT.mkdir(parents=True, exist_ok=True)
PLAY = "--play" in sys.argv
LINE = "Take all the time you need. I'm listening, and there's no hurry at all."
KOKORO = [("kokoro-af_nicole", "af_nicole"), ("kokoro-af_sarah", "af_sarah"), ("kokoro-af_kore", "af_kore"),
          ("kokoro-af_river", "af_river"), ("kokoro-bf_emma", "bf_emma"), ("kokoro-bf_lily", "bf_lily"),
          ("kokoro-blend-heart+nicole", "af_heart,af_nicole"), ("kokoro-blend-nicole+emma", "af_nicole,bf_emma"),
          ("kokoro-am_adam", "am_adam"), ("kokoro-bm_george", "bm_george")]
DESIGNED = {
    "willow": "A warm, calm woman in her late thirties, soft and low, unhurried, like a close friend speaking quietly at a kitchen table.",
    "ember": "A slightly husky woman's voice, gentle and grounded, a little gravelly, kind and steady, speaking slowly.",
    "moss": "A calm, gentle man's voice, low and slow, quietly reassuring, with a smile you can hear.",
    "wren": "A light, soft young woman's voice, curious and kind, a little playful but never loud, speaking gently.",
}
results = []


def save(name, audio, rate):
    path = OUT / (name + ".wav")
    pcm = (np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes()
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate); w.writeframes(pcm)
    return path


def render(model, name, **kw):
    start = time.perf_counter(); first = None; chunks = []; rate = 24000
    for r in model.generate(text=LINE, **kw):
        if first is None: first = time.perf_counter() - start
        chunks.append(np.array(r.audio, dtype=np.float32).reshape(-1)); rate = int(r.sample_rate)
    audio = np.concatenate(chunks); total = time.perf_counter() - start
    path = save(name, audio, rate)
    row = {"name": name, "first_audio_s": round(first, 2), "render_s": round(total, 2), "audio_s": round(len(audio) / rate, 1),
           "realtime_factor": round(total / (len(audio) / rate), 2)}
    results.append(row); print("  %-28s first %.2fs  %.1fs audio in %.1fs (x%.2f realtime)" % (name, first, row["audio_s"], total, row["realtime_factor"]), flush=True)
    return path


from mlx_audio.tts.utils import load
import mlx.core as mx
paths = []
print("== Kokoro voices", flush=True)
try:
    k = load(json.loads((ROOT / "config" / "models.json").read_text())["tts"]["mlx"])
    for name, voice in KOKORO:
        try: paths.append(render(k, name, voice=voice, speed=0.92, lang_code="b" if voice.startswith(("b", "af_nicole,b")) or "bf_" in voice or "bm_" in voice else "a"))
        except Exception as e: print("  %s failed: %s: %s" % (name, type(e).__name__, e))
    del k; gc.collect()
except Exception as e:
    print("!! Kokoro failed: %s: %s" % (type(e).__name__, e))

print("== Designed voices (Qwen3-TTS VoiceDesign, described in words)", flush=True)
try:
    q = load("mlx-community/Qwen3-TTS-12Hz-1.7B-VoiceDesign-4bit")
    for name, desc in DESIGNED.items():
        try: paths.append(render(q, "designed-" + name, instruct=desc, lang_code="english"))
        except Exception as e: print("  %s failed: %s: %s" % (name, type(e).__name__, e))
    del q; gc.collect()
except Exception as e:
    print("!! Designed voices failed: %s: %s" % (type(e).__name__, e))

try: peak = round(mx.get_peak_memory() / 1e9, 2)
except Exception: peak = None
(OUT / "audition.json").write_text(json.dumps({"line": LINE, "peak_gb": peak, "results": results, "designed": DESIGNED}, indent=1))
print("\npeak memory this run: %s GB" % peak)
print("Files in: bench/voices/   Play one: afplay bench/voices/<name>.wav")
if PLAY:
    for p in paths:
        print("playing", p.stem, flush=True)
        subprocess.run(["say", "-v", "Samantha", p.stem.replace("-", " ").replace("_", " ").replace("+", " and ")])
        subprocess.run(["afplay", str(p)]); time.sleep(0.6)
