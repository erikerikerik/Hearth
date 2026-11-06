"""Voice loop tests. Synthetic audio and a fake engine: no model, microphone or network is used."""
import asyncio
import json
import math
import struct
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory

from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.companion import LlmSettings
from app.main import create_app
from app.voice import FRAME_BYTES, Segmenter, VoiceSession, looks_like_speech

PASSWORD = "synthetic-test-passphrase"
SETTINGS = LlmSettings("http://127.0.0.1:8081/v1", "fake", "Be kind.")


def tone(seconds: float, amplitude: int = 6000, hz: int = 220) -> bytes:
    n = int(16000 * seconds)
    return b"".join(struct.pack("<h", int(amplitude * math.sin(2 * math.pi * hz * i / 16000))) for i in range(n))


def silence(seconds: float) -> bytes:
    return b"\x00\x00" * int(16000 * seconds)


class FakeEngine:
    sample_rate = 24000

    def __init__(self, heard="I had a long day at work."):
        self.heard = heard
        self.transcribed = 0
        self.spoken = []

    def transcribe(self, pcm):
        self.transcribed += 1
        return self.heard

    def synthesize(self, text, voice_id):
        self.spoken.append((text, voice_id))
        return struct.pack("<h", 1000) * 2400   # 0.1 s


def fake_llm(base_url, model, messages):
    yield "That sounds heavy. "
    yield "What part of it stayed with you?"


def must_not_call(*args, **kwargs):
    raise AssertionError("model was called")


class SegmenterTests(unittest.TestCase):
    def test_silence_produces_nothing(self):
        self.assertEqual(Segmenter().feed(silence(3)), [])

    def test_speech_then_quiet_makes_one_utterance_with_preroll(self):
        seg = Segmenter()
        out = seg.feed(silence(0.5) + tone(1.0) + silence(1.2))
        self.assertEqual(len(out), 1)
        self.assertGreater(len(out[0]), 16000 * 2)          # more than one second of audio
        self.assertLess(len(out[0]), 16000 * 2 * 2.5)

    def test_short_click_is_discarded(self):
        self.assertEqual(Segmenter().feed(silence(0.5) + tone(0.12) + silence(1.5)), [])

    def test_chunking_does_not_change_the_result(self):
        audio = silence(0.4) + tone(0.9) + silence(1.0)
        whole = Segmenter().feed(audio)
        seg, pieces = Segmenter(), []
        for i in range(0, len(audio), 700):          # odd-sized chunks, not frame aligned
            pieces += seg.feed(audio[i:i + 700])
        self.assertEqual(len(whole), 1)
        self.assertEqual(len(pieces), 1)

    def test_constant_room_noise_does_not_trigger(self):
        self.assertEqual(Segmenter().feed(tone(5, amplitude=120, hz=90)), [])

    def test_very_long_speech_is_cut_off(self):
        out = Segmenter().feed(tone(35))
        self.assertGreaterEqual(len(out), 1)
        self.assertLessEqual(len(out[0]), 16000 * 2 * 30 + FRAME_BYTES)

    def test_reset_drops_partial_utterance(self):
        seg = Segmenter()
        seg.feed(tone(0.6))
        self.assertTrue(seg.in_utterance)
        seg.reset()
        self.assertEqual(seg.feed(silence(1.5)), [])

    def test_speech_filter(self):
        self.assertTrue(looks_like_speech("I had a long day."))
        for noise in ("", "   ", "...", "you", "Thank you.", "Thanks for watching!"):
            self.assertFalse(looks_like_speech(noise), noise)


class Harness:
    def __init__(self, engine=None, llm=fake_llm, settings=SETTINGS, **extra):
        self.engine = engine or FakeEngine()
        self.json, self.bytes = [], []
        self.session = VoiceSession(
            engine=self.engine, llm_settings=settings, llm_call=llm, voice_id=lambda: "willow",
            send_json=self._json, send_bytes=self._bytes, executor=ThreadPoolExecutor(max_workers=1), tail_seconds=0,
            **extra,
        )

    async def _json(self, value): self.json.append(value)
    async def _bytes(self, value): self.bytes.append(value)

    def kinds(self): return [m["type"] for m in self.json]
    def speakers(self): return [m["speaker"] for m in self.json if m["type"] == "turn.state"]

    async def say(self, audio):
        for i in range(0, len(audio), 640):
            await self.session.on_audio(audio[i:i + 640])

    async def finish_playback(self):
        for _ in range(200):
            if self.session._playback_done is not None:
                self.session._playback_done.set()
                break
            await asyncio.sleep(0.01)
        if self.session._task:
            await asyncio.wait_for(self.session._task, 5)


class VoiceSessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_full_turn_in_order(self):
        h = Harness()
        await h.say(tone(1.0) + silence(1.2))
        await h.finish_playback()
        self.assertEqual(h.speakers(), ["user", "think", "assistant", "idle"])
        transcript = [m for m in h.json if m["type"] == "transcript.partial"][0]
        self.assertEqual((transcript["role"], transcript["text"]), ("user", "I had a long day at work."))
        self.assertEqual(len(h.bytes), 2)                                  # one audio frame per sentence
        self.assertEqual([m["rate"] for m in h.json if m["type"] == "audio.sentence"], [24000, 24000])
        self.assertTrue(any(m["type"] == "audio.done" for m in h.json))
        final = [m for m in h.json if m["type"] == "assistant.delivered" and m["final"]][0]
        self.assertEqual(final["text_so_far"], "That sounds heavy. What part of it stayed with you?")
        self.assertEqual(h.engine.spoken[0][1], "willow")
        self.assertFalse(h.session.busy)

    async def test_timestamps_never_go_backwards(self):
        h = Harness()
        await h.say(tone(1.0) + silence(1.2))
        await h.finish_playback()
        stamps = [m["ts"] for m in h.json if "ts" in m]
        self.assertEqual(stamps, sorted(stamps))

    async def test_crisis_words_never_reach_the_model(self):
        h = Harness(engine=FakeEngine("I want to kill myself"), llm=must_not_call)
        await h.say(tone(1.0) + silence(1.2))
        await h.finish_playback()
        self.assertEqual(h.speakers()[-1], "idle")
        self.assertGreaterEqual(len(h.engine.spoken), 1)          # the deterministic reply was spoken

    async def test_model_down_gives_fallback_not_silence(self):
        def broken(*a): raise ConnectionError("down")
        h = Harness(llm=broken)
        await h.say(tone(1.0) + silence(1.2))
        await h.finish_playback()
        self.assertIn("lost my train of thought", h.engine.spoken[0][0])

    async def test_noise_transcript_is_ignored(self):
        h = Harness(engine=FakeEngine("you"))
        await h.say(tone(1.0) + silence(1.2))
        await asyncio.wait_for(h.session._task, 5)
        self.assertEqual(h.bytes, [])
        self.assertEqual(h.speakers()[-1], "idle")

    async def test_paused_microphone_discards_audio(self):
        h = Harness()
        await h.session.on_control({"type": "ui.mic", "paused": True})
        await h.say(tone(1.0) + silence(1.2))
        self.assertIsNone(h.session._task)
        self.assertEqual(h.engine.transcribed, 0)
        self.assertTrue([m for m in h.json if m["type"] == "ui.mic.ack"][-1]["paused"])

    async def test_pausing_mid_sentence_drops_the_partial_utterance(self):
        h = Harness()
        await h.say(tone(0.7))
        await h.session.on_control({"type": "ui.mic", "paused": True})
        await h.session.on_control({"type": "ui.mic", "paused": False})
        await h.say(silence(1.5))
        self.assertEqual(h.engine.transcribed, 0)

    async def test_audio_while_busy_is_ignored(self):
        h = Harness()
        await h.say(tone(1.0) + silence(1.2))
        self.assertTrue(h.session.busy)
        before = h.session.segmenter.in_utterance
        await h.say(tone(1.0) + silence(1.2))       # Hearth "hears" itself or the room: must be dropped
        self.assertEqual(before, h.session.segmenter.in_utterance)
        await h.finish_playback()
        self.assertEqual(h.engine.transcribed, 1)

    async def test_history_is_memory_only_and_capped(self):
        h = Harness()
        for _ in range(6):
            await h.say(tone(1.0) + silence(1.2))
            await h.finish_playback()
        self.assertEqual(len(h.session.history), 4)

    async def test_interrupt_returns_to_idle(self):
        h = Harness()
        await h.say(tone(1.0) + silence(1.2))
        await asyncio.sleep(0.05)
        await h.session.on_control({"type": "ui.interrupt"})
        self.assertEqual(h.speakers()[-1], "idle")
        self.assertFalse(h.session.busy)

    async def test_preview_speaks_with_the_chosen_voice_and_never_calls_the_model(self):
        h = Harness(llm=must_not_call)
        await h.session.on_control({"type": "voice.preview"})
        await h.finish_playback()
        self.assertEqual(h.speakers(), ["assistant", "idle"])
        self.assertEqual(len(h.bytes), 1)
        self.assertIn("how I would sound", h.engine.spoken[0][0])
        self.assertEqual(h.engine.spoken[0][1], "willow")
        self.assertEqual(h.engine.transcribed, 0)
        self.assertFalse(h.session.busy)

    async def test_engine_failure_reports_degraded_and_recovers(self):
        class Boom(FakeEngine):
            def transcribe(self, pcm): raise RuntimeError("metal")
        h = Harness(engine=Boom())
        await h.say(tone(1.0) + silence(1.2))
        await asyncio.wait_for(h.session._task, 5)
        self.assertIn("degraded", h.kinds())
        self.assertFalse(h.session.busy)


class VoiceSocketTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()

    def tearDown(self):
        self.temp.cleanup()

    def make(self, engine, llm_enabled=True):
        app = create_app(
            password_hash=PasswordHasher().hash(PASSWORD), cookie_secure=False,
            db_path=Path(self.temp.name) / "hearth.sqlite3", dev_tools=False,
            data_dir=Path(self.temp.name), llm_enabled=False, voice_engine=engine,
        )
        client = TestClient(app, base_url="http://127.0.0.1:4173")
        client.__enter__()
        self.addCleanup(client.__exit__, None, None, None)
        return client

    def login(self, client):
        response = client.post("/api/auth/login", json={"password": PASSWORD})
        self.assertEqual(response.status_code, 200)
        # TestClient does not forward its cookie jar to WebSocket connects when Host is overridden.
        self.cookie = {"cookie": "hearth_session=" + client.cookies.get("hearth_session")}

    BASE = {"host": "127.0.0.1:4173", "origin": "http://127.0.0.1:4173"}
    cookie: dict = {}

    @property
    def HEADERS(self):
        return {**self.BASE, **self.cookie}

    def test_requires_a_session(self):
        client = self.make(FakeEngine())
        with client.websocket_connect("/ws/voice", headers=self.BASE) as ws:
            with self.assertRaises(WebSocketDisconnect) as ctx:
                ws.receive_json()
        self.assertEqual(ctx.exception.code, 4401)

    def test_rejects_foreign_origin(self):
        client = self.make(FakeEngine())
        self.login(client)
        with client.websocket_connect("/ws/voice", headers={"host": "127.0.0.1:4173", "origin": "http://evil.example"}) as ws:
            with self.assertRaises(WebSocketDisconnect) as ctx:
                ws.receive_json()
        self.assertEqual(ctx.exception.code, 4403)

    def test_rejects_missing_origin(self):
        client = self.make(FakeEngine())
        self.login(client)
        with client.websocket_connect("/ws/voice", headers={"host": "127.0.0.1:4173"}) as ws:
            with self.assertRaises(WebSocketDisconnect) as ctx:
                ws.receive_json()
        self.assertEqual(ctx.exception.code, 4403)

    def test_rejects_unknown_host(self):
        client = self.make(FakeEngine())
        self.login(client)
        with client.websocket_connect("/ws/voice", headers={"host": "evil.example", "origin": "http://evil.example"}) as ws:
            with self.assertRaises(WebSocketDisconnect) as ctx:
                ws.receive_json()
        self.assertEqual(ctx.exception.code, 4403)

    def test_no_engine_says_voice_is_not_installed(self):
        client = self.make(None)
        self.login(client)
        with client.websocket_connect("/ws/voice", headers=self.HEADERS) as ws:
            message = ws.receive_json()
            self.assertEqual((message["type"], message["component"]), ("degraded", "voice"))
            self.assertIn("not installed", message["reason"])

    def test_voices_endpoint_reports_the_loop(self):
        client = self.make(FakeEngine())
        self.login(client)
        body = client.get("/api/voices").json()
        self.assertTrue(body["voice_loop"])

    def test_end_to_end_over_the_socket(self):
        client = self.make(FakeEngine())
        self.login(client)
        with client.websocket_connect("/ws/voice", headers=self.HEADERS) as ws:
            self.assertEqual(ws.receive_json()["type"], "voice.ready")   # the page opens the mic only after this
            ws.send_text(json.dumps({"type": "ui.mic", "paused": False}))
            self.assertEqual(ws.receive_json()["type"], "ui.mic.ack")
            audio = silence(0.3) + tone(1.0) + silence(1.2)
            for i in range(0, len(audio), 1280):
                ws.send_bytes(audio[i:i + 1280])
            seen, frames = [], 0
            while "audio.done" not in seen:
                message = ws.receive()
                if message.get("bytes") is not None:
                    frames += 1
                else:
                    seen.append(json.loads(message["text"])["type"])
            self.assertGreaterEqual(frames, 1)   # model disabled here: one deterministic sentence
            self.assertIn("transcript.partial", seen)
            ws.send_text(json.dumps({"type": "playback", "state": "ended"}))
            while True:
                m = ws.receive_json()
                if m["type"] == "turn.state" and m["speaker"] == "idle":
                    break

    def test_headers_allow_microphone_and_websocket_for_this_origin_only(self):
        client = self.make(FakeEngine())
        response = client.get("/healthz")
        self.assertIn("microphone=(self)", response.headers["permissions-policy"])
        csp = response.headers["content-security-policy"]
        self.assertIn("connect-src 'self' ws://127.0.0.1:4173;", csp)
        self.assertNotIn("unsafe-inline'; font", csp.split("script-src")[1].split(";")[0])


if __name__ == "__main__":
    unittest.main()
