"""Step 1 of the voice loop: text -> spoken audio -> transcribed text, with timings.

Measures on THIS machine: time to first audio, speaking speed vs real time, transcription
speed, round-trip accuracy, and peak memory. Saves a sample WAV you can listen to.
Synthetic sentences only. Run:  .venv-ai/bin/python scripts/voice_smoke.py
"""
import json, re, sys, time, wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.voices import resolve_voice  # noqa: E402

VOICE = resolve_voice(None)  # default: Heart + Nicole blend
cfg = json.loads((ROOT / "config" / "models.json").read_text())
SENTENCES = [
    "Good morning. It's nice to have you here.",
    "That took a lot of courage, speaking up like that.",
    "I don't have any memories of Dana yet. Could you tell me about her?",
    "Take all the time you need. I'm listening.",
    "It sounds like Thursday's meetings are weighing on you before they even start.",
]


def stage(name):
    print("== %s" % name, flush=True)


def fail(name, error):
    print("!! %s failed: %s: %s" % (name, type(error).__name__, error))
    print("!! Paste this whole output back to Claude.")
    sys.exit(1)


import numpy as np
try:
    import mlx.core as mx
    from mlx_audio.tts.utils import load as load_tts
    from mlx_audio.stt.utils import load as load_stt
except Exception as error:
    fail("import", error)

stage("loading speech model (%s)" % cfg["tts"]["mlx"])
t0 = time.perf_counter()
try:
    tts = load_tts(cfg["tts"]["mlx"])
except Exception as error:
    fail("load text-to-speech", error)
tts_load = time.perf_counter() - t0

stage("loading transcription model (%s)" % cfg["stt"]["mlx"])
t0 = time.perf_counter()
try:
    stt = load_stt(cfg["stt"]["mlx"])
except Exception as error:
    fail("load transcription", error)
stt_load = time.perf_counter() - t0


def speak(text):
    start = time.perf_counter(); first = None; chunks = []; rate = 24000
    for result in tts.generate(text=text, voice=VOICE["kokoro_voice"], speed=1.0, lang_code=VOICE["lang_code"]):
        if first is None:
            first = time.perf_counter() - start
        chunks.append(np.array(result.audio, dtype=np.float32).reshape(-1))
        rate = int(result.sample_rate)
    audio = np.concatenate(chunks) if chunks else np.zeros(1, dtype=np.float32)
    return audio, rate, first or 0.0, time.perf_counter() - start


def to16k(audio, rate):
    if rate == 16000:
        return audio
    n = int(len(audio) * 16000 / rate)
    return np.interp(np.linspace(0, len(audio) - 1, n), np.arange(len(audio)), audio).astype(np.float32)


def words(s):
    return re.findall(r"[a-z0-9']+", s.lower())


def wer(ref, hyp):
    r, h = words(ref), words(hyp)
    d = list(range(len(h) + 1))
    for i in range(1, len(r) + 1):
        prev, d[0] = d[0], i
        for j in range(1, len(h) + 1):
            cur = d[j]
            d[j] = min(d[j] + 1, d[j - 1] + 1, prev + (r[i - 1] != h[j - 1]))
            prev = cur
    return d[-1] / max(1, len(r))


# warm-up so the first timed run is not model start-up
try:
    speak("Hello."); stt.generate(np.zeros(16000, dtype=np.float32), language="en")
except Exception as error:
    fail("warm-up", error)

rows = []
for index, text in enumerate(SENTENCES):
    try:
        audio, rate, first, total = speak(text)
        seconds = len(audio) / rate
        heard_start = time.perf_counter()
        out = stt.generate(to16k(audio, rate), language="en")
        heard = (out.text if hasattr(out, "text") else str(out)).strip()
        stt_s = time.perf_counter() - heard_start
    except Exception as error:
        fail("sentence %d" % (index + 1), error)
    rows.append({"text": text, "heard": heard, "audio_s": round(seconds, 2), "tts_first_audio_s": round(first, 2),
                 "tts_total_s": round(total, 2), "tts_realtime_factor": round(total / seconds, 2),
                 "stt_s": round(stt_s, 2), "word_error_rate": round(wer(text, heard), 3)})
    print("%d  first audio %.2fs | speaks %.1fs of audio in %.2fs | transcribed in %.2fs | errors %.0f%%\n    said : %s\n    heard: %s" % (
        index + 1, first, seconds, total, stt_s, 100 * rows[-1]["word_error_rate"], text, heard), flush=True)
    if index == 0:
        sample = ROOT / "bench" / "voice-sample.wav"
        pcm = (np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes()
        with wave.open(str(sample), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate); w.writeframes(pcm)

try:
    peak = mx.get_peak_memory() / 1e9
except Exception:
    try: peak = mx.metal.get_peak_memory() / 1e9
    except Exception: peak = None
mean = lambda key: round(sum(r[key] for r in rows) / len(rows), 2)
summary = {"tts_model": cfg["tts"]["mlx"], "stt_model": cfg["stt"]["mlx"], "load_tts_s": round(tts_load, 1), "load_stt_s": round(stt_load, 1),
           "mean_first_audio_s": mean("tts_first_audio_s"), "mean_tts_realtime_factor": mean("tts_realtime_factor"),
           "mean_stt_s": mean("stt_s"), "mean_word_error_rate": mean("word_error_rate"),
           "peak_memory_gb_this_process": round(peak, 2) if peak is not None else None,
           "note": "Round-trip accuracy uses clean synthetic speech, so it is optimistic. Real microphones and rooms will be worse."}
stamp = time.strftime("%Y%m%d-%H%M%S")
(ROOT / "bench" / ("voice-smoke-%s.json" % stamp)).write_text(json.dumps({"summary": summary, "rows": rows}, indent=1))
print(json.dumps(summary, indent=1))
print("Listen to the sample:  afplay bench/voice-sample.wav")
