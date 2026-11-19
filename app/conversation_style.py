"""How much Hearth says: the workshop tone vials, plus a for-today mode she can ask for out loud.

Before P009 the tone vials in the workshop were saved but never reached the model; the reply
length and question rate were fixed in config/system_prompt.txt. This module turns the saved tone
into a few plain instructions appended to the system prompt, and a sentence cap.

  style_for(tone, day_mode) -> Style(instructions, max_sentences)

Day modes, asked for by voice and held in memory only until the end of the local day:
  "listen"  "just listen today", "I just need you to listen"   -> a quiet listener
  "chat"    "let's chat", "talk to me", "can we just talk"      -> easy coffee-table conversation
  None      "back to normal"                                    -> the workshop tone

The thresholds mirror the workshop's sample reply (dist/index.html reply()), so the preview she
sees moves the same way the companion does. Nothing here touches the safety rules: those stay in
the base prompt, and crisis turns never reach the model in any mode (app.companion).
"""
import re
import time
from dataclasses import dataclass
from typing import Callable, Dict, Optional

DEFAULT_TONE: Dict[str, float] = {"warmth": 0.70, "humor": 0.30, "depth": 0.55, "questions": 0.50,
                                  "directness": 0.40, "challenge": 0.30, "pace": 0.50}
MODES = ("listen", "chat")
HARD_MAX_SENTENCES = 4


@dataclass(frozen=True)
class Style:
    instructions: str
    max_sentences: int


def _tone(raw: Optional[dict]) -> Dict[str, float]:
    tone = dict(DEFAULT_TONE)
    for key, value in (raw or {}).items():
        if key in tone:
            try:
                tone[key] = min(1.0, max(0.0, float(value)))
            except (TypeError, ValueError):
                pass
    tone["challenge"] = min(tone["challenge"], tone["directness"] + 0.2)   # same rule as the workshop
    return tone


def style_for(raw_tone: Optional[dict] = None, day_mode: Optional[str] = None) -> Style:
    t = _tone(raw_tone)
    lines = []
    if day_mode == "listen":
        lines.append("Today she has asked you mostly to listen. Answer in one or two short sentences that "
                     "reflect what you heard. Do not ask questions unless she asks you something, and do not "
                     "offer advice or opinions. Quiet company is the point.")
        lines.append(_warmth(t))
        return Style(" ".join(lines), 2)

    engagement = (t["depth"] + t["questions"] + t["humor"]) / 3
    if day_mode == "chat":
        engagement = max(engagement, 0.7)
    if engagement < 0.3:
        lines.append("Usually answer in one or two short sentences, each under about fifteen words.")
        cap = 2
    elif engagement < 0.6:
        lines.append("Usually answer in two or three short sentences, each under about fifteen words.")
        cap = 3
    else:
        lines.append("Answer in two to four short sentences, each under about fifteen words.")
        cap = 4

    lines.append(_warmth(t))
    if t["depth"] > 0.6:
        lines.append("Notice links to what she said earlier or to the notes about her life, and wonder aloud, "
                     "tentatively, about what might sit underneath.")
    elif t["depth"] > 0.3:
        lines.append("Reflect the feeling behind what she says, not only the facts.")
    else:
        lines.append("Stay with what she said; do not dig for more.")

    questions = max(t["questions"], 0.5) if day_mode == "chat" else t["questions"]
    if questions > 0.7:
        lines.append("Ask a follow-up question in most replies, about a specific detail she mentioned.")
    elif questions > 0.35:
        lines.append("About every other reply, ask one gentle follow-up question about something specific she said; "
                     "otherwise reflect it back or add a small thought.")
    else:
        lines.append("Rarely ask questions; mostly reflect what you heard and stay with her.")

    if t["humor"] > 0.6:
        lines.append("Light, kind humor is welcome when the moment is easy; never joke about her pain.")
    elif t["humor"] > 0.3:
        lines.append("A touch of gentle lightness is fine when the mood is easy.")

    if t["directness"] > 0.66:
        lines.append("Say what you notice plainly.")
    elif t["directness"] > 0.33:
        lines.append("Offer what you notice gently, as a possibility.")
    else:
        lines.append("Keep observations soft and tentative.")

    if t["challenge"] > 0.66:
        lines.append("When she seems open to it, gently invite another angle or a small next step.")
    elif t["challenge"] > 0.4:
        lines.append("Now and then, when it fits, ask what she wishes she had said or done.")

    if day_mode == "chat":
        lines.append("Today she is in the mood to chat, like talking over coffee. Share small opinions, light "
                     "observations or a related thought of your own, show interest in her day and the things she "
                     "brings up, and follow her lead if she turns to something heavier.")
    return Style(" ".join(lines), min(cap, HARD_MAX_SENTENCES))


def _warmth(t: Dict[str, float]) -> str:
    if t["warmth"] > 0.66:
        return "Let your warmth show openly."
    if t["warmth"] > 0.33:
        return "Be warm and steady."
    return "Keep warmth understated and plain."


# ----------------------------------------------------------------- asking out loud

_LEAD = r"^\W*(?:(?:please|hey|okay|ok|um|uh|actually|and|so|hearth)\W+)*"
_LISTEN = re.compile(
    _LEAD + r"(?:"
    r"(?:(?:can|could|would) you\W+)?(?:please\W+)?just listen(?!\s+to\s+(?!me\b))\b"
    r"|i (?:just |really )?(?:need|want) you to (?:just )?listen(?!\s+to\s+(?!me\b))\b"
    r"|i (?:just |really )?(?:need|want) (?:a|someone to) listen(?:er)?\b"
    r"|(?:no|less) (?:questions|advice)(?: today| tonight| for now)?\W*$"
    r")",
    re.I,
)
_CHAT = re.compile(
    _LEAD + r"(?:"
    r"let'?s (?:just )?(?:chat|talk)(?!\s+about)\b"
    r"|(?:can|could) we (?:just )?(?:chat|talk)(?!\s+about)\b"
    r"|(?:just )?(?:talk|chat) (?:to|with) me(?!\s+about)\b"
    r"|i'?m in the mood (?:to chat|to talk|for a chat)\b"
    r")",
    re.I,
)
_NORMAL = re.compile(_LEAD + r"(?:(?:you can |let'?s )?(?:go )?back to (?:normal|usual|your usual)\b|(?:talk|be) (?:like )?normal(?:ly)?\b)", re.I)


def detect_mode_request(text: str) -> Optional[str]:
    """'listen', 'chat', 'default', or None. Conservative: only clear requests at the start of a turn."""
    text = (text or "").strip()
    if _NORMAL.search(text):
        return "default"
    if _LISTEN.search(text):
        return "listen"
    if _CHAT.search(text):
        return "chat"
    return None


class DayMode:
    """The mode she asked for, kept in process memory only, until the local date changes."""

    def __init__(self, today: Callable[[], str] = lambda: time.strftime("%Y-%m-%d")):
        self._today = today
        self._mode: Optional[str] = None
        self._date = ""

    def get(self) -> Optional[str]:
        return self._mode if self._mode and self._date == self._today() else None

    def set(self, mode: Optional[str]) -> None:
        self._mode = mode if mode in MODES else None
        self._date = self._today()
