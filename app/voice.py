"""Hands-free voice loop: microphone audio in, spoken reply out, over one WebSocket.

Pipeline per utterance (all local, nothing leaves the machine):
  browser mic -> 16 kHz int16 PCM -> Segmenter (voice activity) -> speech-to-text
  -> companion.stream_reply (safety first, then the local model, sentence by sentence)
  -> text-to-speech per sentence -> int16 PCM back to the browser.

Rules kept here, each covered by test_voice.py:
  * Half-duplex: audio is ignored while Hearth thinks or speaks, so it cannot hear itself.
  * A paused mic (curtain open) means incoming audio is discarded and any partial utterance dropped.
  * Spoken words are held in memory for the last few turns only. Nothing from the voice loop is
    written to disk or the database; there is no audio storage.
  * Crisis wording is handled by app.safety inside stream_reply; the model is never called for it.
"""
from __future__ import annotations

import array
import asyncio
import math
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable, Iterator, List, Optional, Protocol, Tuple

from dataclasses import replace as dc_replace

from .companion import LlmSettings, stream_reply
from .remember import FORGOT_REPLY, NOTHING_TO_FORGET_REPLY, MemoryKeeper, is_forget_request
from .safety import decide
from .llm import stream_chat

SAMPLE_RATE = 16000
FRAME_SAMPLES = 320                      # 20 ms
FRAME_BYTES = FRAME_SAMPLES * 2
MAX_UTTERANCE_SECONDS = 30
MAX_HISTORY_TURNS = 4
_HAS_WORD = re.compile(r"[A-Za-z0-9]")
# Whisper tends to invent these on near-silence; a bare one of them is treated as noise.
_NOISE_PHRASES = {"you", "thank you", "thanks for watching", "bye", "the end", "thank you for watching"}


@dataclass(frozen=True)
class VadConfig:
    start_frames: int = 4                # 80 ms of speech to open an utterance
    end_silence_frames: int = 40         # 800 ms of quiet closes it
    min_speech_frames: int = 15          # under 300 ms of speech is discarded as a click or cough
    preroll_frames: int = 10             # 200 ms kept from before the trigger
    min_rms: float = 450.0               # absolute floor on int16 scale
    floor_ratio: float = 3.0             # speech must beat the learned room noise by this factor
    floor_alpha: float = 0.05            # how quickly the noise floor follows quiet frames


def rms_int16(frame: bytes) -> float:
    samples = array.array("h")
    samples.frombytes(frame[: len(frame) - (len(frame) % 2)])
    if not samples:
        return 0.0
    return math.sqrt(sum(s * s for s in samples) / len(samples))


class Segmenter:
    """Energy-based voice activity detector that turns a PCM stream into utterances."""

    def __init__(self, config: VadConfig = VadConfig()):
        self.cfg = config
        self.reset()

    def reset(self) -> None:
        self._pending = bytearray()
        self._preroll: List[bytes] = []
        self._speech: List[bytes] = []
        self._active = False
        self._run = 0
        self._quiet = 0
        self._speech_frames = 0
        self.noise_floor = 150.0

    @property
    def in_utterance(self) -> bool:
        return self._active

    def feed(self, pcm: bytes) -> List[bytes]:
        """Add PCM; return any utterances that finished (usually zero or one)."""
        self._pending.extend(pcm)
        done: List[bytes] = []
        while len(self._pending) >= FRAME_BYTES:
            frame = bytes(self._pending[:FRAME_BYTES])
            del self._pending[:FRAME_BYTES]
            utterance = self._step(frame)
            if utterance is not None:
                done.append(utterance)
        return done

    def _step(self, frame: bytes) -> Optional[bytes]:
        level = rms_int16(frame)
        threshold = max(self.cfg.min_rms, self.noise_floor * self.cfg.floor_ratio)
        loud = level >= threshold
        if not self._active:
            if not loud:
                self.noise_floor += (level - self.noise_floor) * self.cfg.floor_alpha
                self._run = 0
                self._preroll.append(frame)
                del self._preroll[: -self.cfg.preroll_frames]
                return None
            self._run += 1
            self._preroll.append(frame)
            if self._run >= self.cfg.start_frames:
                self._active = True
                self._speech = list(self._preroll)
                self._preroll = []
                self._quiet = 0
                self._speech_frames = self._run
            return None
        self._speech.append(frame)
        if loud:
            self._quiet = 0
            self._speech_frames += 1
        else:
            self._quiet += 1
        too_long = len(self._speech) * FRAME_SAMPLES >= MAX_UTTERANCE_SECONDS * SAMPLE_RATE
        if self._quiet >= self.cfg.end_silence_frames or too_long:
            enough = self._speech_frames >= self.cfg.min_speech_frames
            audio = b"".join(self._speech) if enough else None
            self._speech, self._active, self._run, self._quiet, self._speech_frames = [], False, 0, 0, 0
            return audio
        return None


