#!/usr/bin/env bash
set -euo pipefail

old=192.168.1.9
new=192.168.1.100
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

assert_equal 'old blocked domain' '0.0.0.0' "$(answer "$old" doubleclick.net)"
assert_equal 'new blocked domain' '0.0.0.0' "$(answer "$new" doubleclick.net)"
assert_equal 'old router rewrite' '192.168.1.254' "$(answer "$old" router.home.net)"
assert_equal 'new router rewrite' '192.168.1.254' "$(answer "$new" router.home.net)"
assert_equal 'new AdGuard rewrite' "$new" "$(answer "$new" adguard.home.net)"
assert_equal 'private Gitea rewrite' '192.168.1.101' "$(answer "$new" "gitea.home.$domain")"
assert_equal 'private AdGuard HTTPS rewrite' '192.168.1.101' "$(answer "$new" "adguard.home.$domain")"

public_old="$(answer "$old" example.org)"
public_new="$(answer "$new" example.org)"
[[ -n "$public_old" && -n "$public_new" ]] || {
  echo 'FAIL public DNS did not resolve on both resolvers' >&2
  exit 1
}
printf 'PASS public DNS answered on both resolvers\n'
