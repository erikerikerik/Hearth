#!/usr/bin/env python3
"""Run the synthetic authenticated milestone on loopback only."""

import os

import uvicorn


def main():
    if not os.environ.get("HEARTH_PASSWORD_HASH") and not os.environ.get("HEARTH_DEV_PASSWORD"):
        raise SystemExit("Set HEARTH_PASSWORD_HASH (recommended) or HEARTH_DEV_PASSWORD for synthetic development.")
    port = int(os.environ.get("HEARTH_PORT", "4173"))
    uvicorn.run("app.main:create_app", host="127.0.0.1", port=port, factory=True, log_level="info")


if __name__ == "__main__":
    main()

