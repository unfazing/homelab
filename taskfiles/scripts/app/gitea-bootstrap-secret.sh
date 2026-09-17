#!/bin/sh

# Internal helper; invoke through Task.

set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/../../.." && pwd)
secret_dir="$repo_root/.generated/secrets"
secret_file="$secret_dir/gitea-admin-password"

umask 077
mkdir -p "$secret_dir"

if [ ! -f "$secret_file" ]; then
  temporary_file=$(mktemp "$secret_dir/gitea-admin-password.XXXXXX")
  trap 'rm -f "$temporary_file"' EXIT HUP INT TERM
  openssl rand -base64 48 | tr -d '\n' >"$temporary_file"
  chmod 0600 "$temporary_file"
  mv "$temporary_file" "$secret_file"
  trap - EXIT HUP INT TERM
  echo "Generated ignored Gitea bootstrap password at $secret_file."
else
  test "$(stat -f '%Lp' "$secret_file")" = 600 || chmod 0600 "$secret_file"
  echo "Using existing ignored Gitea bootstrap password at $secret_file."
fi
