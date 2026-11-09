"""Authenticated, synthetic-only local API for the Hearth UI milestone."""

import base64
import hashlib
import hmac
import re
import asyncio
import json
import mimetypes
import os
import secrets
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Dict, List, Literal, Optional

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Cookie, Depends, FastAPI, Header, HTTPException, Request, Response, WebSocket, status
from fastapi.responses import JSONResponse
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from .store import Store
from .safety import POLICY_VERSION, decide, filter_output
from .remember import MemoryKeeper
from .voice import MlxVoiceEngine, VoiceSession, mlx_available
from .voices import available_voices
from .companion import generate_reply, load_llm_settings
from .llm import stream_chat


VERSION = "1.3.0-rc1"
PATCH_LEVEL = 8
BUILD_ID = f"{VERSION}+p{PATCH_LEVEL:03d}"
_AUTO_VOICE_ENGINE = object()
UI_CONTRACT_MAJOR = 1
SESSION_COOKIE = "hearth_session"
SESSION_TTL_SECONDS = 30 * 60
REAUTH_TTL_SECONDS = 10 * 60
ALLOWED_HOSTS = {"127.0.0.1", "localhost", "therapy.local", "::1"}
CSP_TEMPLATE = (
    "default-src 'self'; script-src 'self'{script_hashes}; "
    "style-src 'self' 'unsafe-inline'; font-src 'self'; img-src 'self' data:; "
    "media-src 'self' blob:; connect-src 'self'{ws_source}; worker-src 'self' blob:; "
    "object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
)


_INLINE_SCRIPT = re.compile(r"<script(?![^>]*\bsrc=)(?P<attrs>[^>]*)>(?P<body>.*?)</script>", re.S | re.I)


def inline_script_hashes(html_path: Path) -> str:
    """Return CSP sha256 sources for each classic inline script in the built page.

    Hashes are computed from the shipped file at startup, so editing the page
    never needs 'unsafe-inline' for scripts. Style attributes still need
    'unsafe-inline' for styles (documented deviation).
    """
    try:
        html = html_path.read_text(encoding="utf-8")
    except OSError:
        return ""
    hashes = []
    for match in _INLINE_SCRIPT.finditer(html):
        digest = hashlib.sha256(match.group("body").encode("utf-8")).digest()
        hashes.append("'sha256-" + base64.b64encode(digest).decode("ascii") + "'")
    return (" " + " ".join(hashes)) if hashes else ""


SYNTHETIC_MEMORIES = [
    {"id": 1, "category": "people", "text": "Dana, a coworker who often talks over her in meetings", "status": "confirmed"},
    {"id": 2, "category": "patterns", "text": "Holds back when she is interrupted", "status": "reinforced"},
    {"id": 3, "category": "goals", "text": "Speak up earlier in meetings", "status": "confirmed"},
    {"id": 4, "category": "moments", "text": "The spring presentation went better than she feared", "status": "confirmed"},
    {"id": 5, "category": "habits", "text": "A short walk helps her reset", "status": "reinforced"},
    {"id": 6, "category": "habits", "text": "She likes to be asked before I give advice", "status": "confirmed"},
    {"id": 7, "category": "threads", "text": "Thursday meetings seem to weigh on her", "status": "candidate"},
    {"id": 8, "category": "threads", "text": "Maybe follow up about the conversation with her manager", "status": "candidate"},
]

SYNTHETIC_LANTERNS = [
    {"id": 1, "name": "Meetings that leave you drained", "mode": "watch", "level": 0.78, "note": "seen 7 times"},
    {"id": 2, "name": "Holding back when you’re interrupted", "mode": "watch", "level": 0.55, "note": "seen 4 times · easing"},
    {"id": 3, "name": "Venting about the commute", "mode": "venting", "level": 0.18, "note": "just venting"},
]

DEFAULT_SETTINGS = {
    "notice_patterns": True,
    "tone": {
        "warmth": 0.70,
        "humor": 0.30,
        "depth": 0.55,
        "questions": 0.50,
        "directness": 0.40,
        "challenge": 0.30,
        "pace": 0.50,
    },
    "voice": {"id": "willow", "pitch": 0.35},
}


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: str = Field(min_length=1, max_length=512)


