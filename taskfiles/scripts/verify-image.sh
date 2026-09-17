#!/bin/sh

# Internal helper; invoke through Task.

set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
terraform_dir="$repo_root/terraform/image-verification"
work_dir="$repo_root/.generated/image-verification"
terraform_data_dir="$work_dir/terraform-data"
state_file="$work_dir/terraform.tfstate"
key_file="$work_dir/id_ed25519"
report_file="$repo_root/.generated/packer/verification.json"
template_vmid=9000
verification_vmid=9900
ssh_public_key=""

require_value() {
  variable_name="$1"
  eval "variable_value=\${$variable_name:-}"
  if [ -z "$variable_value" ]; then
    echo "Missing required environment variable: $variable_name" >&2
    exit 1
  fi
}

require_value TF_VAR_pm_api_url
require_value TF_VAR_pm_api_token_id
require_value TF_VAR_pm_api_token_secret
require_value TF_VAR_verification_node

pve_get() {
  printf 'header = "Authorization: PVEAPIToken=%s=%s"\n' \
    "$TF_VAR_pm_api_token_id" \
    "$TF_VAR_pm_api_token_secret" |
    curl \
      --config - \
      --silent \
      --show-error \
      --fail \
      --insecure \
      "${TF_VAR_pm_api_url%/}$1"
}

pve_post() {
  printf 'header = "Authorization: PVEAPIToken=%s=%s"\n' \
    "$TF_VAR_pm_api_token_id" \
    "$TF_VAR_pm_api_token_secret" |
    curl \
      --config - \
      --silent \
      --show-error \
      --fail \
      --insecure \
      --request POST \
      "${TF_VAR_pm_api_url%/}$1"
}

cleanup() {
  result=$?
  trap - EXIT HUP INT TERM

  if [ -f "$state_file" ]; then
    echo "Destroying disposable image-verification VMs..."
    if ! TF_DATA_DIR="$terraform_data_dir" terraform -chdir="$terraform_dir" destroy \
      -auto-approve \
      -input=false \
      -var="ssh_public_key=$ssh_public_key"; then
      echo "Automatic cleanup failed; state is retained at $state_file." >&2
      result=1
    else
      rm -rf -- "$work_dir"
    fi
  else
    rm -rf -- "$work_dir"
  fi

  exit "$result"
}
trap cleanup EXIT HUP INT TERM

resources=$(pve_get "/cluster/resources?type=vm")
if ! printf '%s' "$resources" | jq -e ".data[] | select(.vmid == $template_vmid and .template == 1)" >/dev/null; then
  echo "Proxmox template VM $template_vmid does not exist or is not marked as a template." >&2
  exit 1
fi

if printf '%s' "$resources" | jq -e ".data[] | select(.vmid == $verification_vmid)" >/dev/null; then
  echo "Reserved verification VM ID $verification_vmid is already in use; refusing to continue." >&2
  exit 1
fi

umask 077
mkdir -p "$work_dir" "$(dirname -- "$report_file")"
ssh-keygen -q -t ed25519 -N "" -C "homelab-image-verifier" -f "$key_file"
ssh_public_key=$(awk '{ print $1 " " $2 " " $3 }' "$key_file.pub")

TF_DATA_DIR="$terraform_data_dir" terraform -chdir="$terraform_dir" init \
  -input=false \
  -reconfigure \
  -backend-config="path=$state_file"
TF_DATA_DIR="$terraform_data_dir" terraform -chdir="$terraform_dir" apply \
  -auto-approve \
  -input=false \
  -var="ssh_public_key=$ssh_public_key"

addresses=$(TF_DATA_DIR="$terraform_data_dir" terraform -chdir="$terraform_dir" output \
  -json ipv4_addresses)
ip_a=$(printf '%s' "$addresses" | jq -er '.a')

