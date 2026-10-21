#!/usr/bin/env bash
set -euo pipefail

# Persistent Storage (berbayar) memasang volume di /data; tanpa itu /data
# tetap dibuat sebagai direktori sementara di dalam kontainer.
mkdir -p /data

# Private key Ed25519 dipasang lewat HF Secret LICENSE_PRIVATE_KEY_PEM
# (isi file .pem utuh, multi-baris). Tanpa ini server tetap jalan, tetapi
# penerbitan lisensi akan gagal dengan SigningError.
if [ -n "${LICENSE_PRIVATE_KEY_PEM:-}" ]; then
  printf '%s\n' "$LICENSE_PRIVATE_KEY_PEM" > /data/license-signing-private.pem
  chmod 600 /data/license-signing-private.pem
  export LICENSE_PRIVATE_KEY_PATH=/data/license-signing-private.pem
fi

exec python -m uvicorn server.app.main:app --host 0.0.0.0 --port "${PORT:-7860}"
