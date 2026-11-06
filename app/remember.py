"""Long-term memory for the companion: learn short facts, use them quietly, forget on request.

What is stored: one short sentence per fact (people, patterns, goals, moments, habits, open threads),
with provenance (source + connection tag + time). What is NOT stored: her words, transcripts, audio.
New facts are written as status "candidate" (shown on the shelf for her to keep, correct or delete)
and are used tentatively in replies, so the companion stops starting from zero each time.

Rules kept here (each covered by test_remember.py):
  * Crisis turns are never mined for memories, and the model is not asked about them.
  * Synthetic fixture rows are never fed to the model.
  * Numbers that look like identifiers, emails and over-long text are dropped before saving.
  * "Forget that" deletes the most recently touched memory through the store's logged, scrubbed delete.
  * Extraction runs on the local model only (same loopback-only client as replies).
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, Optional

from .companion import LlmSettings
from .llm import stream_chat

log = logging.getLogger("uvicorn.error")

CATEGORIES = ("people", "patterns", "goals", "moments", "habits", "threads")
MAX_NEW_PER_TURN = 2
MIN_LEN, MAX_LEN = 12, 200
PROMPT_MAX_ITEMS = 14
PROMPT_MAX_CHARS = 1100
SOLID = {"confirmed", "corrected", "reinforced"}

EXTRACT_SYSTEM = (
    "You keep notes for a gentle companion. From what she just said, write down at most two lasting facts "
    "worth remembering: people in her life and how she relates to them, recurring patterns, goals, meaningful "
    "moments, habits, and open threads worth following up. Write each as one short sentence about her in the "
    "third person, for example: Dana, a coworker, often talks over her in meetings. "
    "Skip small talk, passing moods, anything you are guessing, medical or psychiatric labels, and anything "
    "about harming herself. Never write phone, account, ID or street-address details. "
    "If nothing is worth keeping, answer []. Answer with JSON only: a list of objects "
    '{"category": "people|patterns|goals|moments|habits|threads", "text": "..."}.'
)

MEMORY_HEADER = (
    "\n\nWHAT YOU REMEMBER ABOUT HER\n"
    "These are real notes from earlier conversations. Use them quietly, the way a friend who listens would: let one "
    "shape your reply only when it truly fits; never list them or announce that you remember. Items marked tentative "
    "may be wrong, so hold them lightly. If she says something that differs, trust her now. Never say that you cannot "
    "remember past conversations or that each time starts fresh."
)
NOTHING_YET = "You have not learned anything lasting about her yet; you are still getting to know her."

_STOP = frozenset("the and for with that this she her has have had was were are about from into over when then they them their his him not but who what you your".split())
_ID_LIKE = re.compile(r"\d{6,}|\b\d{3}[-. ]\d{2,3}[-. ]\d{3,4}\b|@|https?://", re.I)
_FORGET = re.compile(
    r"^\W*(?:(?:please|hey|okay|ok|um|uh|actually|and|so)\W+)*(?:(?:can|could|would) you\W+)?(?:just\W+)?"
    r"(?:(?:forget|erase|delete|remove)\s+(?:that|it|this|what i (?:just )?(?:said|told you))\b"
    r"|(?:don'?t|do not)\s+remember\s+(?:that|it|this)\b)",
    re.I,
)
FORGOT_REPLY = "Okay. It's gone."
NOTHING_TO_FORGET_REPLY = "There's nothing from today that I'm holding onto."


def is_forget_request(text: str) -> bool:
    return bool(_FORGET.search(text.strip()))


def _tokens(text: str) -> frozenset:
    return frozenset(w for w in re.findall(r"[a-z']{3,}", text.lower()) if w not in _STOP)


def similarity(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def parse_extraction(raw: str) -> List[Dict[str, str]]:
    """Pull a validated list of {category, text} out of whatever the model wrote."""
    start, end = raw.find("["), raw.rfind("]")
    if start < 0 or end <= start:
        return []
    try:
        data = json.loads(raw[start:end + 1])
    except ValueError:
        return []
    out: List[Dict[str, str]] = []
    for item in data if isinstance(data, list) else []:
        if not isinstance(item, dict):
            continue
        category = str(item.get("category", "")).strip().lower()
        text = " ".join(str(item.get("text", "")).split())
        if category not in CATEGORIES or not (MIN_LEN <= len(text) <= MAX_LEN) or _ID_LIKE.search(text):
            continue
        if not text.endswith((".", "!", "?")):
            text += "."
        out.append({"category": category, "text": text})
        if len(out) == MAX_NEW_PER_TURN:
            break
    return out


@dataclass
class Change:
    op: str                # "new" | "reinforced"
    id: int
    category: str
    status: str
    text: str


class MemoryKeeper:
    def __init__(self, store, llm_settings: Optional[LlmSettings], llm_call: Callable = stream_chat,
                 clock: Callable[[], float] = time.time):
        self.store = store
        self.llm_settings = llm_settings
        self.llm_call = llm_call
        self.clock = clock
        self.last_touched: Optional[int] = None

    # ----- use -----
    def prompt_block(self) -> str:
        rows = self.store.memories_for_prompt()
        if not rows:
            return MEMORY_HEADER + "\n" + NOTHING_YET
        solid = [r for r in rows if r["status"] in SOLID]
        tentative = [r for r in rows if r["status"] not in SOLID]
        lines: List[str] = []
        used = len(MEMORY_HEADER)
        for row in solid + tentative:        # within each group the store returns newest first
            tag = row["category"] + ("" if row["status"] in SOLID else ", tentative")
            line = "- (%s) %s" % (tag, row["text"])
            if len(lines) >= PROMPT_MAX_ITEMS or used + len(line) > PROMPT_MAX_CHARS:
                break
            lines.append(line)
            used += len(line)
        return MEMORY_HEADER + "\n" + "\n".join(lines)

    # ----- learn -----
    def extract_and_store(self, utterances: Iterable[str], session_tag: str) -> List[Change]:
        """Synchronous; call from a worker thread. Returns what changed so the page can be told."""
        said = [u.strip() for u in utterances if u and u.strip()]
        if not said or self.llm_settings is None:
            return []
        known = [r["text"] for r in self.store.memories_for_prompt()[:15]]
        user = "Already known:\n" + ("\n".join("- " + k for k in known) or "(nothing yet)") + "\n\nShe said:\n" + "\n".join(said)
        messages = [{"role": "system", "content": EXTRACT_SYSTEM}, {"role": "user", "content": user}]
        try:
            raw = "".join(self.llm_call(self.llm_settings.base_url, self.llm_settings.model, messages,
                                        max_tokens=220, temperature=0.2))
        except Exception as error:   # never log what she said
            log.warning("hearth: memory extraction failed: %s: %s", type(error).__name__, str(error)[:200])
            return []
        changes: List[Change] = []
        existing = self.store.memories_for_prompt()
        for item in parse_extraction(raw):
            match = next((r for r in existing if similarity(r["text"], item["text"]) >= 0.55), None)
            if match is not None:
                updated = self.store.reinforce_memory(match["id"])
                if updated:
                    self.last_touched = updated["id"]
                    changes.append(Change("reinforced", updated["id"], updated["category"], updated["status"], updated["text"]))
                continue
            row = self.store.add_memory(item["category"], item["text"], "candidate",
                                        {"source": "conversation", "session": session_tag, "extracted_at": self.clock()})
            existing.insert(0, row)
            self.last_touched = row["id"]
            changes.append(Change("new", row["id"], row["category"], row["status"], row["text"]))
        return changes

    # ----- forget -----
    def forget_last(self) -> Optional[int]:
        """Delete the memory touched most recently in this connection. Returns its id, or None."""
        target, self.last_touched = self.last_touched, None
        if target is None:
            return None
        return target if self.store.delete_memory(target, reason="spoken_request") else None
