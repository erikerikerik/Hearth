"""Prints the first raw stream lines of one request, to see exactly what the model server emits."""
import json, sys, urllib.request
base = json.load(open(__file__.rsplit("/bench/", 1)[0] + "/config/models.json"))["endpoint"]
model = sys.argv[1] if len(sys.argv) > 1 else "default_model"
for thinking in (False, True):
    body = json.dumps({"model": model, "stream": True, "max_tokens": 40,
                       "messages": [{"role": "user", "content": "Say hello in five words."}],
                       "chat_template_kwargs": {"enable_thinking": thinking}}).encode()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    print("== enable_thinking =", thinking)
    with opener.open(urllib.request.Request(base + "/chat/completions", body, {"Content-Type": "application/json"}), timeout=60) as r:
        for n, line in enumerate(r):
            if n >= 8: break
            print(line.decode().strip()[:240])
