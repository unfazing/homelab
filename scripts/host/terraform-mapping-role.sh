#!/bin/sh

set -eu

mode=${1:-status}
proxmox_host=${PROXMOX_SSH_HOST:-root@192.168.1.10}
token_id=${TF_VAR_pm_api_token_id:-}
role=TerraformMapping
acl_path=/mapping/dir
role_privileges='Mapping.Audit,Mapping.Modify,Mapping.Use'
required_privileges='Mapping.Audit Mapping.Modify Mapping.Use'

test -n "$token_id" || {
  echo "Missing required environment variable: TF_VAR_pm_api_token_id" >&2
  exit 1
}

case "$mode" in
  status|apply)
    ;;
  *)
    echo "Usage: $0 [status|apply]" >&2
    exit 2
    ;;
esac

ssh \
  -o BatchMode=yes \
  -o ConnectTimeout=8 \
  -o StrictHostKeyChecking=yes \
  "$proxmox_host" \
  sh -s -- "$mode" "$token_id" "$role" "$acl_path" "$role_privileges" "$required_privileges" <<'REMOTE'
set -eu

mode=$1
token_id=$2
role=$3
acl_path=$4
role_privileges=$5
required_privileges=$6

if [ "$mode" = apply ]; then
  roles=$(pveum role list --output-format json | tr -d '[:space:]')
  if printf '%s' "$roles" | grep -Fq "\"roleid\":\"$role\""; then
    pveum role modify "$role" --privs "$role_privileges"
  else
    pveum role add "$role" --privs "$role_privileges"
  fi

  pveum acl modify "$acl_path" --roles "$role" --tokens "$token_id" --propagate 1
fi

permissions=$(pveum user permissions "$token_id" --path "$acl_path" --output-format json | tr -d '[:space:]')
for privilege in $required_privileges; do
  printf '%s' "$permissions" | grep -Fq "\"$privilege\":1" || {
    echo "Token $token_id lacks $privilege at $acl_path" >&2
    exit 1
  }
done

echo "Token $token_id has the scoped $role privileges at $acl_path."
REMOTE
