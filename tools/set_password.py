#!/usr/bin/env python3
"""Create the local Hearth password record (Argon2id) in the data directory.

The password is read from stdin (never argv), so it does not appear in process listings.
Used by the installed app's first-launch dialog; also usable from a terminal.
"""

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

from argon2 import PasswordHasher

MIN_LENGTH = 8


def write_auth(data_dir: Path, password: str, force: bool = False) -> Path:
    if len(password) < MIN_LENGTH:
        raise SystemExit("Password must be at least %d characters." % MIN_LENGTH)
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(data_dir, 0o700)
    target = data_dir / "auth.json"
    if target.exists() and not force:
        raise SystemExit("A password already exists. Use --force to replace it.")
    fd, tmp = tempfile.mkstemp(dir=str(data_dir), prefix=".auth-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump({"password_hash": PasswordHasher().hash(password)}, handle)
        os.chmod(tmp, 0o600)
        os.replace(tmp, target)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return target


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default=os.environ.get("HEARTH_DATA_DIR"), required=not os.environ.get("HEARTH_DATA_DIR"))
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    password = sys.stdin.readline().rstrip("\r\n")
    write_auth(Path(args.data_dir), password, args.force)
    print("Password saved.")


if __name__ == "__main__":
    main()
