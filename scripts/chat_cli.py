"""Type to the companion in Terminal. SYNTHETIC TESTING ONLY: do not type real personal details.
Nothing is saved. Needs scripts/run_llm.sh running in another window.
Run:  .venv-ai/bin/python scripts/chat_cli.py
"""
import sys, time, urllib.request
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.companion import load_llm_settings, stream_reply

settings = load_llm_settings()
print("Hearth test chat | model: %s | type 'quit' to leave" % settings.model)
print("Synthetic testing only. Safety wording is unreviewed. Nothing is saved.\n")
def server_up():
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        opener.open(settings.base_url.rstrip("/") + "/models", timeout=3).read()
        return True
    except Exception:
        return False


if not server_up():
    print("!! The model server is not running. Replies will be the fixed fallback only.")
    print("!! Open another Terminal window and run:  bash scripts/run_llm.sh   (leave it open), then restart this.\n")
history = []
while True:
    try:
        text = input("you > ").strip()
    except (EOFError, KeyboardInterrupt):
        break
    if text.lower() in ("quit", "exit", "bye"):
        break
    if not text:
        continue
    start = time.perf_counter(); first = None; said = []; source = "?"
    for source, sentence in stream_reply(text, history, settings):
        if first is None:
            first = time.perf_counter() - start
            print("hearth > ", end="", flush=True)
        print(sentence + " ", end="", flush=True)
        said.append(sentence)
    if source == "fallback" and not server_up():
        print("\n    !! model server unreachable, so this was the fixed fallback")
    print("\n    [%s, first sentence %.1fs, whole reply %.1fs]\n" % (source, first or 0, time.perf_counter() - start))
    history.append({"user": text, "assistant": " ".join(said)})
