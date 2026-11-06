"""Voice choices for the companion. Maps a saved voice id to a Kokoro voice (comma = blend)."""
from __future__ import annotations

import json
from pathlib import Path

CONFIG = Path(__file__).resolve().parent.parent / "config" / "models.json"


def _load() -> dict:
    return json.loads(CONFIG.read_text()).get("voices", {})


def available_voices() -> list[dict]:
    cfg = _load()
    return [
        {"id": vid, "label": v["label"], "note": v.get("note", "")}
        for vid, v in cfg.get("options", {}).items()
    ]


def resolve_voice(voice_id: str | None) -> dict:
    """Return {id, kokoro_voice, lang_code}; unknown ids fall back to the default."""
    cfg = _load()
    options = cfg.get("options", {})
    vid = voice_id if voice_id in options else cfg.get("default", "willow")
    return {"id": vid, **options[vid]}
