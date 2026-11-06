import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from argon2 import PasswordHasher
from fastapi.testclient import TestClient

from app.companion import MODEL_DOWN_TEXT, LlmSettings, clean_model_text, generate_reply, stream_reply
from app.main import create_app

SETTINGS = LlmSettings("http://127.0.0.1:8081/v1", "test-model", "system")


def fake(text, calls=None):
    def stream(base_url, model, messages, **kwargs):
        if calls is not None:
            calls.append(messages)
        yield text
    return stream


def broken(*args, **kwargs):
    raise ConnectionError("model server is down")
    yield  # pragma: no cover


class CompanionTests(unittest.TestCase):
    def test_ordinary_text_uses_the_model_and_passes_history(self):
        calls = []
        reply = generate_reply("The walk helped.", [{"user": "hi", "assistant": "hello"}], SETTINGS, fake("Glad it helped.", calls))
        self.assertEqual((reply.source, reply.text, reply.model_called), ("model", "Glad it helped.", True))
        self.assertEqual([m["role"] for m in calls[0]], ["system", "user", "assistant", "user"])

    def test_crisis_text_never_reaches_the_model(self):
        for text in ("I am going to kill myself tonight", "I keep thinking about suicide"):
            calls = []
            reply = generate_reply(text, None, SETTINGS, fake("model words", calls))
            self.assertEqual(calls, [])
            self.assertFalse(reply.model_called)
            self.assertEqual(reply.source, "safety")
            self.assertIn(reply.risk_level, ("high", "uncertain"))
            self.assertNotIn("model words", reply.text)

    def test_model_claims_of_contacting_others_are_replaced(self):
        reply = generate_reply("hello", None, SETTINGS, fake("I'm here. I called 911 for you."))
        self.assertNotIn("called 911", reply.text)
        self.assertIn("I cannot contact anyone for you.", reply.text)

    def test_role_claims_and_diagnoses_are_dropped(self):
        text = clean_model_text("I am your therapist. You have depression. Tell me more.")
        self.assertEqual(text, "Tell me more.")

    def test_reply_is_capped_at_three_sentences(self):
        self.assertEqual(clean_model_text("One. Two. Three. Four. Five."), "One. Two. Three.")

    def test_unreachable_model_falls_back_without_any_network(self):
        reply = generate_reply("hello", None, SETTINGS, broken)
        self.assertEqual((reply.source, reply.text), ("fallback", MODEL_DOWN_TEXT))

    def test_empty_model_output_falls_back(self):
        self.assertEqual(generate_reply("hello", None, SETTINGS, fake("  ")).source, "fallback")


class StreamingTests(unittest.TestCase):
    @staticmethod
    def chunks(*pieces):
        def stream(*args, **kwargs):
            yield from pieces
        return stream

    def test_sentences_arrive_as_they_complete(self):
        out = list(stream_reply("hello", None, SETTINGS, self.chunks("Hi the", "re. How are", " you? Fine", ". More.")))
        self.assertEqual([s for _, s in out], ["Hi there.", "How are you?", "Fine."])
        self.assertTrue(all(src == "model" for src, _ in out))

    def test_stream_filters_and_drops_like_the_blocking_path(self):
        out = [s for _, s in stream_reply("hello", None, SETTINGS, self.chunks("I am your therapist. I called 911 for you. Okay."))]
        self.assertEqual(out, ["I cannot contact anyone for you. You decide whether to reach someone from your own device.", "Okay."])

    def test_stream_crisis_skips_model(self):
        calls = []
        out = list(stream_reply("I'm going to kill myself", None, SETTINGS, fake("x", calls)))
        self.assertEqual((len(out), out[0][0], calls), (1, "safety", []))

    def test_stream_failure_falls_back(self):
        self.assertEqual(list(stream_reply("hello", None, SETTINGS, broken)), [("fallback", MODEL_DOWN_TEXT)])

    def test_unterminated_last_sentence_is_kept(self):
        self.assertEqual([s for _, s in stream_reply("hi", None, SETTINGS, self.chunks("Hello there"))], ["Hello there"])


class EndpointWiringTests(unittest.TestCase):
    def test_turn_endpoint_uses_the_model_and_records_the_ledger(self):
        with TemporaryDirectory() as temp:
            app = create_app(password_hash=PasswordHasher().hash("synthetic-pass"), cookie_secure=False,
                             db_path=Path(temp) / "t.sqlite3", dev_tools=True, llm_enabled=True,
                             llm_stream=fake("That took courage."), voice_engine=None)
            with TestClient(app, base_url="http://localhost") as client:
                csrf = client.post("/api/auth/login", json={"password": "synthetic-pass"}).json()["csrf_token"]
                self.assertEqual(client.get("/healthz").json()["local_ai"], "model-wired-dev-only")
                body = client.post("/api/conversation/turn", json={"fixture_id": "synthetic-wire", "text": "I spoke up today."},
                                   headers={"X-CSRF-Token": csrf}).json()
                self.assertEqual((body["reply_source"], body["assistant_delivered_text"]), ("model", "That took courage."))
                self.assertFalse(body["outside_contact_attempted"])
                crisis = client.post("/api/conversation/turn", json={"fixture_id": "synthetic-wire", "text": "I'm going to hurt myself"},
                                     headers={"X-CSRF-Token": csrf}).json()
                self.assertEqual((crisis["reply_source"], crisis["model_called"]), ("safety", False))
                ledger = client.get("/api/conversation/ledger").json()["turns"]
                self.assertEqual(len(ledger), 2)


if __name__ == "__main__":
    unittest.main()


class StreamSpacingTests(unittest.TestCase):
    def test_chunk_ending_in_space_does_not_glue_sentences(self):
        from app.companion import LlmSettings, stream_reply
        settings = LlmSettings("http://127.0.0.1:8081/v1", "m", "s")
        chunks = lambda *a: iter(["That sounds heavy. ", "What stayed with you?"])
        out = [text for _, text in stream_reply("I had a long day.", [], settings, chunks)]
        self.assertEqual(out, ["That sounds heavy.", "What stayed with you?"])