resolve_guest_ipv4() {
  vmid="$1"
  reported_address="$2"

  if [ -n "$reported_address" ]; then
    printf '%s\n' "$reported_address"
    return 0
  fi

  echo "VM $vmid has no Terraform-reported IPv4 address; querying the guest agent for up to 60 seconds..." >&2
  attempts=0
  while [ "$attempts" -lt 12 ]; do
    response=$(pve_get "/nodes/$TF_VAR_verification_node/qemu/$vmid/agent/network-get-interfaces" 2>/dev/null || true)
    address=$(printf '%s' "$response" | jq -r '
      [
        .data.result[]?
        | select(.name != "lo")
        | .["ip-addresses"][]?
        | select(.["ip-address-type"] == "ipv4")
        | .["ip-address"]
        | select(startswith("127.") | not)
      ][0] // empty
    ')
    if [ -n "$address" ]; then
      printf '%s\n' "$address"
      return 0
    fi
    attempts=$((attempts + 1))
    sleep 5
  done

  echo "Verification clone VM $vmid never reported a usable IPv4 address." >&2
  return 1
}

ip_a=$(resolve_guest_ipv4 9900 "$ip_a")

ssh_run() {
  host="$1"
  shift
  ssh \
    -i "$key_file" \
    -o BatchMode=yes \
    -o ConnectTimeout=5 \
    -o LogLevel=ERROR \
    -o StrictHostKeyChecking=no \
    -o UserKnownHostsFile=/dev/null \
    "verifier@$host" \
    "$@"
}

wait_for_ssh() {
  host="$1"
  attempts=0
  until ssh_run "$host" true >/dev/null 2>&1; do
    attempts=$((attempts + 1))
    if [ "$attempts" -ge 60 ]; then
      echo "Timed out waiting for SSH on verification clone $host." >&2
      return 1
    fi
    sleep 5
  done
}

verify_guest() {
  host="$1"
  expected_hostname="$2"
  wait_for_ssh "$host"

  set +e
  check_output=$(ssh_run "$host" '
    set -eu

    printf "  cloud-init completed without fatal errors... "
    cloud_init_json=$(sudo cloud-init status --wait --format json || true)
    printf "%s" "$cloud_init_json" | python3 -c "
import json
import sys

status = json.load(sys.stdin)
if status.get(\"status\") != \"done\" or status.get(\"errors\"):
    raise SystemExit(1)
recoverable = sum(len(items) for items in status.get(\"recoverable_errors\", {}).values())
print(f\"passed ({recoverable} recoverable warning(s))\")
"

    printf "  passwordless sudo... "
    sudo -n true
    echo passed

    printf "  cloud-init hostname applied... "
    test "$(hostname)" = "'"$expected_hostname"'"
    echo passed

    printf "  QEMU guest agent active... "
    test "$(systemctl is-active qemu-guest-agent)" = active
    echo passed

    printf "  temporary packer account absent... "
    ! getent passwd packer >/dev/null
    test ! -e /home/packer
    test ! -e /etc/sudoers.d/packer
    echo passed


    printf "  reusable network configuration applied... "
    test -z "$(find /etc/netplan -maxdepth 1 -name "00-installer-config*.yaml" -print -quit)"
    ! sudo journalctl -b -u systemd-networkd --no-pager | grep -q "zzzz-dracut-default.network"
    echo passed

    printf "  password SSH disabled... "
    sudo sshd -T | grep -Eq "^passwordauthentication no$"
    echo passed
  ' 2>&1)
  check_status=$?
  set -e

  printf '%s\n' "$check_output"
  if [ "$check_status" -ne 0 ]; then
    echo "Guest checks failed on $host (SSH exit $check_status). Cloud-init diagnostics follow:" >&2
    ssh_run "$host" '
      sudo cloud-init status --long || true
      sudo journalctl -u cloud-init-local -u cloud-init -u cloud-config -u cloud-final --no-pager -n 120 || true
    ' >&2 || true
    return 1
  fi
}

echo "Verifying clone a at $ip_a..."
verify_guest "$ip_a" "verify-ubuntu-26-04-a"

machine_id_a=$(ssh_run "$ip_a" cat /etc/machine-id)
host_key_a=$(ssh_run "$ip_a" "sudo ssh-keygen -E sha256 -lf /etc/ssh/ssh_host_ed25519_key.pub | cut -d ' ' -f 2")

test -n "$machine_id_a"
test -n "$host_key_a"

pve_post "/nodes/$TF_VAR_verification_node/qemu/$verification_vmid/agent/ping" | jq -e '.data.result != null' >/dev/null

jq -n \
  --arg verified_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --argjson template_vmid "$template_vmid" \
  --arg machine_id_a "$machine_id_a" \
  --arg host_key_a "$host_key_a" \
  '{
    verified_at: $verified_at,
    template_vmid: $template_vmid,
    checks: {
      cloud_init: "passed",
      key_only_ssh: "passed",
      cloud_init_hostname: "passed",
      packer_account_absent: "passed",
      installer_network_absent: "passed",
      initramfs_network_absent: "passed",
      qemu_guest_agent: "passed",
      machine_id_present: ($machine_id_a | length > 0),
      ssh_host_key_present: ($host_key_a | length > 0),
      multi_clone_identity_uniqueness: "not_run_single_clone"
    },
    clone_evidence: {
      a: { machine_id: $machine_id_a, ssh_host_key: $host_key_a }
    }
  }' > "$report_file"

echo "Image verification passed; report written to $report_file."
