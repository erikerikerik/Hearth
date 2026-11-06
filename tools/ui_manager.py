#!/usr/bin/env python3
"""Install, switch and roll back the Hearth *look layer* without touching user data.

Layout under <data-dir>/ui/:
    versions/<name>-<version>/   unpacked look bundles (each has ui.json + index.html)
    current  -> versions/...     what the server serves (absent = bundled default)
    previous -> versions/...     one step of rollback

This tool never reads or writes the databases, auth file or models. A bundle is a zip
whose root contains ui.json {"name","version","contract"} and index.html.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

CONTRACT_MAJOR = 1
MAX_UNPACKED = 200 * 1024 * 1024
SAFE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class UiError(Exception):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fetch(source: str, expected_sha: str, workdir: Path) -> Path:
    parsed = urllib.parse.urlparse(source)
    if parsed.scheme in ("http", "https"):
        loopback = parsed.hostname in ("127.0.0.1", "localhost")
        if parsed.scheme != "https" and not loopback:
            raise UiError("Remote bundles must use https.")
        if not expected_sha:
            raise UiError("A --sha256 is required for downloaded bundles.")
        target = workdir / "bundle.zip"
        with urllib.request.urlopen(source, timeout=60) as response, open(target, "wb") as out:
            shutil.copyfileobj(response, out)
    else:
        target = Path(source)
        if not target.is_file():
            raise UiError("Bundle not found: %s" % source)
    if expected_sha and sha256_file(target) != expected_sha.lower():
        raise UiError("Checksum mismatch; bundle rejected.")
    return target


def _safe_extract(archive: Path, dest: Path):
    total = 0
    with zipfile.ZipFile(archive) as zf:
        for info in zf.infolist():
            name = info.filename
            parts = Path(name).parts
            if name.startswith(("/", "\\")) or ".." in parts or (parts and ":" in parts[0]):
                raise UiError("Unsafe path in bundle: %s" % name)
            if (info.external_attr >> 28) == 0xA:  # symlink
                raise UiError("Symlinks are not allowed in bundles.")
            total += info.file_size
            if total > MAX_UNPACKED:
                raise UiError("Bundle is too large.")
        zf.extractall(dest)


def _read_manifest(root: Path) -> dict:
    try:
        manifest = json.loads((root / "ui.json").read_text())
        name, version = str(manifest["name"]), str(manifest["version"])
        major = int(str(manifest["contract"]).split(".")[0])
    except (OSError, ValueError, KeyError):
        raise UiError("Bundle is missing a valid ui.json.")
    if not SAFE.match(name) or not SAFE.match(version):
        raise UiError("Bundle name/version contain unsupported characters.")
    if major != CONTRACT_MAJOR:
        raise UiError("Bundle targets UI contract %d; this app supports %d." % (major, CONTRACT_MAJOR))
    if not (root / "index.html").is_file():
        raise UiError("Bundle has no index.html.")
    return manifest


def _point(link: Path, target: Path):
    tmp = link.with_name(link.name + ".tmp")
    if tmp.is_symlink() or tmp.exists():
        tmp.unlink()
    # macOS exposes /var through /private/var. Mixing a resolved target with an
    # unresolved link parent can otherwise create /private/private/... links.
    base = link.parent.resolve()
    os.symlink(os.path.relpath(target.resolve(), base), tmp)
    os.replace(tmp, link)  # atomic switch


def _target(link: Path):
    return link.resolve() if link.is_symlink() else None


def install(data_dir: Path, source: str, sha256: str = "", activate: bool = True) -> str:
    ui = Path(data_dir) / "ui"
    versions = ui / "versions"
    versions.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=str(ui)) as tmp:
        work = Path(tmp)
        archive = _fetch(source, sha256, work)
        staging = work / "unpacked"
        staging.mkdir()
        _safe_extract(archive, staging)
        manifest = _read_manifest(staging)
        dest = versions / ("%s-%s" % (manifest["name"], manifest["version"]))
        if dest.exists():
            shutil.rmtree(dest)
        shutil.move(str(staging), str(dest))
    if activate:
        current = ui / "current"
        old = _target(current)
        if old and old != dest.resolve():
            _point(ui / "previous", old)
        _point(current, dest)
    return dest.name


def rollback(data_dir: Path) -> str:
    ui = Path(data_dir) / "ui"
    previous = _target(ui / "previous")
    if not previous or not previous.is_dir():
        raise UiError("Nothing to roll back to.")
    _read_manifest(previous)
    current = _target(ui / "current")
    _point(ui / "current", previous)
    if current:
        _point(ui / "previous", current)
    else:
        (ui / "previous").unlink()
    return previous.name


def reset(data_dir: Path):
    """Return to the bundled default look."""
    ui = Path(data_dir) / "ui"
    current = ui / "current"
    old = _target(current)
    if current.is_symlink():
        if old:
            _point(ui / "previous", old)
        current.unlink()


def status(data_dir: Path) -> dict:
    ui = Path(data_dir) / "ui"
    versions = sorted(p.name for p in (ui / "versions").iterdir()) if (ui / "versions").is_dir() else []
    cur, prev = _target(ui / "current"), _target(ui / "previous")
    return {
        "current": cur.name if cur else "bundled-default",
        "previous": prev.name if prev else None,
        "installed": versions,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-dir", default=os.environ.get("HEARTH_DATA_DIR"), required=not os.environ.get("HEARTH_DATA_DIR"))
    sub = parser.add_subparsers(dest="cmd", required=True)
    add = sub.add_parser("install")
    add.add_argument("source", help="path to a .zip, or an https URL (needs --sha256)")
    add.add_argument("--sha256", default="")
    add.add_argument("--no-activate", action="store_true")
    for name in ("rollback", "reset", "status"):
        sub.add_parser(name)
    args = parser.parse_args(argv)
    data_dir = Path(args.data_dir)
    try:
        if args.cmd == "install":
            print("Installed", install(data_dir, args.source, args.sha256, not args.no_activate))
        elif args.cmd == "rollback":
            print("Rolled back to", rollback(data_dir))
        elif args.cmd == "reset":
            reset(data_dir)
            print("Using the bundled default look.")
        else:
            print(json.dumps(status(data_dir), indent=2))
    except UiError as error:
        print("Error:", error, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
