#!/usr/bin/env python3
"""Download companion models on demand: pinned revisions, every file size-checked and hash-verified.

This is the ONLY component of Hearth that is allowed to use the network, and it is a separate
short-lived process the user explicitly consents to (--accept). The running companion makes no
network calls; it only reads the folders this tool finished verifying.

Manifest (models/manifest.json, schema 2, written by scripts/pin_models.py):
  one entry per model snapshot = a Hugging Face repo at one exact 40-hex commit, plus the list of
  files to fetch, each with its size and either a sha256 (large files) or a git blob sha1 (small
  files). An entry without a real revision or without files is unpinned and is never fetched.

Layout under <data-dir>/models/:
  snapshots/<org>--<name>--<revision>/          a complete, verified snapshot (renamed into place
                                                only after every file passed its hash). The folder
                                                name keeps the repo name because mlx-audio infers
                                                the architecture (e.g. Kokoro) from it.
  snapshots/<org>--<name>--<revision>.partial/  in-progress download; resumed on the next run
  installed.json                               which snapshot each role (llm, stt, tts) uses
  progress.json                                live progress for the UI and the launcher
Models are never touched by app or look updates.
"""

import argparse
import contextlib
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
from pathlib import Path, PurePosixPath

HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
REPO = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*$")
ROLES = ("llm", "stt", "tts")
DISK_MARGIN = 2 << 30          # keep 2 GiB free after downloading
LARGE_RAM_GB = 48              # same rule as scripts/install_models.sh: only big machines get the large tier
CHUNK = 1 << 20


class ModelError(Exception):
    pass


# ---------------------------------------------------------------- machine

def total_ram_gb() -> float:
    try:
        if sys.platform == "darwin":
            return int(subprocess.check_output(["sysctl", "-n", "hw.memsize"]).strip()) / 2**30
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2**30
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0.0


# ---------------------------------------------------------------- manifest

def _safe_path(path: str) -> bool:
    parts = PurePosixPath(path).parts
    return bool(parts) and not path.startswith("/") and "\\" not in path and \
        all(p not in ("", ".", "..") and not p.startswith(".") for p in parts)


def load_manifest(path: Path) -> dict:
    data = json.loads(Path(path).read_text())
    if data.get("schema") != 2 or not isinstance(data.get("snapshots"), list):
        raise ModelError("Unsupported model manifest (expected schema 2 with snapshots).")
    seen = set()
    for snap in data["snapshots"]:
        for key in ("id", "role", "repo", "revision", "min_ram_gb", "files"):
            if key not in snap:
                raise ModelError("Manifest entry missing %r: %s" % (key, snap.get("id")))
        if snap["id"] in seen:
            raise ModelError("Duplicate manifest id: %s" % snap["id"])
        seen.add(snap["id"])
        if snap["role"] not in ROLES:
            raise ModelError("Unknown role %r in %s" % (snap["role"], snap["id"]))
        if not REPO.match(str(snap["repo"])):
            raise ModelError("Unsafe repo name in manifest: %s" % snap["repo"])
        for item in snap["files"]:
            if not _safe_path(str(item.get("path", ""))):
                raise ModelError("Unsafe file path in manifest: %s" % item.get("path"))
            if int(item.get("size", -1)) < 0:
                raise ModelError("Bad size for %s" % item.get("path"))
            sha256 = str(item.get("sha256", "")).lower()
            sha1 = str(item.get("git_sha1", "")).lower()
            if bool(HEX64.match(sha256)) == bool(HEX40.match(sha1)):
                raise ModelError("%s needs exactly one of sha256 or git_sha1." % item.get("path"))
    return data


def is_pinned(snap: dict) -> bool:
    return bool(HEX40.match(str(snap.get("revision", "")).lower())) and bool(snap.get("files"))


def choose(manifest: dict, role: str, ram_gb: float, profile: str = "") -> dict:
    pinned = [s for s in manifest["snapshots"] if s["role"] == role and is_pinned(s)]
    if role == "llm" and profile:
        match = [s for s in pinned if s.get("profile") == profile]
        if not match:
            raise ModelError("No pinned language model for profile %r." % profile)
        return match[0]
    fits = [s for s in pinned if s["min_ram_gb"] <= ram_gb]
    if not fits:
        raise ModelError("No pinned %r model fits %.0f GB of RAM (or none is configured yet)." % (role, ram_gb))
    if role == "llm" and ram_gb < LARGE_RAM_GB:
        default = next((s for s in pinned if s.get("profile") == manifest.get("default_profile")), None)
        if default is not None:
            capped = [s for s in fits if s["min_ram_gb"] <= default["min_ram_gb"]]
            fits = capped or fits
    return max(fits, key=lambda s: s["min_ram_gb"])


