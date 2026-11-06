"""Real-browser check of the hands-free voice loop with a FAKE microphone and a FAKE speech engine.

Proves the browser plumbing (permissions header, CSP for the WebSocket, AudioWorklet, resampling, playback,
indicator, curtain pause). It does NOT prove that the real microphone, Whisper or Kokoro work: run
the checklist in docs/VOICE_LOOP.md on the Mac for that.

Run:  python3 tests/voice_browser_check.py          (HEARTH_BROWSER=/path/to/chrome-or-brave to override)
"""
import json, math, os, struct, sys, tempfile, threading, time, wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import uvicorn
from argon2 import PasswordHasher
from playwright.sync_api import sync_playwright

from app.main import create_app

PASSWORD, PORT = "synthetic-voice-check", 4179
ORIGIN = f"http://127.0.0.1:{PORT}"


class FakeEngine:
    sample_rate = 24000
    def transcribe(self, pcm): return "I had a long day at work."
    def synthesize(self, text, voice_id):
        n = int(24000 * 0.6)
        return b"".join(struct.pack("<h", int(5000 * math.sin(2 * math.pi * 440 * i / 24000))) for i in range(n))


def fake_llm(base_url, model, messages, **_options):
    # Keep the synthetic thinking state observable to the browser poller.
    time.sleep(0.2)
    yield "That sounds heavy. "
    yield "What part of it stayed with you?"


def mic_wav(path):
    rate = 48000
    frames = bytearray()
    frames += b"\x00\x00" * int(rate * 0.6)
    frames += b"".join(struct.pack("<h", int(9000 * math.sin(2 * math.pi * 220 * i / rate))) for i in range(int(rate * 1.2)))
    frames += b"\x00\x00" * int(rate * 6)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate); w.writeframes(bytes(frames))


tmp = tempfile.TemporaryDirectory()
app = create_app(
    password_hash=PasswordHasher().hash(PASSWORD), cookie_secure=False, db_path=Path(tmp.name) / "h.sqlite3",
    dev_tools=False, data_dir=Path(tmp.name), llm_enabled=True, llm_stream=fake_llm, voice_engine=FakeEngine(),
)
# llm_enabled=True loads config/models.json for settings only; the model call is the fake above.
server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning"))
server_thread = threading.Thread(target=server.run, daemon=True)
server_thread.start()
for _ in range(100):
    if server.started: break
    time.sleep(0.1)
wav = Path(tmp.name) / "mic.wav"; mic_wav(wav)

results, failures = [], []
def check(name, ok, detail=""):
    results.append((name, ok, detail)); print(("PASS " if ok else "FAIL ") + name + (" - " + detail if detail else ""))
    if not ok: failures.append(name)

