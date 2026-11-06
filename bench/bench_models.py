"""Benchmarks the running local model server: time to first word, speed, and saves every reply.

Run the server first (scripts/run_llm.sh), then:  python bench/bench_models.py [--runs 1]
Output: bench/results-<profile>-<timestamp>.json and .md (replies for a human to read).
Measures speed only. Whether replies are warm and safe needs a person to read the .md file.
"""
import argparse, json, platform, resource, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.llm import stream_events  # noqa: E402

ROOT = Path(__file__).resolve().parent
cfg = json.loads((ROOT.parent / "config" / "models.json").read_text())
data = json.loads((ROOT / "prompts.json").read_text())
data["system"] = (ROOT.parent / "config" / "system_prompt.txt").read_text().strip()

ap = argparse.ArgumentParser()
ap.add_argument("--endpoint", default=cfg["endpoint"])
ap.add_argument("--profile", default=(ROOT.parent / ".hearth-profile").read_text().strip() if (ROOT.parent / ".hearth-profile").exists() else cfg["default_profile"])
ap.add_argument("--model", default=None)
ap.add_argument("--runs", type=int, default=1)
ap.add_argument("--thinking", action="store_true", help="allow hidden reasoning (slower)")
a = ap.parse_args()
model = a.model or cfg["profiles"][a.profile]["mlx"]

rows = []
for run in range(a.runs):
    for index, prompt in enumerate(data["prompts"]):
        messages = [{"role": "system", "content": data["system"]}, {"role": "user", "content": prompt}]
        start = time.perf_counter(); first = None; first_any = None; pieces = []; reasoning = 0
        for kind, piece in stream_events(a.endpoint, model, messages, thinking=a.thinking):
            if first_any is None: first_any = time.perf_counter() - start
            if kind == "reasoning": reasoning += len(piece); continue
            if first is None: first = time.perf_counter() - start
            pieces.append(piece)
        total = time.perf_counter() - start
        text = "".join(pieces).strip(); words = len(text.split())
        rows.append({"i": index, "prompt": prompt, "reply": text, "ttft_s": round(first if first is not None else total, 3),
                     "first_any_token_s": round(first_any if first_any is not None else total, 3), "reasoning_chars": reasoning,
                     "total_s": round(total, 3), "words": words, "empty": not text,
                     "words_per_s": round(words / max(total - (first or 0), 1e-6), 1)})
        print("%2d  first word %.2fs  any token %.2fs  %2d words  reasoning %d chars  %s" % (index + 1, rows[-1]["ttft_s"], rows[-1]["first_any_token_s"], words, reasoning, text[:60].replace("\n", " ")))

ttfts = sorted(r["ttft_s"] for r in rows)
def pct(p): return ttfts[min(len(ttfts) - 1, int(p * len(ttfts)))]
summary = {"profile": a.profile, "model": model, "machine": platform.platform(), "n": len(rows),
           "ttft_p50_s": pct(.5), "ttft_p95_s": pct(.95),
           "under_1_5s": sum(t <= 1.5 for t in ttfts), "empty_replies": sum(r["empty"] for r in rows), "reasoning_chars_total": sum(r["reasoning_chars"] for r in rows), "peak_rss_bench_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1048576 if sys.platform == "darwin" else resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024),
           "note": "peak_rss_bench_mb is this script only. Check the server's memory in Activity Monitor (Memory tab) while it runs."}
stamp = time.strftime("%Y%m%d-%H%M%S"); stem = ROOT / ("results-%s-%s" % (a.profile, stamp))
stem.with_suffix(".json").write_text(json.dumps({"summary": summary, "rows": rows}, indent=1))
md = ["# %s — read these replies\n" % model, "p50 first word %.2fs, p95 %.2fs, %d of %d under 1.5 s\n" % (summary["ttft_p50_s"], summary["ttft_p95_s"], summary["under_1_5s"], len(rows))]
md += ["\n**%d. %s**\n> %s\n" % (r["i"] + 1, r["prompt"], r["reply"].replace("\n", "\n> ")) for r in rows]
stem.with_suffix(".md").write_text("".join(md))
print(json.dumps(summary, indent=1)); print("saved", stem.with_suffix(".md"))
