#!/usr/bin/env python3
"""Create an Argon2id hash without echoing or storing the plaintext password."""

import getpass

from argon2 import PasswordHasher


def main():
    first = getpass.getpass("New local Hearth password: ")
    second = getpass.getpass("Repeat password: ")
    if not first or first != second:
        raise SystemExit("Passwords did not match or were empty.")
    print(PasswordHasher().hash(first))


if __name__ == "__main__":
    main()

