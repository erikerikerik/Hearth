#!/usr/bin/env python3
"""Generate deterministic, long-form orb contract replays."""

from __future__ import annotations

import json
import math
from pathlib import Path


FPS = 20
ROOT = Path(__file__).resolve().parents[1]


SCENARIOS = (
    ("quiet-room", 101, 30, "idle", 0.02, 0.80, 313, 248),
    ("calm-speaker", 102, 30, "user", 0.20, 0.78, 314, 250),
    ("agitated-speaker", 103, 45, "user", 0.68, 0.18, 336, 374),
    ("assistant-reply", 104, 30, "assistant", 0.36, 0.56, 322, 283),
    ("interruption", 105, 30, "assistant", 0.42, 0.48, 325, 302),
    ("long-silence", 106, 60, "idle", 0.0, 0.66, 318, 262),
    ("memory-kept", 107, 30, "think", 0.14, 0.60, 320, 272),
)


def rounded(value: float) -> float:
    return round(max(0.0, min(1.0, value)), 5)


def make_frame(name: str, index: int, speaker: str, base_energy: float,
               calm: float, hue_a: float, hue_b: float) -> dict:
    t = index / FPS
    active_speaker = speaker
    energy = base_energy

    if name == "quiet-room":
        energy = 0.012 + 0.006 * math.sin(t * 0.23) ** 2
    elif name == "long-silence":
        energy = 0.002 * (1 + math.sin(t * 0.11))
    elif name == "interruption":
        if t >= 14:
            active_speaker = "user"
            energy = 0.62 + 0.12 * math.sin(t * 1.7)
            calm = 0.28
            hue_a, hue_b = 332, 352
        else:
            energy = 0.34 + 0.09 * math.sin(t * 1.1)
    else:
        energy += 0.10 * math.sin(t * 1.31) + 0.05 * math.sin(t * 3.77)

    energy = rounded(energy)
    bands = []
    for band in range(8):
        spectral_falloff = 1.0 - band * 0.085
        movement = 0.74 + 0.18 * math.sin(t * (0.61 + band * 0.09) + band * 0.73)
        bands.append(rounded(energy * spectral_falloff * movement))

    return {
        "t": round(t, 5),
        "bands": bands,
        "energy": energy,
        "speaker": active_speaker,
        "calm": rounded(calm + 0.025 * math.sin(t * 0.17)),
        "mood": {
            "activation": rounded(1 - calm),
            "hueA": round(hue_a + 2 * math.sin(t * 0.07), 4),
            "hueB": round(hue_b + 2 * math.cos(t * 0.09), 4),
        },
    }


def events_for(name: str) -> list[dict]:
    if name == "interruption":
        return [
            {"type": "turn-start", "speaker": "assistant", "at": 0},
            {"type": "turn-end", "speaker": "assistant", "at": 13.95},
            {"type": "turn-start", "speaker": "user", "at": 14},
        ]
    if name == "memory-kept":
        return [{"type": "memory-kept", "id": "synthetic-memory-1", "at": 12}]
    if name in {"calm-speaker", "agitated-speaker", "assistant-reply"}:
        speaker = "assistant" if name == "assistant-reply" else "user"
        return [{"type": "turn-start", "speaker": speaker, "at": 0}]
    return []


def main() -> None:
    fixtures = []
    for name, seed, duration, speaker, energy, calm, hue_a, hue_b in SCENARIOS:
        frame_count = duration * FPS
        fixtures.append({
            "name": name,
            "fps": FPS,
            "duration": duration,
            "seed": seed,
            "frames": [
                make_frame(name, index, speaker, energy, calm, hue_a, hue_b)
                for index in range(frame_count)
            ],
            "events": events_for(name),
        })
    destination = ROOT / "dev_ui" / "synthetic-replays.json"
    destination.write_text(json.dumps(fixtures, separators=(",", ":")) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
