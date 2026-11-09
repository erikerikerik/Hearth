"""Read-only view of the models that tools/model_manager.py finished downloading and verifying.

The companion never downloads anything. When the installed app's data directory has a verified
snapshot for a role, that local folder is used; otherwise the developer tree keeps using the names
in config/models.json (resolved from the developer's own Hugging Face cache, offline).
"""
import json
from pathlib import Path
from typing import Dict, Optional

ROLES = ("llm", "stt", "tts")


def installed_models(data_dir: Optional[Path]) -> Dict[str, dict]:
    """{role: {"path": absolute folder, "profile": str|None}} for complete snapshots only."""
    if not data_dir:
        return {}
    models_dir = Path(data_dir) / "models"
    try:
        data = json.loads((models_dir / "installed.json").read_text())
        roles = data.get("roles", {}) if data.get("schema") == 2 else {}
        root = (models_dir / "snapshots").resolve(strict=True)
    except (OSError, ValueError, AttributeError):
        return {}
    found = {}
    for role in ROLES:
        entry = roles.get(role)
        if not isinstance(entry, dict):
            continue
        try:
            target = (models_dir / str(entry["path"])).resolve(strict=True)
        except (OSError, KeyError):
            continue
        if root in target.parents and target.is_dir() and not target.name.endswith(".partial"):
            found[role] = {"path": str(target), "profile": entry.get("profile")}
    return found
