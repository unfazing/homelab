#!/bin/sh

set -eu

mode="${1:-}"
case "$mode" in
  validate|build) ;;
  *)
    echo "Usage: $0 validate|build" >&2
    exit 2
    ;;
esac

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
image_dir="$repo_root/packer/images/ubuntu-26.04"
image_vars="$image_dir/ubuntu-26.04.pkrvars.hcl"
generated_root="$repo_root/.generated/packer"
build_dir="$generated_root/ubuntu-26.04"
http_dir="$build_dir/http"
key_file="$build_dir/id_ed25519"
template_vmid=9000

cleanup() {
  if [ -d "$build_dir" ]; then
    rm -rf -- "$build_dir"
  fi
}
trap cleanup EXIT HUP INT TERM

require_value() {
  variable_name="$1"
  eval "variable_value=\${$variable_name:-}"
  if [ -z "$variable_value" ]; then
    echo "Missing required environment variable: $variable_name" >&2
    exit 1
  fi
}

require_value PKR_VAR_proxmox_api_url
require_value PKR_VAR_proxmox_user
require_value PKR_VAR_node
require_value PKR_VAR_packer_http_interface

if [ -z "${PKR_VAR_proxmox_token:-}" ] && [ -z "${PKR_VAR_proxmox_password:-}" ]; then
  echo "Set PKR_VAR_proxmox_token or PKR_VAR_proxmox_password." >&2
  exit 1
fi

interface="$PKR_VAR_packer_http_interface"
bind_address="${PKR_VAR_packer_http_bind_address:-}"
if [ -z "$bind_address" ] && command -v ipconfig >/dev/null 2>&1; then
  bind_address=$(ipconfig getifaddr "$interface" 2>/dev/null || true)
fi
if [ -z "$bind_address" ] && command -v ip >/dev/null 2>&1; then
  bind_address=$(ip -o -4 addr show dev "$interface" 2>/dev/null | awk '$3 == "inet" { split($4, address, "/"); print address[1]; exit }')
fi
if [ -z "$bind_address" ] && command -v ifconfig >/dev/null 2>&1; then
  bind_address=$(ifconfig "$interface" 2>/dev/null | awk '$1 == "inet" { print $2; exit }')
fi
if [ -z "$bind_address" ]; then
  echo "Could not determine an IPv4 address for trusted interface: $interface" >&2
  echo "Set PKR_VAR_packer_http_bind_address explicitly." >&2
  exit 1
fi

umask 077
mkdir -p "$http_dir"
ssh-keygen -q -t ed25519 -N "" -C "homelab-packer-ephemeral" -f "$key_file"
public_key=$(awk '{ print $1 " " $2 " " $3 }' "$key_file.pub")
awk -v key="$public_key" '{ gsub(/__PACKER_SSH_PUBLIC_KEY__/, key); print }' \
  "$repo_root/packer/http/ubuntu/user-data.pkrtpl" > "$http_dir/user-data"
cp "$repo_root/packer/http/ubuntu/meta-data" "$http_dir/meta-data"

export PKR_VAR_http_directory="$http_dir"
export PKR_VAR_ssh_private_key_file="$key_file"
export PKR_VAR_packer_http_bind_address="$bind_address"

packer validate -var-file="$image_vars" "$image_dir"

if [ "$mode" = "validate" ]; then
  exit 0
fi

require_value PKR_VAR_proxmox_token
api_response="$build_dir/proxmox-vms.json"
printf 'header = "Authorization: PVEAPIToken=%s=%s"\n' \
  "$PKR_VAR_proxmox_user" \
  "$PKR_VAR_proxmox_token" |
  curl \
    --config - \
    --silent \
    --show-error \
    --fail \
    --insecure \
    --output "$api_response" \
    "${PKR_VAR_proxmox_api_url%/}/cluster/resources?type=vm"

if grep -Eq "\"vmid\"[[:space:]]*:[[:space:]]*$template_vmid([^0-9]|$)" "$api_response"; then
  echo "Proxmox VM ID $template_vmid is already in use; refusing to build." >&2
  exit 1
fi

mkdir -p "$generated_root"
packer build -var-file="$image_vars" "$image_dir"
