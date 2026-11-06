#!/usr/bin/env bash
# Run on HER LAPTOP after installing ca.crt. Verifies trust, name, TLS and headers.
#   scripts/check_lan.sh [https://therapy.local:8443]
set -u
URL="${1:-https://therapy.local:8443}"
ok(){ printf '  PASS  %s\n' "$1"; }; bad(){ printf '  FAIL  %s\n' "$1"; FAILED=1; }
FAILED=0
H=$(curl -sS -m 8 -D - -o /tmp/hearth_health.json "$URL/healthz" 2>&1) || { bad "cannot reach $URL with system trust ($H)"; exit 1; }
ok "TLS verifies against the system keychain (no -k flag used)"
echo "$H" | grep -qi '^content-security-policy:.*script-src .self.' && ok "CSP present" || bad "CSP missing"
echo "$H" | grep -qi 'x-frame-options: deny' && ok "X-Frame-Options DENY" || bad "X-Frame-Options missing"
grep -q '"personal_use_ready":false' /tmp/hearth_health.json && ok "healthz still reports personal_use_ready=false (expected until all gates close)" || bad "unexpected healthz body"
grep -q '"dev_tools":false' /tmp/hearth_health.json && ok "dev tools are off" || bad "dev tools are ON; do not use with personal data"
curl -sS -m 5 -o /dev/null -w '%{http_code}' "http://therapy.local:80/" 2>/dev/null | grep -q 000 && ok "nothing answers on plain HTTP port 80" || bad "port 80 answers"
exit $FAILED
