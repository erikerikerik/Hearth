#!/usr/bin/env bash
# Creates a private certificate authority that can ONLY issue for therapy.local,
# then issues the server certificate. Run on the Mac mini. Synthetic-safe: no network.
#   scripts/tls_setup.sh [output_dir]        (default: ~/Hearth-TLS, outside the project)
# Env: CA_PASSPHRASE_FILE=path  (non-interactive; otherwise openssl prompts)
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
OUT="${1:-$HOME/Hearth-TLS}"
HOST="therapy.local"
mkdir -p "$OUT"; chmod 700 "$OUT"; cd "$OUT"
[ -e ca.key ] && { echo "ca.key already exists in $OUT; use scripts/tls_issue.sh to renew the server cert." >&2; exit 1; }

PASS_ARGS=()
[ -n "${CA_PASSPHRASE_FILE:-}" ] && PASS_ARGS=(-pass "file:$CA_PASSPHRASE_FILE")

cat > ca.cnf <<CNF
[req]
distinguished_name = dn
x509_extensions = v3_ca
prompt = no
[dn]
CN = Hearth Local CA
[v3_ca]
basicConstraints = critical,CA:TRUE,pathlen:0
keyUsage = critical,keyCertSign,cRLSign
subjectKeyIdentifier = hash
nameConstraints = critical,permitted;DNS:$HOST
CNF

openssl genpkey -algorithm EC -pkeyopt ec_paramgen_curve:P-256 -aes-256-cbc ${PASS_ARGS[@]+"${PASS_ARGS[@]}"} -out ca.key
openssl req -x509 -new -key ca.key ${PASS_ARGS[@]+"${PASS_ARGS[@]/#-pass/-passin}"} -sha256 -days 3650 -config ca.cnf -out ca.crt
chmod 600 ca.key; rm ca.cnf
"$SCRIPT_DIR/tls_issue.sh" "$OUT"
cat <<MSG

Done. Files in $OUT:
  ca.crt            public: install on her laptop (see docs/LAN_HTTPS.md)
  ca.key            PRIVATE, passphrase-protected: move to an offline USB stick after this.
  $HOST.crt/.key    server certificate and key used by scripts/run_https.sh
MSG
