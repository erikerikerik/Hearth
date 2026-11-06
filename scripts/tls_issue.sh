#!/usr/bin/env bash
# Issues (or renews) the therapy.local server certificate. Needs ca.key in the output dir.
# Validity is 365 days because macOS rejects server certs valid for more than 398 days.
set -euo pipefail
OUT="${1:-$HOME/Hearth-TLS}"; HOST="therapy.local"
PASS_ARGS=(); [ -n "${CA_PASSPHRASE_FILE:-}" ] && PASS_ARGS=(-passin "file:$CA_PASSPHRASE_FILE")
cd "$OUT"
cat > leaf.cnf <<CNF
[req]
distinguished_name = dn
prompt = no
[dn]
CN = $HOST
[v3_leaf]
basicConstraints = critical,CA:FALSE
keyUsage = critical,digitalSignature
extendedKeyUsage = serverAuth
subjectAltName = DNS:$HOST
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid
CNF
openssl ecparam -name prime256v1 -genkey -noout -out "$HOST.key"; chmod 600 "$HOST.key"
openssl req -new -key "$HOST.key" -config leaf.cnf -out leaf.csr
openssl x509 -req -in leaf.csr -CA ca.crt -CAkey ca.key ${PASS_ARGS[@]+"${PASS_ARGS[@]}"} -CAcreateserial \
  -days 365 -sha256 -extfile leaf.cnf -extensions v3_leaf -out leaf.crt
cat leaf.crt ca.crt > "$HOST.crt"
rm -f leaf.cnf leaf.csr leaf.crt ca.srl
openssl verify -CAfile ca.crt "$HOST.crt"
