#!/bin/sh
# Runtime settings come only from the protected systemd environment file.

set -efu

api_base=https://api.cloudflare.com/client/v4

fail() {
  printf 'Cloudflare DDNS: %s\n' "$1" >&2
  exit 1
}

require_value() {
  variable_name=$1
  eval "variable_value=\${$variable_name:-}"
  [ -n "$variable_value" ] || fail "missing $variable_name"
}

cloudflare_request() {
  method=$1
  endpoint=$2
  request_body=${3:-}

  if [ -n "$request_body" ]; then
    printf 'header = "Authorization: Bearer %s"\nheader = "Content-Type: application/json"\n' \
      "$CLOUDFLARE_DDNS_API_TOKEN" |
      curl \
        --config - \
        --silent \
        --show-error \
        --fail \
        --request "$method" \
        --data "$request_body" \
        "$api_base$endpoint"
  else
    printf 'header = "Authorization: Bearer %s"\n' "$CLOUDFLARE_DDNS_API_TOKEN" |
      curl \
        --config - \
        --silent \
        --show-error \
        --fail \
        --request "$method" \
        "$api_base$endpoint"
  fi
}

assert_cloudflare_success() {
  response=$1
  if ! printf '%s' "$response" | jq -e '.success == true' >/dev/null; then
    errors=$(printf '%s' "$response" | jq -c '.errors // []' 2>/dev/null || printf 'invalid JSON response')
    fail "Cloudflare API request failed: $errors"
  fi
}

require_value CLOUDFLARE_ACCOUNT_ID
require_value CLOUDFLARE_DDNS_API_TOKEN
require_value CLOUDFLARE_DDNS_RECORD_LABELS
require_value CLOUDFLARE_DDNS_TTL
require_value CLOUDFLARE_DDNS_IPV4_SOURCE_URL

seen_labels=''
label_count=0
for label in $CLOUDFLARE_DDNS_RECORD_LABELS; do
  case "$label" in
    '@') ;;
    ''|-*|*-|*[!a-z0-9-]*) fail 'invalid DNS record label' ;;
  esac
  [ "${#label}" -le 63 ] || fail 'DNS label is too long'
  case " $seen_labels " in *" $label "*) fail 'duplicate DNS record label' ;; esac
  seen_labels="$seen_labels $label"
  label_count=$((label_count + 1))
done
[ "$label_count" -gt 0 ] && [ "$label_count" -le 10 ] || fail 'expected one to ten DNS labels'
case "$CLOUDFLARE_DDNS_TTL" in ''|*[!0-9]*) fail 'invalid DNS TTL' ;; esac
[ "$CLOUDFLARE_DDNS_TTL" -ge 60 ] || fail 'DNS TTL must be at least 60'

public_trace=$(curl -4 --silent --show-error --fail "$CLOUDFLARE_DDNS_IPV4_SOURCE_URL")
public_ipv4=$(printf '%s\n' "$public_trace" | awk -F= '$1 == "ip" { print $2; exit }')
[ -n "$public_ipv4" ] || fail 'public IPv4 source returned no address'
printf '%s\n' "$public_ipv4" | awk -F. '
  NF != 4 { exit 1 }
  {
    for (part = 1; part <= 4; part++) {
      if ($part !~ /^[0-9]+$/ || $part < 0 || $part > 255) exit 1
    }
  }
' || fail 'public IPv4 source returned an invalid address'

zone_response=$(cloudflare_request GET "/zones?account.id=$CLOUDFLARE_ACCOUNT_ID&status=active&per_page=2")
assert_cloudflare_success "$zone_response"
[ "$(printf '%s' "$zone_response" | jq '.result | length')" -eq 1 ] ||
  fail 'DDNS token must expose exactly one active Cloudflare zone'

zone_id=$(printf '%s' "$zone_response" | jq -r '.result[0].id')
zone_name=$(printf '%s' "$zone_response" | jq -r '.result[0].name')
# Preflight every name before performing any mutations. TXT/MX/AAAA records are
# left untouched; a CNAME or duplicate A is an explicit operator conflict.
record_plan='[]'
for label in $CLOUDFLARE_DDNS_RECORD_LABELS; do
  if [ "$label" = '@' ]; then record_name=$zone_name; else record_name="$label.$zone_name"; fi
  record_response=$(cloudflare_request GET "/zones/$zone_id/dns_records?name=$record_name&per_page=100")
  assert_cloudflare_success "$record_response"
  [ "$(printf '%s' "$record_response" | jq '.result_info.total_pages // 1')" -le 1 ] || fail "too many records for $record_name"
  [ "$(printf '%s' "$record_response" | jq '[.result[] | select(.type == "CNAME")] | length')" -eq 0 ] || fail "CNAME conflicts with A record for $record_name"
  records=$(printf '%s' "$record_response" | jq '[.result[] | select(.type == "A")]')
  [ "$(printf '%s' "$records" | jq 'length')" -le 1 ] || fail "multiple A records exist for $record_name"
  record_plan=$(printf '%s' "$record_plan" | jq --arg name "$record_name" --argjson records "$records" '. + [{name:$name, existing:($records[0] // null)}]')
done

for label in $CLOUDFLARE_DDNS_RECORD_LABELS; do
  if [ "$label" = '@' ]; then record_name=$zone_name; else record_name="$label.$zone_name"; fi
  current=$(printf '%s' "$record_plan" | jq --arg name "$record_name" '.[] | select(.name == $name) | .existing')
  if [ "$current" != null ] && printf '%s' "$current" | jq -e --arg ip "$public_ipv4" --argjson ttl "$CLOUDFLARE_DDNS_TTL" '.content == $ip and .ttl == $ttl and .proxied == false' >/dev/null; then
    printf 'Cloudflare DDNS: DNS-only %s is current\n' "$record_name"
    continue
  fi
  record_body=$(jq -nc --arg name "$record_name" --arg content "$public_ipv4" \
    --arg comment 'Managed by the homelab Cloudflare DDNS updater' --argjson ttl "$CLOUDFLARE_DDNS_TTL" \
    '{type:"A",name:$name,content:$content,ttl:$ttl,proxied:false,comment:$comment}')
  if [ "$current" = null ]; then
    mutation_response=$(cloudflare_request POST "/zones/$zone_id/dns_records" "$record_body")
    action=created
  else
    record_id=$(printf '%s' "$current" | jq -r '.id')
    mutation_response=$(cloudflare_request PATCH "/zones/$zone_id/dns_records/$record_id" "$record_body")
    action=updated
  fi
  assert_cloudflare_success "$mutation_response"
  printf 'Cloudflare DDNS: %s DNS-only %s\n' "$action" "$record_name"
done
