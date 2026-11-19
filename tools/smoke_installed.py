#!/usr/bin/env python3
"""Smoke test for an installed Hearth on the target Mac. Synthetic text only; no network.

Run it with the app's own Python after the models finished downloading:

  /Applications/Hearth.app/Contents/Resources/python/bin/python3 \\
      /Applications/Hearth.app/Contents/Resources/tools/smoke_installed.py

It checks, and times:
  1. the companion answers /healthz on 127.0.0.1;
  2. the supervised language model answers on 127.0.0.1:8081 and streams a short reply;
  3. the bundled speech stack loads the verified local Whisper and Kokoro snapshots, speaks a
     fixed synthetic sentence and transcribes it back.
It prints one JSON report (paste it into the P008 evidence). Exit code 0 only if every check passed.
Not covered: the microphone, Brave's permission prompt, earbuds, echo or a real conversation.
"""
import json
import os
import platform
import sys
import time
import urllib.request
from pathlib import Path

RES = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RES))
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
sys.dont_write_bytecode = True

DATA = Path(os.environ.get("HEARTH_DATA_DIR") or Path.home() / "Library" / "Application Support" / "Hearth" / "data")
SENTENCE = "The kettle is warm and the lantern is lit on the workshop shelf."
LOOPBACK = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def get_json(url: str, timeout: float = 3.0):
    with LOOPBACK.open(url, timeout=timeout) as response:
        return json.load(response)


def words(text: str) -> set:
    return {w.strip(".,!?").lower() for w in text.split() if w.strip(".,!?")}


def main() -> int:
    from app.companion import load_llm_settings
    from app.llm import stream_chat
    from app.local_models import installed_models
    from app.voice import MlxVoiceEngine, use_bundled_espeak

    report = {"machine": platform.machine(), "macos": platform.mac_ver()[0], "data_dir": str(DATA), "checks": {}}
    checks = report["checks"]
    installed = installed_models(DATA)
    report["installed"] = {role: Path(v["path"]).name for role, v in installed.items()}

    try:
        health = get_json("http://127.0.0.1:%s/healthz" % os.environ.get("HEARTH_PORT", "4173"))
        checks["companion"] = {"ok": health.get("status") == "ok", "build_id": health.get("build_id")}
    except Exception as error:
        checks["companion"] = {"ok": False, "error": repr(error)}

    settings = load_llm_settings(RES, DATA)
    try:
        get_json(settings.base_url + "/models", timeout=5)
        start = time.perf_counter()
        first = None
        pieces = []
        for piece in stream_chat(settings.base_url, settings.model, [
                {"role": "system", "content": "Reply in one short sentence."},
                {"role": "user", "content": "Say hello to a synthetic test."}], max_tokens=40, timeout=120):
            first = first or time.perf_counter()
            pieces.append(piece)
        end = time.perf_counter()
        checks["llm"] = {"ok": bool("".join(pieces).strip()), "model": Path(settings.model).name,
                         "first_token_s": round((first or end) - start, 2), "total_s": round(end - start, 2),
                         "reply_chars": len("".join(pieces))}
    except Exception as error:
        checks["llm"] = {"ok": False, "model": Path(settings.model).name, "error": repr(error)}

    try:
        import numpy as np
        from scipy.signal import resample_poly
        engine = MlxVoiceEngine(data_dir=DATA)
        report["espeak_bundled"] = use_bundled_espeak() or bool(os.environ.get("PHONEMIZER_ESPEAK_LIBRARY"))
        t0 = time.perf_counter()
        engine.load()
        t1 = time.perf_counter()
        pcm = engine.synthesize(SENTENCE, None)
        t2 = time.perf_counter()
        audio = np.frombuffer(pcm, dtype="<i2").astype(np.float32)
        audio16 = resample_poly(audio, 16000, engine.sample_rate)
        heard = engine.transcribe(np.clip(audio16, -32768, 32767).astype("<i2").tobytes())
        t3 = time.perf_counter()
        overlap = len(words(heard) & words(SENTENCE)) / len(words(SENTENCE))
        checks["voice"] = {"ok": overlap >= 0.8, "load_s": round(t1 - t0, 2), "tts_s": round(t2 - t1, 2),
                           "audio_s": round(len(audio) / engine.sample_rate, 2), "stt_s": round(t3 - t2, 2),
                           "word_overlap": round(overlap, 2), "heard": heard,
                           "stt_model": Path(engine.config["stt"]["mlx"]).name,
                           "tts_model": Path(engine.config["tts"]["mlx"]).name}
    except Exception as error:
        checks["voice"] = {"ok": False, "error": repr(error)}

    report["all_ok"] = all(c.get("ok") for c in checks.values())
    print(json.dumps(report, indent=2))
    return 0 if report["all_ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
