# LAN HTTPS for therapy.local (release gate 3)

Target: the Mac mini serves `https://therapy.local:8443`; her M3 Pro MacBook uses Brave. Brave on macOS trusts the system keychain, so one CA install is enough. Status: the scripts are tested against this app on Linux (certificate issue, name constraint, Secure cookie over TLS). **Not yet run on the real Mac mini or laptop, so the gate is still open.**

## 1. On the Mac mini (once)
1. Name it so Bonjour answers `therapy.local`: `sudo scutil --set LocalHostName therapy`.
2. Give it a fixed address: reserve its Ethernet/Wi-Fi address in the router (DHCP reservation).
3. `scripts/tls_setup.sh` — creates `~/Hearth-TLS` with a passphrase-protected CA that may only issue for `therapy.local` (name-constrained), plus the server certificate (365 days; macOS rejects longer).
4. Copy `ca.key` to an offline USB stick, then delete it from the Mini. Keep `ca.crt` (public). Back up the passphrase separately.
5. Create the login hash with `python scripts/create_password_hash.py`, then: `export HEARTH_PASSWORD_HASH='…'` and run `scripts/run_https.sh`. It binds only the LAN address, never 0.0.0.0, with dev tools off.

## 2. On her laptop (once)
1. Move `ca.crt` over by AirDrop or USB (not by email).
2. Terminal: `sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain ca.crt` (admin password required).
3. Quit and reopen Brave, then open `https://therapy.local:8443`. There must be no warning.
4. Run `scripts/check_lan.sh`.
5. Microphone: when the voice step ships, Brave asks permission once for this site. Shields do not block it.

## 3. Lock down the Mini
- System Settings → Network → Firewall: on, with Stealth Mode on.
- Optional but recommended: allow only her laptop's address to reach the port. Reserve the laptop's address in the router, then add a pf anchor that passes TCP 8443 from that address and blocks the rest.
- From the laptop run `nmap -p- therapy.local`. Only 8443 may be open (mDNS on UDP 5353 is the OS). Attach the output as gate evidence.
- Optional: URL without `:8443` needs a pf redirect 443→8443. Skip unless wanted.

## 4. Renewal and loss
- Server cert expires after 365 days: plug in the USB, run `scripts/tls_issue.sh`, restart.
- If the CA key is lost, create a new CA and reinstall `ca.crt` on the laptop. Nothing else depends on it.
- Remove trust: Keychain Access → System → "Hearth Local CA" → delete.

## Known limits
- Tested with synthetic data only. Mac mini behaviour (Bonjour name, firewall, pf) is unverified.
- LibreSSL on macOS differs slightly from the OpenSSL used here; if `tls_setup.sh` fails there, send me the error.