def selection(manifest: dict, ram_gb: float, profile: str = "", roles=ROLES) -> list:
    configured = {s["role"] for s in manifest["snapshots"] if is_pinned(s)}
    return [choose(manifest, role, ram_gb, profile) for role in roles if role in configured]


def snapshot_dir(models_dir: Path, snap: dict) -> Path:
    return Path(models_dir) / "snapshots" / ("%s--%s" % (snap["repo"].replace("/", "--"), snap["revision"]))


def _staging(models_dir: Path, snap: dict) -> Path:
    final = snapshot_dir(models_dir, snap)
    return final.with_name(final.name + ".partial")


def snapshot_bytes(snap: dict) -> int:
    return sum(int(f["size"]) for f in snap["files"])


# ---------------------------------------------------------------- hashing

def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_blob_sha1(path: Path) -> str:
    digest = hashlib.sha1()
    digest.update(b"blob %d\0" % Path(path).stat().st_size)
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_matches(path: Path, item: dict) -> bool:
    if not path.is_file() or path.stat().st_size != int(item["size"]):
        return False
    if item.get("sha256"):
        return sha256_file(path) == item["sha256"].lower()
    return git_blob_sha1(path) == item["git_sha1"].lower()


# ---------------------------------------------------------------- network (this process only)

def _check_url(url: str):
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme == "https":
        return
    if parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost"):
        return
    raise ModelError("Model URLs must be https.")


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    """Follow the hub's redirect to its download CDN, but never downgrade to plain http."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_SafeRedirect)


def file_url(hub: str, snap: dict, path: str) -> str:
    return "%s/%s/resolve/%s/%s" % (hub.rstrip("/"), snap["repo"], snap["revision"], urllib.parse.quote(path))


def _progress(models_dir: Path, **fields):
    tmp = models_dir / ".progress.tmp"
    tmp.write_text(json.dumps(dict(fields, updated=time.time())))
    os.replace(tmp, models_dir / "progress.json")


def download_file(url: str, item: dict, dest: Path, on_bytes=None) -> Path:
    """Fetch one file to dest (resuming dest + '.part'), then verify size and hash."""
    _check_url(url)
    if file_matches(dest, item):
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    have = part.stat().st_size if part.exists() else 0
    if have > int(item["size"]):
        part.unlink()
        have = 0
    request = urllib.request.Request(url, headers={"User-Agent": "Hearth-model-manager"})
    if have:
        request.add_header("Range", "bytes=%d-" % have)
    if have < int(item["size"]) or int(item["size"]) == 0:
        with _OPENER.open(request, timeout=60) as response:
            resumed = bool(have) and response.status == 206
            if have and not resumed:
                have = 0                       # server ignored Range; restart cleanly
            with open(part, "ab" if resumed else "wb") as out:
                while True:
                    chunk = response.read(CHUNK)
                    if not chunk:
                        break
                    out.write(chunk)
                    have += len(chunk)
                    if on_bytes:
                        on_bytes(len(chunk))
    if not file_matches(part, item):
        part.unlink(missing_ok=True)
        raise ModelError("Checksum mismatch for %s; partial file discarded." % item["path"])
    os.replace(part, dest)
    return dest


def partial_bytes(models_dir: Path, snap: dict) -> int:
    """Bytes already on disk for an unfinished snapshot (completed files plus .part files)."""
    staging = _staging(models_dir, snap)
    total = 0
    for item in snap["files"]:
        target = staging / item["path"]
        for candidate in (target, target.with_name(target.name + ".part")):
            if candidate.is_file():
                total += min(candidate.stat().st_size, int(item["size"]))
                break
    return total


def install_snapshot(hub: str, snap: dict, models_dir: Path, report=None) -> Path:
    """Download every file of one snapshot into a staging folder, then rename it into place."""
    if not is_pinned(snap):
        raise ModelError("%s is not pinned to a revision; refusing to download." % snap["id"])
    final = snapshot_dir(models_dir, snap)
    if final.is_dir():
        return final
    staging = _staging(models_dir, snap)
    staging.mkdir(parents=True, exist_ok=True)
    for item in snap["files"]:
        download_file(file_url(hub, snap, item["path"]), item, staging / item["path"], report)
    os.replace(staging, final)
    return final


# ---------------------------------------------------------------- installed state

def read_installed(models_dir: Path) -> dict:
    path = Path(models_dir) / "installed.json"
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) and data.get("schema") == 2 else {"schema": 2, "roles": {}}
    except (OSError, ValueError):
        return {"schema": 2, "roles": {}}


def _write_installed(models_dir: Path, data: dict):
    tmp = Path(models_dir) / ".installed.tmp"
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, Path(models_dir) / "installed.json")


def record(models_dir: Path, snap: dict):
    data = read_installed(models_dir)
    data["roles"][snap["role"]] = {
        "id": snap["id"], "repo": snap["repo"], "revision": snap["revision"],
        "profile": snap.get("profile"),
        "path": str(snapshot_dir(models_dir, snap).relative_to(models_dir)),
    }
    _write_installed(models_dir, data)


def installed_path(models_dir: Path, role: str):
    """Absolute folder for a role, only if it is a complete snapshot under models_dir; else None."""
    entry = read_installed(models_dir).get("roles", {}).get(role)
    if not entry:
        return None
    root = (Path(models_dir) / "snapshots").resolve()
    try:
        target = (Path(models_dir) / entry["path"]).resolve(strict=True)
    except (OSError, KeyError, TypeError):
        return None
    if root not in target.parents or not target.is_dir() or target.name.endswith(".partial"):
        return None
    return target


def prune(models_dir: Path) -> list:
    """Remove snapshot folders (finished or partial) that no role uses any more."""
    keep = {installed_path(models_dir, role) for role in ROLES} - {None}
    removed = []
    base = Path(models_dir) / "snapshots"
    if not base.is_dir():
        return removed
    for entry in base.iterdir():
        if entry.resolve() not in keep:
            shutil.rmtree(entry) if entry.is_dir() and not entry.is_symlink() else entry.unlink()
            removed.append(str(entry.relative_to(models_dir)))
    return removed


# ---------------------------------------------------------------- commands

@contextlib.contextmanager
def _exclusive(models_dir: Path):
    import fcntl
    models_dir.mkdir(parents=True, exist_ok=True)
    with open(models_dir / ".lock", "w") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ModelError("Another model download is already running.") from None
        yield


def download_running(models_dir: Path) -> bool:
    """True while another process holds the download lock."""
    import fcntl
    lock = Path(models_dir) / ".lock"
    if not lock.exists():
        return False
    with open(lock, "a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(handle, fcntl.LOCK_UN)
    return False


def progress_text(models_dir: Path) -> str:
    try:
        data = json.loads((Path(models_dir) / "progress.json").read_text())
        return "%d%%" % (100 * data["bytes"] // max(1, data["total"]))
    except (OSError, ValueError, KeyError, TypeError):
        return "starting"


def pending_bytes(manifest_path: Path, data_dir: Path, ram_gb: float = 0.0, profile: str = "") -> int:
    """Bytes still to download for this machine's selection (0 = nothing to do). Never hashes."""
    manifest = load_manifest(manifest_path)
    models_dir = Path(data_dir) / "models"
    total = 0
    for snap in selection(manifest, ram_gb or total_ram_gb(), profile):
        if not snapshot_dir(models_dir, snap).is_dir():
            total += snapshot_bytes(snap) - partial_bytes(models_dir, snap)
    return total