def looks_like_speech(text: str) -> bool:
    cleaned = " ".join(text.lower().strip(" .!?,\n").split())
    return bool(_HAS_WORD.search(text)) and cleaned not in _NOISE_PHRASES


class VoiceEngine(Protocol):
    sample_rate: int

    def transcribe(self, pcm16k: bytes) -> str: ...
    def synthesize(self, text: str, voice_id: Optional[str]) -> bytes: ...  # int16 PCM at sample_rate


def use_bundled_espeak() -> bool:
    """Point phonemizer at the eSpeak NG library shipped inside the app (espeakng-loader).

    Kokoro's English front-end (misaki) uses eSpeak only for words missing from its dictionary,
    such as names. Without a library it silently skips those words. An explicit environment
    setting wins. Returns True when the bundled copy is in use.
    """
    import importlib
    import os
    if os.environ.get("PHONEMIZER_ESPEAK_LIBRARY"):
        return False
    try:
        loader = importlib.import_module("espeakng_loader")
        library, data = loader.get_library_path(), loader.get_data_path()
    except Exception:
        return False
    if not os.path.isfile(library):
        return False
    os.environ["PHONEMIZER_ESPEAK_LIBRARY"] = library
    os.environ.setdefault("PHONEMIZER_ESPEAK_DATA_PATH", data)
    return True


class MlxVoiceEngine:
    """Local speech models through MLX (Apple silicon). Loaded on first use, then kept warm.

    The model names come from config/models.json. All calls must come from one thread; the
    server routes them through a single-worker executor.
    """

    def __init__(self, config: Optional[dict] = None, data_dir=None):
        import json
        from pathlib import Path

        from .local_models import installed_models

        root = Path(__file__).resolve().parent.parent
        self.config = dict(config or json.loads((root / "config" / "models.json").read_text()))
        # Installed app: load the verified local snapshots, never a hub name.
        for role, local in installed_models(data_dir).items():
            if role in ("stt", "tts"):
                self.config[role] = dict(self.config.get(role, {}), mlx=local["path"])
        self.sample_rate = 24000
        self._tts = None
        self._stt = None

    def load(self) -> None:
        use_bundled_espeak()
        if self._tts is None:
            from mlx_audio.tts.utils import load as load_tts
            self._tts = load_tts(self.config["tts"]["mlx"])
        if self._stt is None:
            from mlx_audio.stt.utils import load as load_stt
            self._stt = load_stt(self.config["stt"]["mlx"])

    def transcribe(self, pcm16k: bytes) -> str:
        import numpy as np
        self.load()
        audio = np.frombuffer(pcm16k, dtype="<i2").astype(np.float32) / 32768.0
        out = self._stt.generate(audio, language="en")
        return (out.text if hasattr(out, "text") else str(out)).strip()

    def synthesize(self, text: str, voice_id: Optional[str]) -> bytes:
        import numpy as np
        from .voices import resolve_voice
        self.load()
        voice = resolve_voice(voice_id)
        chunks = []
        for result in self._tts.generate(text=text, voice=voice["kokoro_voice"], speed=1.0, lang_code=voice["lang_code"]):
            chunks.append(np.array(result.audio, dtype=np.float32).reshape(-1))
            self.sample_rate = int(result.sample_rate)
        if not chunks:
            return b""
        audio = np.clip(np.concatenate(chunks), -1.0, 1.0)
        return (audio * 32767).astype("<i2").tobytes()


def mlx_available() -> bool:
    import importlib.util
    return all(importlib.util.find_spec(name) for name in ("mlx", "mlx_audio", "numpy"))