exe = os.environ.get("HEARTH_BROWSER") or None
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, executable_path=exe, args=[
        "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
        f"--use-file-for-fake-audio-capture={wav}", "--autoplay-policy=no-user-gesture-required"])
    context = browser.new_context(viewport={"width": 1280, "height": 800})
    page = context.new_page()
    console, errors = [], []
    page.on("console", lambda m: console.append((m.type, m.text)))
    page.on("pageerror", lambda e: errors.append(str(e)))
    login = context.request.post(f"{ORIGIN}/api/auth/login", data=json.dumps({"password": PASSWORD}), headers={"content-type": "application/json"})
    check("login", login.ok)
    # Record every caption the page shows (a fast fake model replaces the user's words within milliseconds).
    page.add_init_script("""window.__caps=[];document.addEventListener('DOMContentLoaded',()=>{const el=document.querySelector('#cap');if(!el)return;
      new MutationObserver(()=>window.__caps.push(el.textContent)).observe(el,{childList:true,subtree:true,characterData:true})})""")
    page.goto(ORIGIN, wait_until="domcontentloaded")

    def wait(expr, timeout=15):
        # Poll through CDP evaluate; wait_for_function uses eval(), which the page's CSP correctly refuses.
        end = time.time() + timeout
        while time.time() < end:
            if page.evaluate(expr): return True
            time.sleep(0.05)
        raise TimeoutError(expr)

    def state(): return page.evaluate("document.documentElement.dataset.micState")
    def text(): return page.evaluate("document.getElementById('micIndicator')?.textContent")
    def speaker(): return page.evaluate("window.__hearth && window.__hearth.S.speaker")

    wait("document.documentElement.dataset.micState === 'listening'", 15)
    check("indicator says listening with a live mic", "listening" in text(), text())
    check("microphone track is live in the page", page.evaluate("navigator.mediaDevices.enumerateDevices().then(d=>d.length>0)"))

    seen, captions = set(), ""
    deadline = time.time() + 25
    while time.time() < deadline and not ({"user", "think", "assistant"} <= seen and "stayed with you" in captions):
        seen.add(speaker()); captions += page.evaluate("document.body.innerText"); time.sleep(0.05)
    check("orb state followed user -> think -> assistant", {"user", "think", "assistant"} <= seen, str(sorted(seen)))
    wait("window.__hearth.S.speaker === 'idle'", 15)
    check("returned to idle after playback ended", True)
    caption = captions + " ".join(page.evaluate("window.__caps"))
    check("assistant words reached the page", "That sounds heavy" in caption)
    check("user words reached the page", "long day at work" in caption)

    csp = [t for k, t in console if "Content Security Policy" in t or "Refused" in t]
    check("no CSP violations", not csp, "; ".join(csp)[:300])
    check("no page errors", not errors, "; ".join(errors)[:300])

    wait("document.documentElement.dataset.micState === 'listening'", 15)
    page.evaluate("window.hearthRealtime.send({type:'ui.mic', paused:true})")
    wait("document.documentElement.dataset.micState === 'paused'", 5)
    live = page.evaluate("""async () => { const c = document.querySelectorAll('audio,video').length; return c }""")
    check("indicator says off when paused", "off" in text(), text())
    ack = page.evaluate("document.body.dataset.micPausedAck")
    check("server acknowledged pause", ack == "true", str(ack))
    page.evaluate("window.hearthRealtime.send({type:'ui.mic', paused:false})")
    wait("document.documentElement.dataset.micState === 'listening'", 10)
    check("resumes listening after the curtain closes", True)

    # Logged-out page: must say what it waits for, must NOT open the microphone, then connect right after login.
    fresh = browser.new_context(viewport={"width": 1280, "height": 800})
    anon = fresh.new_page()
    anon.add_init_script("""window.__gum=0;const g=navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
      navigator.mediaDevices.getUserMedia=(...a)=>{window.__gum++;return g(...a)}""")
    anon.goto(ORIGIN, wait_until="domcontentloaded")
    end = time.time() + 15
    while time.time() < end and anon.evaluate("document.documentElement.dataset.micState") != "needsLogin": time.sleep(0.1)
    check("logged out: indicator says voice waits for the password", anon.evaluate("document.documentElement.dataset.micState") == "needsLogin", anon.evaluate("document.getElementById('micIndicator').textContent"))
    time.sleep(1.5)
    check("logged out: microphone was never opened", anon.evaluate("window.__gum") == 0)
    anon.evaluate("""fetch('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({password:'%s'})}).then(()=>document.dispatchEvent(new CustomEvent('hearth:authenticated')))""" % PASSWORD)
    end = time.time() + 15
    while time.time() < end and anon.evaluate("document.documentElement.dataset.micState") != "listening": time.sleep(0.1)
    check("after login the page connects and listens without a reload", anon.evaluate("document.documentElement.dataset.micState") == "listening")
    check("microphone opened exactly once, after login", anon.evaluate("window.__gum") == 1, str(anon.evaluate("window.__gum")))
    fresh.close()

    page2 = context.new_page()
    page2.goto(ORIGIN + "/?x=1", wait_until="domcontentloaded")
    headers = context.request.get(ORIGIN + "/healthz").headers
    check("permissions policy allows the microphone for this origin", "microphone=(self)" in headers.get("permissions-policy", ""))
    check("csp has no unsafe-inline for scripts", "unsafe-inline" not in headers["content-security-policy"].split("script-src")[1].split(";")[0])
    browser.close()

server.should_exit = True
server_thread.join(timeout=5)
tmp.cleanup()
print("\n%d checks, %d failed" % (len(results), len(failures)))
sys.exit(1 if failures else 0)