class ReauthenticateRequest(LoginRequest):
    purpose: Literal["shelf", "melt"]


class ToneSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    warmth: float = Field(ge=0, le=1)
    humor: float = Field(ge=0, le=1)
    depth: float = Field(ge=0, le=1)
    questions: float = Field(ge=0, le=1)
    directness: float = Field(ge=0, le=1)
    challenge: float = Field(ge=0, le=1)
    pace: float = Field(ge=0, le=1)


class VoiceSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: Literal["willow", "ember", "moss", "wren"]
    pitch: float = Field(ge=0, le=1)


class SettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    notice_patterns: Optional[bool] = None
    tone: Optional[ToneSettings] = None
    voice: Optional[VoiceSettings] = None


class NoteCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=2000)
    author: Literal["E", "me"] = "E"


class NotePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=2000)


class MemoryPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: Optional[str] = Field(default=None, min_length=1, max_length=4000)
    status: Optional[Literal["confirmed", "corrected", "retired"]] = None


class LanternCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(default="", max_length=200)


class LanternPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Optional[str] = Field(default=None, max_length=200)
    mode: Optional[Literal["watch", "venting", "off", "unlit"]] = None
    level: Optional[float] = Field(default=None, ge=0, le=1)


class ConversationTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fixture_id: str = Field(pattern=r"^synthetic-[a-z0-9-]{1,80}$")
    text: str = Field(min_length=1, max_length=4000)


class TonePreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tone: ToneSettings


@dataclass
class Session:
    csrf: str
    expires_at: float
    shelf_unlocked_until: float = 0
    melt_authorized_until: float = 0
    reauth_attempts: List[float] = field(default_factory=list)


@dataclass
class Runtime:
    password_hash: str
    store: Store
    cookie_secure: bool = False
    dev_tools: bool = False
    sessions: Dict[str, Session] = field(default_factory=dict)
    attempts: Dict[str, List[float]] = field(default_factory=dict)
    lock: threading.RLock = field(default_factory=threading.RLock)
    hasher: PasswordHasher = field(default_factory=PasswordHasher)

    def verify_password(self, password: str) -> bool:
        try:
            return self.hasher.verify(self.password_hash, password)
        except VerifyMismatchError:
            return False


def default_data_dir() -> Path:
    return Path(os.environ.get("HEARTH_DATA_DIR") or Path(__file__).parent.parent / "runtime")


def configured_password_hash(data_dir: Optional[Path] = None) -> str:
    existing = os.environ.get("HEARTH_PASSWORD_HASH", "").strip()
    if existing:
        return existing
    auth_file = Path(data_dir or default_data_dir()) / "auth.json"
    if auth_file.is_file():
        try:
            stored = str(json.loads(auth_file.read_text()).get("password_hash", "")).strip()
        except (OSError, ValueError):
            stored = ""
        if stored:
            return stored
    dev_password = os.environ.get("HEARTH_DEV_PASSWORD", "")
    if dev_password:
        return PasswordHasher().hash(dev_password)
    raise RuntimeError(
        "No password configured. Run tools/set_password.py (the installed app does this on first launch). "
        "HEARTH_DEV_PASSWORD is allowed only for synthetic development."
    )


def resolve_ui_root(data_dir: Path, bundled: Path) -> Path:
    """Installed look layer (data_dir/ui/current) if valid and contract-compatible, else the bundled UI.

    Evaluated per request, so a look update or rollback takes effect without a restart
    and never touches the data directory's databases.
    """
    try:
        root = (Path(data_dir) / "ui" / "current").resolve(strict=True)
        manifest = json.loads((root / "ui.json").read_text())
        major = int(str(manifest["contract"]).split(".")[0])
        if major == UI_CONTRACT_MAJOR and (root / "index.html").is_file():
            return root
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return Path(bundled)


