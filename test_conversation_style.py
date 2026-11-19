"""P009: the workshop tone reaches the model, and she can ask for a listener or a chat for the day. Synthetic only."""
import asyncio
import re
import unittest
from pathlib import Path

from app.companion import LlmSettings, stream_reply, with_style
from app.conversation_style import DEFAULT_TONE, DayMode, detect_mode_request, style_for
from test_voice import FakeEngine, Harness, must_not_call, silence, tone

ROOT = Path(__file__).parent
SETTINGS = LlmSettings("http://127.0.0.1:1/v1", "synthetic-model", "BASE PROMPT")


class StyleTests(unittest.TestCase):
    def test_default_tone_is_a_little_more_engaging_than_before(self):
        style = style_for(None)
        self.assertEqual(style, style_for(DEFAULT_TONE))
        self.assertEqual(style.max_sentences, 3)
        self.assertIn("two or three short sentences", style.instructions)
        self.assertIn("every other reply", style.instructions)
        self.assertIn("feeling behind", style.instructions)

    def test_quiet_and_lively_tones(self):
        quiet = style_for({"depth": 0.1, "questions": 0.1, "humor": 0.0})
        self.assertEqual(quiet.max_sentences, 2)
        self.assertIn("Rarely ask questions", quiet.instructions)
        lively = style_for({"depth": 0.8, "questions": 0.8, "humor": 0.7})
        self.assertEqual(lively.max_sentences, 4)
        self.assertIn("most replies", lively.instructions)
        self.assertIn("humor", lively.instructions)

    def test_listen_mode_overrides_a_lively_tone(self):
        style = style_for({"depth": 0.9, "questions": 0.9, "humor": 0.9}, "listen")
        self.assertEqual(style.max_sentences, 2)
        self.assertIn("mostly to listen", style.instructions)
        self.assertNotIn("follow-up question", style.instructions)
        self.assertNotIn("humor", style.instructions)

    def test_chat_mode_lifts_a_quiet_tone(self):
        style = style_for({"depth": 0.1, "questions": 0.1, "humor": 0.1}, "chat")
        self.assertEqual(style.max_sentences, 4)
        self.assertIn("over coffee", style.instructions)
        self.assertIn("follow her lead if she turns to something heavier", style.instructions)
        self.assertNotIn("Rarely ask questions", style.instructions)

    def test_challenge_is_capped_by_directness_like_the_workshop(self):
        self.assertNotIn("another angle", style_for({"challenge": 0.9, "directness": 0.2}).instructions)
        self.assertIn("another angle", style_for({"challenge": 0.9, "directness": 0.9}).instructions)

    def test_bad_values_fall_back_safely(self):
        style = style_for({"depth": "lots", "questions": 7, "unknown": 1})
        self.assertLessEqual(style.max_sentences, 4)
        self.assertIn("most replies", style.instructions)      # 7 is clamped to 1.0

    def test_style_never_weakens_the_rules(self):
        banned = re.compile(r"therapist|diagnos|emergency|call (911|988)|ignore", re.I)
        for mode in (None, "listen", "chat"):
            for value in (0.0, 0.5, 1.0):
                text = style_for({k: value for k in DEFAULT_TONE}, mode).instructions
                self.assertFalse(banned.search(text), (mode, value))

    def test_base_prompt_keeps_safety_and_memory_rules(self):
        prompt = (ROOT / "config" / "system_prompt.txt").read_text()
        for rule in ("Never diagnose", "never claim to be a therapist", "hurting themselves",
                     "You remember her", "How to talk right now"):
            self.assertIn(rule, prompt)
        self.assertNotIn("one or two short sentences", prompt)      # length now comes from the style
        combined = with_style(SETTINGS, style_for(None)).system_prompt
        self.assertTrue(combined.startswith("BASE PROMPT\n\nHow to talk right now: "))

    def test_thresholds_match_the_workshop_preview(self):
        page = (ROOT / "dist" / "index.html").read_text()
        for snippet in ("t.depth>.6", "t.depth>.3", "t.questions>.7", "t.questions>.35", "t.humor>.6",
                        "t.directness>.66", "t.directness>.33", "t.challenge>.66", "t.challenge>.4",
                        "t.warmth>.66", "t.warmth>.33"):
            self.assertIn(snippet, page)