@dataclass
class VoiceSession:
    """One browser connection. Owns the segmenter, the turn state and the in-memory history."""

    engine: VoiceEngine
    llm_settings: Optional[LlmSettings]
    llm_call: Callable = stream_chat
    voice_id: Callable[[], Optional[str]] = lambda: None
    send_json: Callable = None           # async (dict) -> None
    send_bytes: Callable = None          # async (bytes) -> None
    executor: Optional[ThreadPoolExecutor] = None
    clock: Callable[[], float] = time.monotonic
    vad: VadConfig = field(default_factory=VadConfig)
    tail_seconds: float = 0.35           # extra quiet after playback before listening again
    memory: Optional[MemoryKeeper] = None
    shelf_unlocked: Callable[[], bool] = lambda: False
    session_tag: str = "s0"
    memory_delay: float = 4.0            # quiet seconds before notes are written, so replies are never slowed

    def __post_init__(self):
        self.segmenter = Segmenter(self.vad)
        self.paused = False
        self.busy = False                # thinking or speaking; microphone input is ignored
        self.history: List[dict] = []
        self.turn = 0
        self._task: Optional[asyncio.Task] = None
        self._playback_done: Optional[asyncio.Event] = None
        self._deaf_until = 0.0
        self._last_ts = 0.0
        self._pending_memory: List[str] = []
        self._memory_task: Optional[asyncio.Task] = None

    # ----- events to the browser -----
    def _ts(self) -> float:
        self._last_ts = max(self._last_ts, self.clock())
        return self._last_ts

    async def event(self, kind: str, **fields) -> None:
        await self.send_json({"type": kind, "v": 1, "ts": self._ts(), **fields})

    async def state(self, speaker: str, turn_id: str) -> None:
        await self.event("turn.state", speaker=speaker, turn_id=turn_id)

    # ----- messages from the browser -----
    async def on_audio(self, pcm: bytes) -> None:
        if self.paused or self.busy or self.clock() < self._deaf_until:
            return
        started = self.segmenter.in_utterance
        for utterance in self.segmenter.feed(pcm):
            self.busy = True
            self._task = asyncio.create_task(self._run_turn(utterance))
            break
        if not started and self.segmenter.in_utterance and not self.busy:
            await self.state("user", f"t{self.turn + 1}")

    async def on_control(self, message: dict) -> None:
        kind = message.get("type")
        if kind == "ui.mic":
            self.paused = bool(message.get("paused"))
            if self.paused:
                self.segmenter.reset()
                if not self.busy:
                    await self.state("idle", f"t{self.turn}")
            await self.event("ui.mic.ack", paused=self.paused)
        elif kind == "ui.interrupt":
            await self.interrupt()
        elif kind == "voice.preview":
            if not self.busy:
                self.busy = True
                self._task = asyncio.create_task(self._run_preview())
        elif kind == "playback" and message.get("state") == "ended":
            if self._playback_done is not None:
                self._playback_done.set()

    async def interrupt(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await self.state("idle", f"t{self.turn}")
        self.segmenter.reset()
        self.busy = False

    async def close(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass

    # ----- notes for later (runs only after a quiet moment) -----
    def _schedule_memory(self) -> None:
        if self._memory_task and not self._memory_task.done():
            self._memory_task.cancel()
        self._memory_task = asyncio.create_task(self._memory_after_quiet())

    async def _memory_after_quiet(self) -> None:
        await asyncio.sleep(self.memory_delay)
        while self.busy:
            await asyncio.sleep(0.5)
        await self._write_memories()

    async def _write_memories(self) -> None:
        if not self._pending_memory or self.memory is None:
            return
        said, self._pending_memory = self._pending_memory[-3:], []
        changes = await asyncio.to_thread(self.memory.extract_and_store, said, self.session_tag)
        unlocked = self.shelf_unlocked()
        for change in changes:
            text = change.text if unlocked else ""     # a locked shelf never receives memory text
            try:
                if change.op == "new":
                    await self.event("memory.candidate", id=str(change.id), category=change.category, text=text, status="candidate")
                else:
                    await self.event("memory.updated", id=str(change.id), status=change.status, text=text)
            except Exception:
                break

    async def flush_memory(self) -> None:
        """Called when the connection ends: write whatever is still pending."""
        if self._memory_task and not self._memory_task.done():
            self._memory_task.cancel()
        try:
            await self._write_memories()
        except Exception:
            pass

    # ----- voice preview ("Hear it") -----
    PREVIEW_TEXT = "Hello. This is how I would sound, if you would like me to stay."

    async def _run_preview(self) -> None:
        turn_id = f"p{self.turn}"
        try:
            await self.state("assistant", turn_id)
            self._playback_done = asyncio.Event()
            pcm = await self._in_engine(self.engine.synthesize, self.PREVIEW_TEXT, self.voice_id())
            if pcm:
                rate = self.engine.sample_rate
                await self.send_json({"type": "audio.sentence", "rate": rate, "turn_id": turn_id})
                await self.send_bytes(pcm)
                await self.send_json({"type": "audio.done", "turn_id": turn_id})
                try:
                    await asyncio.wait_for(self._playback_done.wait(), timeout=len(pcm) / 2 / rate + 5.0)
                except asyncio.TimeoutError:
                    pass
            await self.state("idle", turn_id)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            await self.event("degraded", component="voice", reason=type(error).__name__)
            await self.state("idle", turn_id)
        finally:
            self._playback_done = None
            self._deaf_until = self.clock() + self.tail_seconds
            self.segmenter.reset()
            self.busy = False

    # ----- one turn -----
    async def _in_engine(self, fn, *args):
        return await asyncio.get_running_loop().run_in_executor(self.executor, fn, *args)

    async def _run_turn(self, utterance: bytes) -> None:
        self.turn += 1
        turn_id = f"t{self.turn}"
        spoken_any = False
        try:
            await self.state("think", turn_id)
            text = await self._in_engine(self.engine.transcribe, utterance)
            if not looks_like_speech(text):
                await self.state("idle", turn_id)
                return
            await self.event("transcript.partial", turn_id=turn_id, role="user", text=text)
            sources = set()
            if self.memory and is_forget_request(text) and decide(text).risk_level == "ordinary":
                removed = await asyncio.to_thread(self.memory.forget_last)
                if removed is not None:
                    await self.event("memory.removed", id=str(removed))
                sentences = iter([("memory", FORGOT_REPLY if removed is not None else NOTHING_TO_FORGET_REPLY)])
            else:
                settings = self.llm_settings
                if settings is not None and self.memory is not None:
                    settings = dc_replace(settings, system_prompt=settings.system_prompt + self.memory.prompt_block())
                sentences = stream_reply(text, list(self.history), settings, self.llm_call)
            delivered: List[str] = []
            self._playback_done = asyncio.Event()
            audio_seconds = 0.0
            while True:
                item = await asyncio.to_thread(next, sentences, None)
                if item is None:
                    break
                source, sentence = item
                sources.add(source)
                if not sentence.strip():
                    continue
                pcm = await self._in_engine(self.engine.synthesize, sentence, self.voice_id())
                delivered.append(sentence)
                if not pcm:
                    continue
                if not spoken_any:
                    await self.state("assistant", turn_id)
                    spoken_any = True
                rate = self.engine.sample_rate
                audio_seconds += len(pcm) / 2 / rate
                await self.send_json({"type": "audio.sentence", "rate": rate, "turn_id": turn_id})
                await self.send_bytes(pcm)
                await self.event("assistant.delivered", turn_id=turn_id, text_so_far=" ".join(delivered), final=False)
            if delivered:
                if self.memory is not None and sources == {"model"}:   # never from crisis, fallback or forget turns
                    self._pending_memory.append(text)
                    self._schedule_memory()
                self.history.append({"user": text, "assistant": " ".join(delivered)})
                del self.history[:-MAX_HISTORY_TURNS]
                await self.event("assistant.delivered", turn_id=turn_id, text_so_far=" ".join(delivered), final=True)
            await self.send_json({"type": "audio.done", "turn_id": turn_id})
            if spoken_any:
                try:   # the browser says when playback really ended; the timeout covers a lost message
                    await asyncio.wait_for(self._playback_done.wait(), timeout=audio_seconds + 5.0)
                except asyncio.TimeoutError:
                    pass
            await self.state("idle", turn_id)
        except asyncio.CancelledError:
            raise
        except Exception as error:   # engine or model failure must not kill the connection
            await self.event("degraded", component="voice", reason=type(error).__name__)
            await self.state("idle", turn_id)
        finally:
            self._playback_done = None
            self._deaf_until = self.clock() + self.tail_seconds
            self.segmenter.reset()
            self.busy = False