def create_app(
    password_hash: Optional[str] = None,
    cookie_secure: Optional[bool] = None,
    db_path: Optional[Path] = None,
    dev_tools: Optional[bool] = None,
    data_dir: Optional[Path] = None,
    bundled_ui: Optional[Path] = None,
    llm_enabled: Optional[bool] = None,
    llm_stream=None,
    voice_engine=_AUTO_VOICE_ENGINE,
) -> FastAPI:
    data_root = Path(data_dir) if data_dir else default_data_dir()
    bundled_root = Path(bundled_ui or os.environ.get("HEARTH_BUNDLED_UI") or Path(__file__).resolve().parent.parent / "dist")
    resolved_db = Path(db_path or os.environ.get("HEARTH_DB_PATH", data_root / "hearth.sqlite3"))
    store = Store(resolved_db, SYNTHETIC_MEMORIES, SYNTHETIC_LANTERNS, DEFAULT_SETTINGS)
    runtime = Runtime(
        password_hash=password_hash or configured_password_hash(data_root),
        store=store,
        cookie_secure=(os.environ.get("HEARTH_COOKIE_SECURE", "1") == "1") if cookie_secure is None else cookie_secure,
        dev_tools=(os.environ.get("HEARTH_DEV_TOOLS", "0") == "1") if dev_tools is None else dev_tools,
    )

    # One worker thread owns every speech-model call (MLX is not safe to share across threads).
    voice_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="hearth-voice")
    voice_state = {"ready": False, "error": ""}
    if voice_engine is not _AUTO_VOICE_ENGINE:
        # Explicit None disables voice. Omitting the argument keeps production's
        # local auto-detection while making tests and tools deterministic.
        voice_engine_ref = [voice_engine] if voice_engine is not None else []
    elif os.environ.get("HEARTH_VOICE_ENABLED", "1") == "1" and mlx_available():
        voice_engine_ref = [MlxVoiceEngine(data_dir=data_root)]
    else:
        voice_engine_ref = []

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        async def melt_executor():
            while True:
                await asyncio.sleep(1)
                await asyncio.to_thread(store.execute_due_melt)

        task = asyncio.create_task(melt_executor())
        if voice_engine_ref and hasattr(voice_engine_ref[0], "load"):
            # Warm the speech models in the background so the first sentence is not slow.
            def warm():
                try:
                    voice_engine_ref[0].load()
                    voice_state["ready"] = True
                except Exception as error:
                    voice_state["error"] = type(error).__name__
            asyncio.get_running_loop().run_in_executor(voice_executor, warm)
        elif voice_engine_ref:
            voice_state["ready"] = True
        try:
            yield
        finally:
            voice_executor.shutdown(wait=False, cancel_futures=True)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            store.close()

    app = FastAPI(
        title="Hearth local API", version=VERSION, docs_url=None, redoc_url=None,
        openapi_url=None, lifespan=lifespan,
    )
    app.state.runtime = runtime
    use_llm = (os.environ.get("HEARTH_LLM_ENABLED", "0") == "1") if llm_enabled is None else llm_enabled
    llm_settings = load_llm_settings(data_dir=data_root) if use_llm else None
    llm_call = llm_stream or stream_chat

    def parse_host(raw: str) -> str:
        raw = raw.strip().lower()
        if raw.startswith("["):
            return raw[1:].split("]", 1)[0]
        return raw.split(":", 1)[0]

    csp_cache: dict = {}

    def csp_for_request(request: Request) -> str:
        # Hashes are taken from the index actually being served (bundled or an installed look),
        # cached by path and mtime so a look update takes effect without a restart.
        index = resolve_ui_root(data_root, bundled_root) / "index.html"
        try:
            key = (str(index), index.stat().st_mtime_ns)
        except OSError:
            key = (str(index), 0)
        if key not in csp_cache:
            csp_cache.clear()
            csp_cache[key] = (str(index), inline_script_hashes(index))
        return csp_cache[key][1]

    def apply_security_headers(request: Request, response):
        hashes = csp_for_request(request)
        host = request.headers.get("host", "").strip().lower()
        # Some browsers do not treat 'self' as covering ws:, so the validated Host is named explicitly.
        ws_source = (" ws://" + host) if parse_host(host) in ALLOWED_HOSTS else ""
        response.headers["Content-Security-Policy"] = CSP_TEMPLATE.format(script_hashes=hashes, ws_source=ws_source)
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(self), geolocation=()"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
        if request.url.path.startswith("/api/") or request.url.path == "/healthz":
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        if parse_host(request.headers.get("host", "")) not in ALLOWED_HOSTS:
            return apply_security_headers(
                request, JSONResponse(status_code=400, content={"detail": "invalid_host"})
            )
        return apply_security_headers(request, await call_next(request))

    def client_key(request: Request) -> str:
        # Per-client so a stranger's failed guesses cannot lock the owner out.
        return request.client.host if request.client else "unknown"

    def require_session(request: Request, hearth_session: Optional[str] = Cookie(default=None)) -> Session:
        now = time.time()
        with runtime.lock:
            session = runtime.sessions.get(hearth_session or "")
            if not session or session.expires_at <= now:
                if hearth_session:
                    runtime.sessions.pop(hearth_session, None)
                raise HTTPException(status_code=401, detail="authentication_required")
            session.expires_at = now + SESSION_TTL_SECONDS
            return session

    def require_csrf(
        session: Session = Depends(require_session),
        x_csrf_token: Optional[str] = Header(default=None),
    ) -> Session:
        if not x_csrf_token or not hmac.compare_digest(session.csrf, x_csrf_token):
            raise HTTPException(status_code=403, detail="csrf_failed")
        return session

    def require_shelf_unlocked(session: Session = Depends(require_session)) -> Session:
        if session.shelf_unlocked_until <= time.time():
            raise HTTPException(status_code=403, detail="shelf_locked")
        return session

    def require_dev_tools():
        if not runtime.dev_tools:
            raise HTTPException(status_code=404, detail="not_found")

    def ui_info():
        root = resolve_ui_root(data_root, bundled_root)
        try:
            manifest = json.loads((root / "ui.json").read_text())
        except (OSError, ValueError):
            manifest = {}
        return {
            "source": "bundled" if root == bundled_root else "installed",
            "name": manifest.get("name"),
            "version": manifest.get("version"),
        }

    @app.get("/healthz")
    def health():
        return {
            "status": "ok",
            "version": VERSION,
            "build_id": BUILD_ID,
            "patch_level": PATCH_LEVEL,
            "mode": "synthetic-v1-release-candidate",
            "local_ai": "model-wired-dev-only" if use_llm else "disabled",
            "persistence": "sqlite-synthetic",
            "personal_use_ready": False,
            "safety_baseline": POLICY_VERSION if runtime.dev_tools else "parked",
            "dev_tools": runtime.dev_tools,
            "ui": ui_info(),
        }

    @app.get("/api/session")
    def session_status(hearth_session: Optional[str] = Cookie(default=None)):
        now = time.time()
        with runtime.lock:
            session = runtime.sessions.get(hearth_session or "")
            if not session or session.expires_at <= now:
                return {"authenticated": False}
            return {
                "authenticated": True,
                "csrf_token": session.csrf,
                "shelf_unlocked": session.shelf_unlocked_until > now,
            }

    @app.post("/api/auth/login")
    def login(body: LoginRequest, request: Request, response: Response):
        now = time.time()
        key = client_key(request)
        with runtime.lock:
            recent = [stamp for stamp in runtime.attempts.get(key, []) if now - stamp < 300]
            runtime.attempts[key] = recent
            if len(recent) >= 5:
                raise HTTPException(status_code=429, detail="login_backoff")
            # Bound memory: drop idle clients' empty records.
            for stale in [k for k, v in runtime.attempts.items() if not v and k != key]:
                runtime.attempts.pop(stale, None)
        valid = runtime.verify_password(body.password)  # Argon2 outside the lock
        with runtime.lock:
            if not valid:
                runtime.attempts.setdefault(key, []).append(time.time())
                raise HTTPException(status_code=401, detail="invalid_credentials")
            runtime.attempts.pop(key, None)
            session_id = secrets.token_urlsafe(32)
            csrf = secrets.token_urlsafe(32)
            runtime.sessions[session_id] = Session(
                csrf=csrf,
                expires_at=now + SESSION_TTL_SECONDS,
                shelf_unlocked_until=now + REAUTH_TTL_SECONDS,
            )
        response.set_cookie(
            SESSION_COOKIE,
            session_id,
            max_age=SESSION_TTL_SECONDS,
            httponly=True,
            secure=runtime.cookie_secure,
            samesite="strict",
            path="/",
        )
        return {"authenticated": True, "csrf_token": csrf, "shelf_unlocked": True}

    @app.post("/api/auth/reauthenticate")
    def reauthenticate(body: ReauthenticateRequest, session: Session = Depends(require_csrf)):
        now = time.time()
        with runtime.lock:
            session.reauth_attempts = [stamp for stamp in session.reauth_attempts if now - stamp < 300]
            if len(session.reauth_attempts) >= 5:
                raise HTTPException(status_code=429, detail="reauthentication_backoff")
        valid = runtime.verify_password(body.password)  # Argon2 outside the lock
        with runtime.lock:
            if not valid:
                session.reauth_attempts.append(time.time())
                raise HTTPException(status_code=401, detail="invalid_credentials")
            session.reauth_attempts.clear()
        if body.purpose == "shelf":
            session.shelf_unlocked_until = now + REAUTH_TTL_SECONDS
            return {"reauthenticated": True, "purpose": "shelf", "until": session.shelf_unlocked_until}
        session.melt_authorized_until = now + 60
        return {"reauthenticated": True, "purpose": "melt", "until": session.melt_authorized_until}

    @app.post("/api/auth/logout")
    def logout(response: Response, session: Session = Depends(require_csrf), hearth_session: Optional[str] = Cookie(default=None)):
        with runtime.lock:
            runtime.sessions.pop(hearth_session or "", None)
        response.delete_cookie(SESSION_COOKIE, path="/")
        return {"authenticated": False}

    @app.post("/api/shelf/lock")
    def lock_shelf(session: Session = Depends(require_csrf)):
        session.shelf_unlocked_until = 0
        return {"shelf_unlocked": False}

    @app.get("/api/workshop")
    def workshop(session: Session = Depends(require_session)):
        return {
            "synthetic": True,
            "shelf_unlocked": session.shelf_unlocked_until > time.time(),
            **runtime.store.workshop(include_memory_text=session.shelf_unlocked_until > time.time()),
        }

    @app.patch("/api/settings")
    def patch_settings(body: SettingsPatch, session: Session = Depends(require_csrf)):
        update = body.model_dump(exclude_none=True)
        if body.tone and body.tone.challenge > body.tone.directness + 0.2:
            update["tone"]["challenge"] = min(1.0, body.tone.directness + 0.2)
        return runtime.store.patch_settings(update)

    @app.post("/api/memories/{memory_id}/keep")
    def keep_memory(memory_id: int, session: Session = Depends(require_csrf)):
        if session.shelf_unlocked_until <= time.time():
            raise HTTPException(status_code=403, detail="shelf_locked")
        memory = runtime.store.keep_memory(memory_id)
        if not memory:
            raise HTTPException(status_code=404, detail="memory_not_found")
        return memory

    @app.patch("/api/memories/{memory_id}")
    def patch_memory(memory_id: int, body: MemoryPatch, session: Session = Depends(require_csrf)):
        if session.shelf_unlocked_until <= time.time():
            raise HTTPException(status_code=403, detail="shelf_locked")
        updates = body.model_dump(exclude_none=True)
        if not updates:
            raise HTTPException(status_code=422, detail="empty_update")
        memory = runtime.store.update_memory(memory_id, updates)
        if not memory:
            raise HTTPException(status_code=404, detail="memory_not_found")
        return memory

    @app.delete("/api/memories/{memory_id}")
    def remove_memory(memory_id: int, session: Session = Depends(require_csrf)):
        if session.shelf_unlocked_until <= time.time():
            raise HTTPException(status_code=403, detail="shelf_locked")
        if not runtime.store.delete_memory(memory_id):
            raise HTTPException(status_code=404, detail="memory_not_found")
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.post("/api/notes", status_code=201)
    def create_note(body: NoteCreate, session: Session = Depends(require_csrf)):
        return runtime.store.create_note(body.text, body.author)

    @app.patch("/api/notes/{note_id}")
    def update_note(note_id: int, body: NotePatch, session: Session = Depends(require_csrf)):
        note = runtime.store.update_note(note_id, body.text)
        if not note:
            raise HTTPException(status_code=404, detail="note_not_found")
        return note

    @app.delete("/api/notes/{note_id}")
    def delete_note(note_id: int, session: Session = Depends(require_csrf)):
        if not runtime.store.delete_note(note_id):
            raise HTTPException(status_code=404, detail="note_not_found")
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.post("/api/lanterns", status_code=201)
    def create_lantern(body: LanternCreate, session: Session = Depends(require_csrf)):
        return runtime.store.create_lantern(body.name)

    @app.patch("/api/lanterns/{lantern_id}")
    def update_lantern(lantern_id: int, body: LanternPatch, session: Session = Depends(require_csrf)):
        updates = body.model_dump(exclude_none=True)
        if not updates:
            raise HTTPException(status_code=422, detail="empty_update")
        lantern = runtime.store.update_lantern(lantern_id, updates)
        if not lantern:
            raise HTTPException(status_code=404, detail="lantern_not_found")
        return lantern

    @app.delete("/api/lanterns/{lantern_id}")
    def delete_lantern(lantern_id: int, session: Session = Depends(require_csrf)):
        if not runtime.store.delete_lantern(lantern_id):
            raise HTTPException(status_code=404, detail="lantern_not_found")
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.post("/api/tone/preview")
    def tone_preview(body: TonePreviewRequest, session: Session = Depends(require_session)):
        tone = body.tone.model_dump()
        if tone["challenge"] > tone["directness"] + 0.2:
            tone["challenge"] = min(1.0, tone["directness"] + 0.2)
        traits = sorted(
            ((key, value) for key, value in tone.items() if key != "pace"),
            key=lambda item: item[1], reverse=True,
        )[:2]
        labels = {"warmth": "warm", "humor": "light", "depth": "reflective", "questions": "curious", "directness": "direct", "challenge": "challenging"}
        return {
            "synthetic": True,
            "side_effect_free": True,
            "tone": tone,
            "blend": " and ".join(labels[key] for key, _ in traits),
            "text": "That sounds frustrating. What part of that moment matters most to you?",
        }

    @app.get("/api/privacy")
    def privacy_plate(session: Session = Depends(require_session)):
        counts = runtime.store.privacy_counts()
        return {**counts, "egress_bytes": None, "last_backup_at": None}

    @app.get("/api/voices")
    def voices(session: Session = Depends(require_session)):
        return {"voices": available_voices(), "pitch_supported": False, "preview_supported": False,
                "voice_loop": bool(voice_engine_ref), "voice_ready": voice_state["ready"],
                "voice_error": voice_state["error"]}

    @app.post("/api/conversation/turn")
    def conversation_turn(
        body: ConversationTurn,
        session: Session = Depends(require_csrf),
        _: None = Depends(require_dev_tools),
    ):
        reply = generate_reply(
            body.text, runtime.store.recent_turns(body.fixture_id), llm_settings, llm_call,
        )
        delivered = reply.text
        turn_id = runtime.store.record_turn(body.fixture_id, body.text, reply.risk_level, delivered)
        return {
            "turn_id": turn_id,
            "synthetic": True,
            "risk_level": reply.risk_level,
            "assistant_delivered_text": delivered,
            "asks_clarifying_question": reply.asks_clarifying_question,
            "reply_source": reply.source,
            "model_called": reply.model_called,
            "policy_version": POLICY_VERSION,
            "outside_contact_attempted": False,
            "resource_actions": [],
        }

    @app.get("/api/conversation/ledger")
    def conversation_ledger(
        session: Session = Depends(require_shelf_unlocked),
        _: None = Depends(require_dev_tools),
    ):
        return {"synthetic": True, "turns": runtime.store.ledger()}

    @app.get("/api/melt")
    def melt_state(session: Session = Depends(require_session)):
        return runtime.store.melt_state()

    @app.post("/api/melt/schedule")
    def schedule_melt(session: Session = Depends(require_csrf)):
        if session.melt_authorized_until <= time.time():
            raise HTTPException(status_code=403, detail="melt_reauthentication_required")
        result = runtime.store.schedule_melt(time.time() + (2 * 24 * 60 * 60))
        session.melt_authorized_until = 0
        if result is None:
            raise HTTPException(status_code=409, detail="melt_already_scheduled")
        return {**result, "synthetic": True}

    @app.delete("/api/melt/schedule")
    def cancel_melt(session: Session = Depends(require_csrf)):
        result = runtime.store.cancel_melt()
        if result is None:
            raise HTTPException(status_code=409, detail="melt_execution_started")
        return result

    @app.get("/api/deletion-log")
    def deletion_log(session: Session = Depends(require_session)):
        return {"synthetic": True, "entries": runtime.store.deletion_log()}

    @app.post("/dev/melt/advance", dependencies=[Depends(require_dev_tools)])
    def dev_advance_melt(session: Session = Depends(require_csrf)):
        if not runtime.store.advance_melt():
            raise HTTPException(status_code=409, detail="no_scheduled_melt")
        return {"advanced": True, "synthetic": True}

    @app.get("/dev/orb", dependencies=[Depends(require_dev_tools)])
    def dev_orb():
        return FileResponse(Path(__file__).resolve().parent.parent / "dev_ui" / "orb.html")

    @app.get("/dev/orb-fixtures", dependencies=[Depends(require_dev_tools)])
    def dev_orb_fixtures():
        return FileResponse(
            Path(__file__).resolve().parent.parent / "dev_ui" / "synthetic-replays.json",
            media_type="application/json",
        )

    @app.websocket("/ws/voice")
    async def voice_socket(ws: WebSocket):
        # The HTTP middleware does not see WebSockets, so Host, Origin and the session are checked here.
        host = ws.headers.get("host", "")
        origin = ws.headers.get("origin", "")
        origin_host = origin.split("://", 1)[-1].rstrip("/")
        if parse_host(host) not in ALLOWED_HOSTS or origin_host != host.strip().lower():
            await ws.accept()          # accept first so the browser receives the close code, not a bare 403
            await ws.close(code=4403)
            return
        now = time.time()
        with runtime.lock:
            session = runtime.sessions.get(ws.cookies.get(SESSION_COOKIE, ""))
            if not session or session.expires_at <= now:
                session = None
            else:
                session.expires_at = now + SESSION_TTL_SECONDS
        await ws.accept()
        if session is None:
            await ws.close(code=4401)
            return
        if not voice_engine_ref:
            await ws.send_json({"type": "degraded", "v": 1, "ts": time.monotonic(),
                                "component": "voice", "reason": "speech models not installed"})
            await ws.close(code=4503)
            return
        # The page opens the microphone only after this message.
        await ws.send_json({"type": "voice.ready", "v": 1, "ts": time.monotonic()})

        def current_voice():
            try:
                return runtime.store.workshop(include_memory_text=False)["settings"].get("voice", {}).get("id")
            except Exception:
                return None

        voice = VoiceSession(
            engine=voice_engine_ref[0], llm_settings=llm_settings, llm_call=llm_call,
            voice_id=current_voice, send_json=ws.send_json, send_bytes=ws.send_bytes, executor=voice_executor,
            memory=MemoryKeeper(runtime.store, llm_settings, llm_call) if llm_settings is not None else None,
            shelf_unlocked=lambda: session.shelf_unlocked_until > time.time(),
            session_tag="c-" + secrets.token_hex(4),
        )
        try:
            while True:
                message = await ws.receive()
                if message["type"] == "websocket.disconnect":
                    break
                if message.get("bytes") is not None:
                    with runtime.lock:   # a logged-out or expired session must stop the microphone
                        alive = runtime.sessions.get(ws.cookies.get(SESSION_COOKIE, "")) is session and session.expires_at > time.time()
                    if not alive:
                        await ws.close(code=4401)
                        break
                    await voice.on_audio(message["bytes"])
                elif message.get("text") is not None:
                    try:
                        control = json.loads(message["text"])
                    except ValueError:
                        continue
                    if isinstance(control, dict):
                        await voice.on_control(control)
        except Exception:
            pass
        finally:
            await voice.close()
            await voice.flush_memory()

    @app.get("/{path:path}", include_in_schema=False)
    def serve_ui(path: str):
        root = resolve_ui_root(data_root, bundled_root).resolve()
        relative = path.strip("/") or "index.html"
        target = (root / relative).resolve()
        if target.is_dir():
            target = target / "index.html"
        if not target.is_relative_to(root) or not target.is_file():
            raise HTTPException(status_code=404, detail="not_found")
        media_type = mimetypes.guess_type(target.name)[0]
        if target.suffix == ".js":
            media_type = "text/javascript"
        response = FileResponse(target, media_type=media_type)
        # Look-layer updates must show up on the next load.
        response.headers["Cache-Control"] = "no-cache"
        return response

    return app