def ensure(manifest_path: Path, data_dir: Path, accept: bool, ram_gb: float = 0.0, profile: str = "",
           roles=ROLES) -> list:
    if not accept:
        raise ModelError("Downloading requires explicit consent (--accept).")
    manifest = load_manifest(manifest_path)
    chosen = selection(manifest, ram_gb or total_ram_gb(), profile, roles)
    if not chosen:
        raise ModelError("No models are pinned in the manifest yet; nothing to download.")
    models_dir = Path(data_dir) / "models"
    with _exclusive(models_dir):
        os.chmod(models_dir, 0o700)
        todo = [s for s in chosen if not snapshot_dir(models_dir, s).is_dir()]
        need = sum(snapshot_bytes(s) - partial_bytes(models_dir, s) for s in todo)
        if need and shutil.disk_usage(models_dir).free < need + DISK_MARGIN:
            raise ModelError("Not enough free disk space: %.1f GB more is needed." % (need / 1e9))
        total = sum(snapshot_bytes(s) for s in todo)
        state = {"done": sum(partial_bytes(models_dir, s) for s in todo), "last": 0.0}

        def report(n, snap_id=""):
            state["done"] += n
            if time.time() - state["last"] > 1:
                _progress(models_dir, state="downloading", bytes=state["done"], total=total, id=state.get("id"))
                state["last"] = time.time()

        try:
            for snap in chosen:
                state["id"] = snap["id"]
                install_snapshot(manifest.get("hub", "https://huggingface.co"), snap, models_dir, report)
                record(models_dir, snap)
        except Exception as error:
            _progress(models_dir, state="error", bytes=state["done"], total=total, error=str(error)[:200])
            raise
        prune(models_dir)
        _progress(models_dir, state="done", bytes=total, total=total)
    return [s["id"] for s in chosen]


