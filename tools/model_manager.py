#!/usr/bin/env python3
"""Download companion models on demand: resumable, size-checked, hash-verified.

This is the ONLY component of Hearth that is allowed to use the network, and it is a
separate short-lived process the user explicitly consents to (--accept). The running
companion makes no network calls. Entries whose sha256 is not a real 64-hex digest are
treated as unpinned and are refused, so nothing unverified is ever fetched.

Models live in <data-dir>/models/ and are never touched by app or look updates.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

HEX64 = re.compile(r"^[0-9a-f]{64}$")
DISK_MARGIN = 1 << 30  # keep 1 GiB free after downloading


class ModelError(Exception):
    pass


def total_ram_gb() -> float:
    try:
        if sys.platform == "darwin":
            return int(subprocess.check_output(["sysctl", "-n", "hw.memsize"]).strip()) / 2**30
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2**30
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0.0


def load_manifest(path: Path) -> list:
    models = json.loads(Path(path).read_text())["models"]
    for item in models:
        for key in ("id", "role", "filename", "url", "sha256", "size_bytes", "min_ram_gb"):
            if key not in item:
                raise ModelError("Manifest entry missing %r: %s" % (key, item.get("id")))
        if "/" in item["filename"] or item["filename"].startswith("."):
            raise ModelError("Unsafe filename in manifest: %s" % item["filename"])
    return models


def is_pinned(item: dict) -> bool:
    return bool(HEX64.match(str(item["sha256"]).lower())) and int(item["size_bytes"]) > 0


def choose(models: list, role: str, ram_gb: float) -> dict:
    fits = [m for m in models if m["role"] == role and is_pinned(m) and m["min_ram_gb"] <= ram_gb]
    if not fits:
        raise ModelError("No pinned %r model fits %.0f GB of RAM (or none is configured yet)." % (role, ram_gb))
    return max(fits, key=lambda m: m["min_ram_gb"])


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _progress(models_dir: Path, **fields):
    tmp = models_dir / ".progress.tmp"
    tmp.write_text(json.dumps(fields))
    os.replace(tmp, models_dir / "progress.json")


def _check_url(url: str):
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme == "https":
        return
    if parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost"):
        return
    raise ModelError("Model URLs must be https.")


def download(item: dict, models_dir: Path) -> Path:
    if not is_pinned(item):
        raise ModelError("%s has no pinned sha256; refusing to download." % item["id"])
    _check_url(item["url"])
    models_dir.mkdir(parents=True, exist_ok=True)
    final = models_dir / item["filename"]
    expected = str(item["sha256"]).lower()
    if final.is_file() and sha256_file(final) == expected:
        return final
    part = models_dir / (item["filename"] + ".part")
    have = part.stat().st_size if part.exists() else 0
    needed = int(item["size_bytes"]) - have
    if shutil.disk_usage(models_dir).free < needed + DISK_MARGIN:
        raise ModelError("Not enough free disk space for %s." % item["id"])
    request = urllib.request.Request(item["url"])
    if have:
        request.add_header("Range", "bytes=%d-" % have)
    with urllib.request.urlopen(request, timeout=60) as response:
        resumed = have and response.status == 206
        if have and not resumed:
            have = 0  # server ignored Range; restart cleanly
        mode = "ab" if resumed else "wb"
        last = 0.0
        with open(part, mode) as out:
            while True:
                chunk = response.read(1 << 20)
                if not chunk:
                    break
                out.write(chunk)
                have += len(chunk)
                if time.time() - last > 1:
                    _progress(models_dir, id=item["id"], bytes=have, total=int(item["size_bytes"]), state="downloading")
                    last = time.time()
    if sha256_file(part) != expected:
        part.unlink()
        raise ModelError("Checksum mismatch for %s; partial file discarded." % item["id"])
    os.replace(part, final)
    _progress(models_dir, id=item["id"], bytes=final.stat().st_size, total=int(item["size_bytes"]), state="done")
    return final


def _record(models_dir: Path, item: dict):
    path = models_dir / "installed.json"
    data = json.loads(path.read_text()) if path.exists() else {}
    data[item["role"]] = {"id": item["id"], "filename": item["filename"], "sha256": item["sha256"]}
    path.write_text(json.dumps(data, indent=2))


def ensure(manifest: Path, data_dir: Path, roles, accept: bool, ram_gb: float = 0.0) -> list:
    if not accept:
        raise ModelError("Downloading requires explicit consent (--accept).")
    models = load_manifest(manifest)
    ram = ram_gb or total_ram_gb()
    models_dir = Path(data_dir) / "models"
    done = []
    for role in roles:
        item = choose(models, role, ram)
        download(item, models_dir)
        _record(models_dir, item)
        done.append(item["id"])
    return done


def pending_bytes(manifest: Path, data_dir: Path, ram_gb: float = 0.0) -> int:
    """Bytes still to download for this machine's tier of every configured role (0 = nothing to do)."""
    models = load_manifest(manifest)
    ram = ram_gb or total_ram_gb()
    models_dir = Path(data_dir) / "models"
    total = 0
    for role in sorted({m["role"] for m in models if is_pinned(m)}):
        try:
            item = choose(models, role, ram)
        except ModelError:
            continue
        final = models_dir / item["filename"]
        if not (final.is_file() and sha256_file(final) == str(item["sha256"]).lower()):
            part = models_dir / (item["filename"] + ".part")
            total += int(item["size_bytes"]) - (part.stat().st_size if part.exists() else 0)
    return total


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-dir", default=os.environ.get("HEARTH_DATA_DIR"), required=not os.environ.get("HEARTH_DATA_DIR"))
    parser.add_argument("--manifest", default=str(Path(__file__).resolve().parent.parent / "models" / "manifest.json"))
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    sub.add_parser("status")
    sub.add_parser("pending", help="print bytes still to download (nothing if up to date)")
    ens = sub.add_parser("ensure")
    ens.add_argument("--role", action="append", help="llm, stt, tts (default: all configured roles)")
    ens.add_argument("--ram-gb", type=float, default=0.0)
    ens.add_argument("--accept", action="store_true", help="I consent to downloading these files")
    args = parser.parse_args(argv)
    try:
        if args.cmd == "list":
            for item in load_manifest(Path(args.manifest)):
                print("%-5s %-28s %6.1f GB  min RAM %-3s %s" % (
                    item["role"], item["id"], item["size_bytes"] / 1e9, item["min_ram_gb"],
                    "pinned" if is_pinned(item) else "UNPINNED (will not download)"))
        elif args.cmd == "pending":
            remaining = pending_bytes(Path(args.manifest), Path(args.data_dir))
            if remaining > 0:
                print(remaining)
        elif args.cmd == "status":
            path = Path(args.data_dir) / "models" / "installed.json"
            print(path.read_text() if path.exists() else "{}")
        else:
            roles = args.role or sorted({m["role"] for m in load_manifest(Path(args.manifest)) if is_pinned(m)})
            if not roles:
                raise ModelError("No models are pinned in the manifest yet; nothing to download.")
            print("Installed:", ", ".join(ensure(Path(args.manifest), Path(args.data_dir), roles, args.accept, args.ram_gb)))
    except (ModelError, OSError, ValueError) as error:
        print("Error:", error, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
