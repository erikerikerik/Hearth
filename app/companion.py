"""Turn orchestration: safety first, then the local model, then output filtering.

Order is fixed and tested:
  1. app.safety.decide() runs on the user's words. Anything not "ordinary" gets the
     deterministic reply and the model is NEVER called.
  2. Otherwise the local model (loopback only) writes the reply.
  3. Every sentence passes app.safety.filter_output(); role claims are dropped.
  4. If the model is unavailable the deterministic reply is used. No cloud fallback, ever.
The safety wording is the unreviewed synthetic baseline; this module does not make it clinical.
"""
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Iterator, List, Optional, Tuple

from .llm import stream_chat
from .local_models import installed_models
from .safety import decide, filter_output

log = logging.getLogger("uvicorn.error")
ROOT = Path(__file__).resolve().parent.parent
MAX_SENTENCES = 3
ROLE_CLAIM = re.compile(
    r"\b(i am|i'm|as) (a|your|an) (licensed |professional )?(therapist|counsel+or|psychologist|psychiatrist|doctor|clinician)\b|\bi can diagnose\b|\byou have (depression|anxiety|ptsd|bipolar)\b",
    re.I,
)
MODEL_DOWN_TEXT = "Sorry, I lost my train of thought for a moment. Could you say that again?"
_SENTENCE = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class Reply:
    risk_level: str
    text: str
    source: str  # "safety" | "model" | "fallback"
    asks_clarifying_question: bool
    model_called: bool


@dataclass(frozen=True)
class LlmSettings:
    base_url: str
    model: str
    system_prompt: str


def with_style(settings: LlmSettings, style) -> LlmSettings:
    """The base prompt (safety rules, memory rules) plus the current conversation style."""
    return LlmSettings(settings.base_url, settings.model,
                       settings.system_prompt + "\n\nHow to talk right now: " + style.instructions)


def load_llm_settings(root: Path = ROOT, data_dir: Optional[Path] = None) -> LlmSettings:
    """The model name sent to the loopback server.

    Installed app: the verified local folder from the data directory, which is exactly the path
    the supervised mlx_lm.server was started with (so the server never resolves a hub name).
    Developer tree: the profile's hub name, served from the developer's own offline cache.
    """
    cfg = json.loads((root / "config" / "models.json").read_text())
    prompt = (root / "config" / "system_prompt.txt").read_text().strip()
    local = installed_models(data_dir).get("llm")
    if local:
        return LlmSettings(cfg["endpoint"], local["path"], prompt)
    profile_file = root / ".hearth-profile"
    profile = profile_file.read_text().strip() if profile_file.exists() else cfg["default_profile"]
    return LlmSettings(cfg["endpoint"], cfg["profiles"][profile]["mlx"], prompt)


def clean_model_text(raw: str, max_sentences: int = MAX_SENTENCES) -> str:
    sentences: List[str] = []
    for sentence in _SENTENCE.split(" ".join(raw.split())):
        if not sentence or ROLE_CLAIM.search(sentence):
            continue
        sentences.append(filter_output(sentence))
        if len(sentences) == max_sentences:
            break
    return " ".join(sentences)


def generate_reply(
    user_text: str,
    history: Optional[List[dict]] = None,
    settings: Optional[LlmSettings] = None,
    stream: Callable[..., Iterable[str]] = stream_chat,
    max_sentences: int = MAX_SENTENCES,
) -> Reply:
    decision = decide(user_text)
    if decision.risk_level != "ordinary" or settings is None:
        return Reply(decision.risk_level, filter_output(decision.response),
                     "safety" if decision.risk_level != "ordinary" else "fallback",
                     decision.asks_clarifying_question, False)
    messages = [{"role": "system", "content": settings.system_prompt}]
    for turn in (history or [])[-4:]:
        messages.append({"role": "user", "content": turn["user"]})
        messages.append({"role": "assistant", "content": turn["assistant"]})
    messages.append({"role": "user", "content": user_text})
    try:
        text = clean_model_text("".join(stream(settings.base_url, settings.model, messages)), max_sentences)
    except Exception as error:
        log.warning("hearth: model call failed: %s: %s", type(error).__name__, str(error)[:200])
        text = ""
    if not text:
        return Reply("ordinary", MODEL_DOWN_TEXT, "fallback", True, True)
    return Reply("ordinary", text, "model", text.rstrip().endswith("?"), True)


def stream_reply(
    user_text: str,
    history: Optional[List[dict]] = None,
    settings: Optional[LlmSettings] = None,
    stream: Callable[..., Iterable[str]] = stream_chat,
    max_sentences: int = MAX_SENTENCES,
) -> Iterator[Tuple[str, str]]:
    """Yield (source, sentence) as each sentence completes, already filtered.

    Same rules as generate_reply: crisis text never reaches the model; role claims are
    dropped; at most max_sentences (set by the conversation style); a deterministic fallback.
    The first sentence can be spoken while the rest is still being written.
    """
    decision = decide(user_text)
    if decision.risk_level != "ordinary" or settings is None:
        yield ("safety" if decision.risk_level != "ordinary" else "fallback"), filter_output(decision.response)
        return
    messages = [{"role": "system", "content": settings.system_prompt}]
    for turn in (history or [])[-4:]:
        messages.append({"role": "user", "content": turn["user"]})
        messages.append({"role": "assistant", "content": turn["assistant"]})
    messages.append({"role": "user", "content": user_text})
    emitted = 0
    buffer = ""

    def flush(final: bool) -> Iterator[str]:
        nonlocal buffer
        trailing = buffer[len(buffer.rstrip()):]
        parts = _SENTENCE.split(buffer.strip()) if buffer.strip() else []
        keep = [] if final else parts[-1:]
        for sentence in (parts if final else parts[:-1]):
            yield sentence
        # Keep the trailing space: a chunk that ends "heavy. " must not glue onto the next chunk.
        buffer = (" ".join(keep) + trailing) if keep else ""

    try:
        for piece in stream(settings.base_url, settings.model, messages):
            buffer += piece
            for sentence in flush(False):
                if ROLE_CLAIM.search(sentence):
                    continue
                yield "model", filter_output(" ".join(sentence.split()))
                emitted += 1
                if emitted == max_sentences:
                    return
        for sentence in flush(True):
            if sentence and not ROLE_CLAIM.search(sentence):
                yield "model", filter_output(" ".join(sentence.split()))
                emitted += 1
                if emitted == max_sentences:
                    return
    except Exception as error:
        # Never log what was said; only why the model call failed.
        log.warning("hearth: model call failed: %s: %s", type(error).__name__, str(error)[:200])
    if emitted == 0:
        log.warning("hearth: no spoken text from the model; using the fixed fallback line")
        yield "fallback", MODEL_DOWN_TEXT
