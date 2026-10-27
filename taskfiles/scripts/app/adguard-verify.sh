#!/usr/bin/env bash
set -euo pipefail

resolver=192.168.1.100
domain="${HOMELAB_DOMAIN:?Set HOMELAB_DOMAIN}"

answer() {
  dig +short +time=3 +tries=1 "@$1" "$2" A
}

assert_equal() {
  local name="$1" expected="$2" actual="$3"
  if [[ "$actual" != "$expected" ]]; then
    printf 'FAIL %s: expected %s, got %s\n' "$name" "$expected" "${actual:-<empty>}" >&2
    exit 1
  fi
  printf 'PASS %s → %s\n' "$name" "$actual"
}

assert_equal 'blocked domain' '0.0.0.0' "$(answer "$resolver" doubleclick.net)"
assert_equal 'private Gitea rewrite' '192.168.1.101' "$(answer "$resolver" "gitea.home.$domain")"
assert_equal 'private AdGuard HTTPS rewrite' '192.168.1.101' "$(answer "$resolver" "adguard.home.$domain")"
assert_equal 'private Hermes rewrite' '192.168.1.101' "$(answer "$resolver" "hermes.home.$domain")"
assert_equal 'private Inkling rewrite' '192.168.1.101' "$(answer "$resolver" "inkling.home.$domain")"
assert_equal 'private Homepage rewrite' '192.168.1.101' "$(answer "$resolver" "dashboard.home.$domain")"

public_answer="$(answer "$resolver" example.org)"
[[ -n "$public_answer" ]] || {
  echo 'FAIL public DNS did not resolve on the new resolver' >&2
  exit 1
}
printf 'PASS public DNS answered on the new resolver\n'