def verify(manifest_path: Path, data_dir: Path) -> list:
    """Re-hash every installed file against the manifest. Returns a list of problems (empty = good)."""
    manifest = load_manifest(manifest_path)
    models_dir = Path(data_dir) / "models"
    problems = []
    by_id = {s["id"]: s for s in manifest["snapshots"]}
    for role, entry in read_installed(models_dir).get("roles", {}).items():
        snap = by_id.get(entry.get("id"))
        folder = installed_path(models_dir, role)
        if snap is None or folder is None or snap["revision"] != entry.get("revision"):
            problems.append("%s: installed snapshot is missing or not in this manifest" % role)
            continue
        for item in snap["files"]:
            if not file_matches(folder / item["path"], item):
                problems.append("%s: %s does not match" % (role, item["path"]))
    return problems


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-dir", default=os.environ.get("HEARTH_DATA_DIR"), required=not os.environ.get("HEARTH_DATA_DIR"))
    parser.add_argument("--manifest", default=str(Path(__file__).resolve().parent.parent / "models" / "manifest.json"))
    parser.add_argument("--ram-gb", type=float, default=0.0)
    parser.add_argument("--profile", default=os.environ.get("HEARTH_PROFILE", ""), help="fast, balanced or large (default: by RAM)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    sub.add_parser("status")
    sub.add_parser("pending", help="print bytes still to download (prints nothing when up to date)")
    path_cmd = sub.add_parser("path", help="print the verified local folder for a role (nothing if absent)")
    path_cmd.add_argument("role", choices=ROLES)
    ens = sub.add_parser("ensure")
    ens.add_argument("--role", action="append", choices=ROLES)
    ens.add_argument("--accept", action="store_true", help="I consent to downloading these files")
    sub.add_parser("downloading", help="exit 0 and print progress if a download is running, else exit 1")
    sub.add_parser("verify", help="re-hash installed models (slow)")
    sub.add_parser("prune", help="delete snapshots that no role uses")
    args = parser.parse_args(argv)
    data_dir = Path(args.data_dir)
    models_dir = data_dir / "models"
    try:
        if args.cmd == "list":
            manifest = load_manifest(Path(args.manifest))
            for snap in manifest["snapshots"]:
                print("%-4s %-12s %-48s %6.2f GB  min RAM %-3s %s" % (
                    snap["role"], snap["id"], snap["repo"], snapshot_bytes(snap) / 1e9, snap["min_ram_gb"],
                    snap["revision"][:12] if is_pinned(snap) else "UNPINNED (will not download)"))
        elif args.cmd == "pending":
            remaining = pending_bytes(Path(args.manifest), data_dir, args.ram_gb, args.profile)
            if remaining > 0:
                print(remaining)
        elif args.cmd == "path":
            found = installed_path(models_dir, args.role)
            if found:
                print(found)
        elif args.cmd == "status":
            print(json.dumps(read_installed(models_dir), indent=2))
        elif args.cmd == "downloading":
            if not download_running(models_dir):
                sys.exit(1)
            print(progress_text(models_dir))
        elif args.cmd == "verify":
            problems = verify(Path(args.manifest), data_dir)
            print("\n".join(problems) if problems else "All installed models match the manifest.")
            sys.exit(1 if problems else 0)
        elif args.cmd == "prune":
            print("\n".join(prune(models_dir)) or "Nothing to remove.")
        else:
            done = ensure(Path(args.manifest), data_dir, args.accept, args.ram_gb, args.profile, args.role or ROLES)
            print("Installed:", ", ".join(done))
    except (ModelError, OSError, ValueError) as error:
        print("Error:", error, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
