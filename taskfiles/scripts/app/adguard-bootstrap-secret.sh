#!/usr/bin/env bash
set -euo pipefail

secret_file=".generated/secrets/adguard-admin-password"
if [[ -e "$secret_file" ]]; then
  [[ -f "$secret_file" && -s "$secret_file" ]] || {
    echo "AdGuard administrator secret exists but is not a non-empty file" >&2
    exit 1
  }
  exit 0
fi

umask 077
mkdir -p "$(dirname "$secret_file")"
openssl rand -hex 32 > "$secret_file"
echo "Generated ignored AdGuard administrator password at $secret_file"
