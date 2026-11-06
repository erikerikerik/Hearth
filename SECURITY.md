# Security policy

Hearth is a pre-release local companion. The current build is not approved for sensitive personal data.

## Reporting a vulnerability

Use GitHub's private vulnerability reporting feature if it is enabled for this repository. If it is not enabled, open an issue containing only a minimal description and ask the maintainer for a private reporting channel.

Do not include conversation text, names, database files, logs, credentials, model files or any other personal data in a report. Synthetic reproduction data is preferred.

## Supported version

Only the newest tagged `1.3.0-rc1+pNNN` state is being maintained during the release-candidate phase. Earlier snapshots may contain known defects.

## Security boundary

The supported runtime boundary is one Apple-silicon Mac with services bound to loopback. Hearth is not designed to be exposed to a LAN or the public internet. It has no cloud fallback and never contacts emergency services or other people.