class AskingOutLoudTests(unittest.TestCase):
    def test_listen_requests(self):
        for text in ("Can you just listen today?", "I just need you to listen.", "Okay, just listen.",
                     "I need someone to listen tonight", "Just listen to me for a bit", "No questions today."):
            self.assertEqual(detect_mode_request(text), "listen", text)

    def test_chat_requests(self):
        for text in ("Let's chat.", "Can we just talk for a while?", "Talk to me.", "I'm in the mood to chat",
                     "Hey Hearth, let's talk"):
            self.assertEqual(detect_mode_request(text), "chat", text)

    def test_back_to_normal(self):
        for text in ("Back to normal.", "You can go back to normal now", "Talk normally"):
            self.assertEqual(detect_mode_request(text), "default", text)

    def test_ordinary_sentences_do_not_switch(self):
        for text in ("Let's talk about my sister.", "Can we talk about work?", "Just listen to this song I found",
                     "My friend never listens to me.", "We chatted at lunch.", "I talked to my mom.",
                     "I had a long day at work.", "Talk to me about something else? No, never mind", ""):
            self.assertIsNone(detect_mode_request(text), text)

    def test_day_mode_ends_with_the_day(self):
        today = ["2026-11-09"]
        mode = DayMode(today=lambda: today[0])
        self.assertIsNone(mode.get())
        mode.set("listen")
        self.assertEqual(mode.get(), "listen")
        today[0] = "2026-11-10"
        self.assertIsNone(mode.get())
        mode.set("chat")
        mode.set("nonsense")
        self.assertIsNone(mode.get())


def recording_llm(record, reply=("One. ", "Two. ", "Three. ", "Four. ", "Five.")):
    def call(base_url, model, messages):
        record.append(messages[0]["content"])
        yield from reply
    return call


class SentenceCapTests(unittest.TestCase):
    def test_stream_reply_respects_the_style_cap(self):
        for cap in (2, 3, 4):
            out = list(stream_reply("I had a long day.", [], SETTINGS, recording_llm([]), cap))
            self.assertEqual(len(out), cap)


class VoiceSessionStyleTests(unittest.IsolatedAsyncioTestCase):
    async def turn(self, h, heard):
        h.engine.heard = heard
        await h.say(tone(1.0) + silence(1.2))
        await h.finish_playback()

    async def test_tone_reaches_the_model_each_turn(self):
        prompts, current = [], [{"depth": 0.1, "questions": 0.1, "humor": 0.0}]
        h = Harness(llm=recording_llm(prompts), tone=lambda: current[0], day_mode=DayMode())
        await self.turn(h, "I had a long day at work.")
        self.assertIn("Rarely ask questions", prompts[-1])
        self.assertEqual(len(h.engine.spoken), 2)                 # quiet tone: at most two sentences
        current[0] = {"depth": 0.8, "questions": 0.8, "humor": 0.7}
        await self.turn(h, "The bus was late again.")
        self.assertIn("most replies", prompts[-1])
        self.assertEqual(len(h.engine.spoken), 2 + 4)

    async def test_asking_for_a_listener_lasts_across_turns_and_connections(self):
        prompts, shared = [], DayMode()
        h = Harness(llm=recording_llm(prompts), day_mode=shared)
        await self.turn(h, "Can you just listen today?")
        self.assertIn("mostly to listen", prompts[-1])
        await self.turn(h, "Work was a lot.")
        self.assertIn("mostly to listen", prompts[-1])
        h2 = Harness(llm=recording_llm(prompts), day_mode=shared)    # a page reload is a new connection
        await self.turn(h2, "Still thinking about it.")
        self.assertIn("mostly to listen", prompts[-1])
        await self.turn(h2, "Let's chat.")
        self.assertIn("over coffee", prompts[-1])
        await self.turn(h2, "Back to normal.")
        self.assertNotIn("over coffee", prompts[-1])
        self.assertNotIn("mostly to listen", prompts[-1])

    async def test_crisis_words_never_change_the_mode_or_reach_the_model(self):
        shared = DayMode()
        h = Harness(engine=FakeEngine(), llm=must_not_call, day_mode=shared)
        await self.turn(h, "Just listen, I want to kill myself")
        self.assertIsNone(shared.get())
        self.assertGreaterEqual(len(h.engine.spoken), 1)


if __name__ == "__main__":
    unittest.main()
