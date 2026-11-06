"""Memory tests. Synthetic sentences only; the "model" is a fake that returns canned JSON."""
import asyncio
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.companion import LlmSettings
from app.remember import (FORGOT_REPLY, NOTHING_TO_FORGET_REPLY, MemoryKeeper, is_forget_request, parse_extraction,
                          similarity)
from app.store import Store
from test_voice import FakeEngine, Harness, silence, tone

SETTINGS = LlmSettings("http://127.0.0.1:8081/v1", "fake", "Be kind.")
SYNTH = [{"id": 1, "category": "people", "text": "Seeded fixture about Dana the synthetic coworker", "status": "confirmed"}]


def make_store(tmp):
    return Store(Path(tmp) / "h.sqlite3", SYNTH, [], {})


def llm_with(facts, chat="That sounds like a lot."):
    """Fake model: extraction calls get JSON, ordinary calls get a short reply. Records every system prompt."""
    calls = []

    def call(base_url, model, messages, **kwargs):
        calls.append(messages[0]["content"])
        if "keep notes" in messages[0]["content"]:
            yield json.dumps(facts)
        else:
            yield chat
    call.calls = calls
    return call


class ParsingTests(unittest.TestCase):
    def test_accepts_valid_and_trims(self):
        out = parse_extraction('Sure: [{"category":"People","text":"Dana, a coworker, often talks over her"}]')
        self.assertEqual(out, [{"category": "people", "text": "Dana, a coworker, often talks over her."}])

    def test_rejects_junk(self):
        bad = ['not json', '[]', '{"a":1}', '[{"category":"feelings","text":"She is sad about work today"}]',
               '[{"category":"people","text":"short"}]', '[{"category":"people","text":"%s"}]' % ("x" * 300),
               '[{"category":"habits","text":"Her account number is 123456789 at the bank"}]',
               '[{"category":"habits","text":"Her email is someone@example.com for work"}]']
        for raw in bad:
            self.assertEqual(parse_extraction(raw), [], raw)

    def test_caps_at_two(self):
        items = [{"category": "habits", "text": "Walks every morning before work %d" % i} for i in range(5)]
        self.assertEqual(len(parse_extraction(json.dumps(items))), 2)

    def test_similarity(self):
        self.assertGreater(similarity("Dana, a coworker, often talks over her in meetings.", "Her coworker Dana talks over her in meetings"), 0.55)
        self.assertLess(similarity("She walks every morning", "Her manager schedules Thursday meetings"), 0.3)

    def test_forget_phrases(self):
        for yes in ("Forget that.", "please forget it", "Can you forget what I just said?", "Okay, don't remember that.", "delete this"):
            self.assertTrue(is_forget_request(yes), yes)
        for no in ("I can't forget that day.", "Forget about it, it's fine.", "I forgot my keys", "remember that for later"):
            self.assertFalse(is_forget_request(no), no)


class StoreAndKeeperTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.store = make_store(self.tmp.name)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_synthetic_and_retired_are_never_used(self):
        self.store.add_memory("habits", "Walks every morning before work.", "candidate", {"source": "conversation"})
        retired = self.store.add_memory("habits", "Used to smoke cigars long ago.", "retired", {"source": "conversation"})
        texts = [r["text"] for r in self.store.memories_for_prompt()]
        self.assertEqual(texts, ["Walks every morning before work."])
        keeper = MemoryKeeper(self.store, SETTINGS)
        block = keeper.prompt_block()
        self.assertNotIn("Seeded fixture", block)
        self.assertNotIn("cigars", block)
        self.assertIn("(habits, tentative) Walks every morning", block)

    def test_empty_memory_never_claims_amnesia(self):
        block = MemoryKeeper(self.store, SETTINGS).prompt_block()
        self.assertIn("still getting to know her", block)
        self.assertIn("Never say that you cannot remember", block)

    def test_solid_memories_come_first_and_untagged(self):
        a = self.store.add_memory("people", "Her sister Maya lives far away.", "confirmed", {"source": "conversation"})
        self.store.add_memory("goals", "Wants to speak up earlier in meetings.", "candidate", {"source": "conversation"})
        lines = [l for l in MemoryKeeper(self.store, SETTINGS).prompt_block().splitlines() if l.startswith("- ")]
        self.assertTrue(lines[0].startswith("- (people) Her sister Maya"))
        self.assertIn("tentative", lines[1])
        self.assertEqual(a["status"], "confirmed")

    def test_extract_stores_candidate_with_provenance_and_no_transcript(self):
        keeper = MemoryKeeper(self.store, SETTINGS, llm_with([{"category": "people", "text": "Dana, a coworker, often talks over her in meetings."}]))
        changes = keeper.extract_and_store(["Dana talked over me again in the meeting today"], "c-1")
        self.assertEqual([(c.op, c.status) for c in changes], [("new", "candidate")])
        row = self.store._conn.execute("SELECT text,status,provenance_json FROM memories WHERE id=?", (changes[0].id,)).fetchone()
        prov = json.loads(row["provenance_json"])
        self.assertEqual((prov["source"], prov["session"]), ("conversation", "c-1"))
        self.assertNotIn("talked over me again", row["provenance_json"])
        dump = json.dumps([dict(r) for r in self.store._conn.execute("SELECT * FROM memories")])
        self.assertNotIn("talked over me again", dump)           # her words are not stored anywhere in memories

    def test_repeat_reinforces_instead_of_duplicating(self):
        fact = [{"category": "people", "text": "Dana, a coworker, often talks over her in meetings."}]
        keeper = MemoryKeeper(self.store, SETTINGS, llm_with(fact))
        keeper.extract_and_store(["x"], "c-1")
        again = [{"category": "people", "text": "Her coworker Dana talks over her in meetings."}]
        keeper.llm_call = llm_with(again)
        changes = keeper.extract_and_store(["y"], "c-2")
        self.assertEqual([(c.op, c.status) for c in changes], [("reinforced", "reinforced")])
        self.assertEqual(len(self.store.memories_for_prompt()), 1)

    def test_kept_memory_stays_kept_when_repeated(self):
        row = self.store.add_memory("goals", "Wants to speak up earlier in meetings.", "confirmed", {"source": "conversation"})
        keeper = MemoryKeeper(self.store, SETTINGS, llm_with([{"category": "goals", "text": "She wants to speak up earlier in meetings."}]))
        keeper.extract_and_store(["x"], "c-1")
        self.assertEqual(self.store._conn.execute("SELECT status FROM memories WHERE id=?", (row["id"],)).fetchone()[0], "confirmed")

    def test_model_failure_is_quiet(self):
        def boom(*a, **k):
            raise ConnectionError("down")
            yield
        self.assertEqual(MemoryKeeper(self.store, SETTINGS, boom).extract_and_store(["hello there"], "c"), [])

    def test_forget_deletes_logs_and_leaves_no_residue(self):
        keeper = MemoryKeeper(self.store, SETTINGS, llm_with([{"category": "moments", "text": "Zebracorn sentinel moment she told me about."}]))
        change = keeper.extract_and_store(["x"], "c")[0]
        self.assertEqual(keeper.forget_last(), change.id)
        self.assertEqual(self.store.memories_for_prompt(), [])
        self.assertIn(("memory", str(change.id), "spoken_request"), [(d["entity_type"], d["entity_id"], d["reason"]) for d in self.store.deletion_log()])
        for f in Path(self.tmp.name).iterdir():
            self.assertNotIn(b"Zebracorn", f.read_bytes(), f.name)
        self.assertIsNone(keeper.forget_last())

    def test_memory_survives_a_new_connection(self):
        """The groundhog-day test: a second keeper on the same store sees what the first learned."""
        MemoryKeeper(self.store, SETTINGS, llm_with([{"category": "goals", "text": "Wants to speak up earlier in meetings."}])).extract_and_store(["x"], "c-1")
        later = MemoryKeeper(self.store, SETTINGS).prompt_block()
        self.assertIn("speak up earlier in meetings", later)


class VoiceMemoryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.store = make_store(self.tmp.name)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def harness(self, llm, engine=None, unlocked=False):
        keeper = MemoryKeeper(self.store, SETTINGS, llm)
        return Harness(engine=engine or FakeEngine("Dana talked over me again today."), llm=llm,
                       memory=keeper, shelf_unlocked=lambda: unlocked, memory_delay=0.05, session_tag="c-test")

    async def talk(self, h):
        await h.say(tone(1.0) + silence(1.2))
        await h.finish_playback()

    async def settle(self, h):
        for _ in range(100):
            await asyncio.sleep(0.05)
            if h.session._memory_task is None or h.session._memory_task.done():
                break

    FACT = [{"category": "people", "text": "Dana, a coworker, often talks over her in meetings."}]

    async def test_learns_after_a_turn_and_tells_the_page_without_text_when_locked(self):
        h = self.harness(llm_with(self.FACT), unlocked=False)
        await self.talk(h)
        await self.settle(h)
        events = [m for m in h.json if m["type"] == "memory.candidate"]
        self.assertEqual(len(events), 1)
        self.assertEqual((events[0]["category"], events[0]["status"], events[0]["text"]), ("people", "candidate", ""))
        self.assertEqual(len(self.store.memories_for_prompt()), 1)

    async def test_unlocked_shelf_gets_the_text(self):
        h = self.harness(llm_with(self.FACT), unlocked=True)
        await self.talk(h)
        await self.settle(h)
        event = [m for m in h.json if m["type"] == "memory.candidate"][0]
        self.assertIn("Dana", event["text"])

    async def test_memory_reaches_the_next_reply_prompt(self):
        llm = llm_with(self.FACT)
        h = self.harness(llm)
        await self.talk(h)
        await self.settle(h)
        llm.calls.clear()
        await self.talk(h)
        chat_prompts = [c for c in llm.calls if "keep notes" not in c]
        self.assertTrue(chat_prompts)
        self.assertIn("Dana, a coworker, often talks over her", chat_prompts[0])

    async def test_crisis_turn_is_never_mined(self):
        llm = llm_with(self.FACT)
        h = self.harness(llm, engine=FakeEngine("I want to kill myself"))
        await self.talk(h)
        await self.settle(h)
        self.assertEqual(self.store.memories_for_prompt(), [])
        self.assertFalse([c for c in llm.calls if "keep notes" in c])

    async def test_spoken_forget_removes_the_last_memory(self):
        llm = llm_with(self.FACT)
        h = self.harness(llm)
        await self.talk(h)
        await self.settle(h)
        self.assertEqual(len(self.store.memories_for_prompt()), 1)
        h.engine.heard = "Forget that."
        await self.talk(h)
        self.assertEqual(self.store.memories_for_prompt(), [])
        self.assertTrue([m for m in h.json if m["type"] == "memory.removed"])
        self.assertEqual(h.engine.spoken[-1][0], FORGOT_REPLY)

    async def test_forget_with_nothing_learned_says_so(self):
        h = self.harness(llm_with([]), engine=FakeEngine("Forget that."))
        await self.talk(h)
        self.assertEqual(h.engine.spoken[-1][0], NOTHING_TO_FORGET_REPLY)

    async def test_pending_notes_are_written_when_the_connection_closes(self):
        h = self.harness(llm_with(self.FACT))
        h.session.memory_delay = 60
        await self.talk(h)
        self.assertEqual(self.store.memories_for_prompt(), [])
        await h.session.flush_memory()
        self.assertEqual(len(self.store.memories_for_prompt()), 1)


if __name__ == "__main__":
    unittest.main()
