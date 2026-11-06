"""Deterministic synthetic safety baseline.

The wording here is not clinically reviewed and must not be enabled for real
personal use. It exists to make the control path and zero-contact invariant
testable before a local model is connected.
"""

import re
from dataclasses import dataclass


POLICY_VERSION = "synthetic-unreviewed-1"


@dataclass(frozen=True)
class SafetyDecision:
    risk_level: str
    response: str
    asks_clarifying_question: bool


EXPLICIT_IMMEDIATE = [
    re.compile(r"\b(i am|i'm) going to (kill|hurt) myself\b", re.I),
    re.compile(r"\bi (have|made) a plan to (kill|hurt) myself\b", re.I),
    re.compile(r"\bi intend to (kill|hurt) myself\b", re.I),
]

RECALL_FLOOR = [
    re.compile(r"\bkill myself\b", re.I),
    re.compile(r"\bhurt myself\b", re.I),
    re.compile(r"\bsuicid(?:e|al)\b", re.I),
    re.compile(r"\bself[- ]harm\b", re.I),
]

FORBIDDEN_ASSISTANT_CLAIMS = [
    re.compile(r"\b(i|we) (called|contacted|notified) (911|988|the police|your family|emergency services)\b", re.I),
    re.compile(r"\bhelp is on the way\b", re.I),
    re.compile(r"\bi am monitoring (you|your location)\b", re.I),
]


def decide(text: str) -> SafetyDecision:
    normalized = " ".join(text.split())
    if any(pattern.search(normalized) for pattern in EXPLICIT_IMMEDIATE):
        return SafetyDecision(
            risk_level="high",
            response=(
                "I’m really sorry you’re carrying this. Are you in immediate danger of acting on that right now? "
                "You can choose to call a local emergency service or someone you trust from your own device. "
                "I have not contacted anyone, and I can stay with you while you decide what to do next."
            ),
            asks_clarifying_question=True,
        )
    if any(pattern.search(normalized) for pattern in RECALL_FLOOR):
        return SafetyDecision(
            risk_level="uncertain",
            response=(
                "I want to check directly rather than guess: are you thinking about hurting yourself, "
                "and do you feel in immediate danger right now?"
            ),
            asks_clarifying_question=True,
        )
    if re.search(r"\b(punch|hit) my boss\b", normalized, re.I):
        return SafetyDecision("ordinary", "Jesus. What happened?", False)
    return SafetyDecision(
        "ordinary",
        "I’m here. Do you want company, or would it help to think it through together?",
        False,
    )


def filter_output(sentence: str) -> str:
    if any(pattern.search(sentence) for pattern in FORBIDDEN_ASSISTANT_CLAIMS):
        return "I cannot contact anyone for you. You decide whether to reach someone from your own device."
    return sentence

