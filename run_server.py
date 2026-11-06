#!/usr/bin/env python3
"""Installed-app entry point: loopback only, password from the data directory's auth.json."""

import os

import uvicorn

from app.main import configured_password_hash, default_data_dir


def main():
    configured_password_hash(default_data_dir())  # fail fast, with a clear message, if setup was skipped
    port = int(os.environ.get("HEARTH_PORT", "4173"))
    uvicorn.run("app.main:create_app", host="127.0.0.1", port=port, factory=True, log_level="warning")


if __name__ == "__main__":
    main()
