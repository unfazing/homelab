#!/bin/sh

# Internal helper; invoke through Task.

set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/../../.." && pwd)
terraform_dir="$repo_root/terraform/storage-verification"
work_dir="$repo_root/.generated/storage-verification"
terraform_data_dir="$work_dir/terraform-data"
state_file="$work_dir/terraform.tfstate"
key_file="$work_dir/id_ed25519"
report_file="$repo_root/.generated/storage/virtiofs-verification.json"
proxmox_host=${PROXMOX_SSH_HOST:-root@192.168.1.10}
template_vmid=9000
verification_vmid=9900
verification_parent=tank/homelab/verification
verification_dataset="$verification_parent/virtiofs-proof"
verification_path=/srv/homelab/verification/virtiofs-proof
mapping_name=homelab-virtiofs-proof
mount_path=/mnt/homelab-virtiofs-proof
ssh_public_key=""
proof_succeeded=no

require_value() {
  variable_name=$1
  eval "variable_value=\${$variable_name:-}"
  if [ -z "$variable_value" ]; then
    echo "Missing required environment variable: $variable_name" >&2
    exit 1
  fi
}

for variable_name in \
  TF_VAR_pm_api_url \
  TF_VAR_pm_api_token_id \
  TF_VAR_pm_api_token_secret \
  TF_VAR_verification_node; do
  require_value "$variable_name"
done

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

host_run() {
  ssh \
    -o BatchMode=yes \
    -o ConnectTimeout=8 \
    -o StrictHostKeyChecking=yes \
    "$proxmox_host" \
    "$@"
}

terraform_run() {
  TF_DATA_DIR="$terraform_data_dir" terraform -chdir="$terraform_dir" "$@"
}

destroy_verification_stack() {
  if [ -f "$state_file" ]; then
    terraform_run destroy \
      -auto-approve \
      -input=false \
      -var="ssh_public_key=$ssh_public_key"
  fi
}

if [ -e "$state_file" ]; then
  echo "Existing storage-verification state requires inspection: $state_file" >&2
  echo "Refusing to guess whether it is safe to destroy resources from an earlier run." >&2
  exit 1
fi

cleanup() {
  result=$?
  trap - EXIT HUP INT TERM

  if ! destroy_verification_stack; then
    echo "Automatic Terraform cleanup failed; diagnostics remain under $work_dir." >&2
    result=1
  fi

  if [ "$proof_succeeded" = yes ] && [ "$result" -eq 0 ]; then
    if ! host_run sh -s -- "$verification_dataset" "$verification_parent" <<'REMOTE'
set -eu

verification_dataset=$1
verification_parent=$2

if zfs list -H -o name "$verification_dataset" >/dev/null 2>&1; then
  zfs destroy "$verification_dataset"
fi
if zfs list -H -o name "$verification_parent" >/dev/null 2>&1; then
  zfs destroy "$verification_parent"
fi
REMOTE
    then
      echo "Terraform cleanup passed, but the verification dataset could not be removed." >&2
      result=1
    else
      rm -rf -- "$work_dir"
    fi
  else
    echo "Verification data is preserved at $verification_dataset for diagnosis." >&2
  fi

  exit "$result"
}
trap cleanup EXIT HUP INT TERM

"$repo_root/taskfiles/scripts/host/terraform-mapping-role.sh" status

resources=$(pve_get "/cluster/resources?type=vm")
if ! printf '%s' "$resources" | jq -e ".data[] | select(.vmid == $template_vmid and .template == 1)" >/dev/null; then
  echo "Proxmox template VM $template_vmid does not exist or is not marked as a template." >&2
  exit 1
fi
if printf '%s' "$resources" | jq -e ".data[] | select(.vmid == $verification_vmid)" >/dev/null; then
  echo "Reserved verification VM ID $verification_vmid is already in use; refusing to continue." >&2
  exit 1
fi

if host_run zfs list -H -o name "$verification_dataset" >/dev/null 2>&1; then
  echo "Verification dataset already exists: $verification_dataset" >&2
  echo "Inspect it before removing it; the previous run may have retained evidence." >&2
  exit 1
fi

host_run sh -s -- "$verification_parent" "$verification_dataset" "$verification_path" <<'REMOTE'
set -eu

verification_parent=$1
verification_dataset=$2
verification_path=$3

if ! zfs list -H -o name "$verification_parent" >/dev/null 2>&1; then
  zfs create -o canmount=off "$verification_parent"
fi
zfs create "$verification_dataset"
zfs mount "$verification_dataset" 2>/dev/null || true
test "$(zfs get -H -o value mountpoint "$verification_dataset")" = "$verification_path"
test -d "$verification_path"
chown 1000:1000 "$verification_path"
chmod 0770 "$verification_path"
REMOTE

umask 077
mkdir -p "$work_dir" "$(dirname -- "$report_file")"
ssh-keygen -q -t ed25519 -N "" -C "homelab-storage-verifier" -f "$key_file"
ssh_public_key=$(awk '{ print $1 " " $2 " " $3 }' "$key_file.pub")
sentinel="virtiofs-proof-$(date -u +%Y%m%dT%H%M%SZ)-$$"

terraform_run init \
  -input=false \
  -reconfigure \
  -backend-config="path=$state_file"

apply_stack() {
  terraform_run apply \
    -auto-approve \
    -input=false \
    -var="ssh_public_key=$ssh_public_key"
}

resolve_guest_ipv4() {
  attempts=0
  while [ "$attempts" -lt 60 ]; do
    response=$(pve_get "/nodes/$TF_VAR_verification_node/qemu/$verification_vmid/agent/network-get-interfaces" 2>/dev/null || true)
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

  echo "Verification clone VM $verification_vmid never reported a usable IPv4 address." >&2
  return 1
}

ssh_run() {
  host=$1
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
  host=$1
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

mount_and_read() {
  host=$1
  expected=$2
  ssh_run "$host" sh -s -- "$mapping_name" "$mount_path" "$expected" <<'REMOTE'
set -eu

mapping_name=$1
mount_path=$2
expected=$3

sudo mkdir -p "$mount_path"
sudo mount -t virtiofs "$mapping_name" "$mount_path"
test "$(findmnt -n -o FSTYPE "$mount_path")" = virtiofs
test "$(cat "$mount_path/sentinel")" = "$expected"
test "$(python3 -c 'import os, sys; print(os.getxattr(sys.argv[1], "user.homelab-proof").decode())' "$mount_path/sentinel")" = persisted
sudo umount "$mount_path"
REMOTE
}

echo "Creating the first disposable VirtioFS guest..."
apply_stack
first_ip=$(resolve_guest_ipv4)
wait_for_ssh "$first_ip"

ssh_run "$first_ip" sh -s -- "$mapping_name" "$mount_path" "$sentinel" <<'REMOTE'
set -eu

mapping_name=$1
mount_path=$2
sentinel=$3

sudo mkdir -p "$mount_path"
sudo mount -t virtiofs "$mapping_name" "$mount_path"
test "$(findmnt -n -o FSTYPE "$mount_path")" = virtiofs
test "$(stat -c '%u:%g' "$mount_path")" = 1000:1000
python3 - "$mount_path/sentinel" "$sentinel" <<'PYTHON'
import os
import sys

path, value = sys.argv[1:]
with open(path, "w", encoding="utf-8") as sentinel_file:
    sentinel_file.write(value + "\n")
    sentinel_file.flush()
    os.fsync(sentinel_file.fileno())
os.setxattr(path, "user.homelab-proof", b"persisted")
directory_fd = os.open(os.path.dirname(path), os.O_RDONLY)
try:
    os.fsync(directory_fd)
finally:
    os.close(directory_fd)
PYTHON
sudo umount "$mount_path"
REMOTE

echo "Rebooting and remounting the first guest..."
first_boot_id=$(ssh_run "$first_ip" cat /proc/sys/kernel/random/boot_id)
ssh_run "$first_ip" sudo reboot >/dev/null 2>&1 || true
sleep 5
first_ip=$(resolve_guest_ipv4)
wait_for_ssh "$first_ip"
second_boot_id=$(ssh_run "$first_ip" cat /proc/sys/kernel/random/boot_id)
test "$first_boot_id" != "$second_boot_id"
mount_and_read "$first_ip" "$sentinel"

echo "Destroying the first guest and its mapping..."
destroy_verification_stack
host_sentinel=$(host_run cat "$verification_path/sentinel")
test "$host_sentinel" = "$sentinel"

echo "Recreating the guest and mapping from the same Terraform definition..."
apply_stack
second_ip=$(resolve_guest_ipv4)
wait_for_ssh "$second_ip"
mount_and_read "$second_ip" "$sentinel"

jq -n \
  --arg verified_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --arg dataset "$verification_dataset" \
  --arg mapping "$mapping_name" \
  --arg sentinel "$sentinel" \
  --arg first_ip "$first_ip" \
  --arg second_ip "$second_ip" \
  '{
    verified_at: $verified_at,
    disposable_dataset: $dataset,
    directory_mapping: $mapping,
    sentinel: $sentinel,
    first_guest_ipv4: $first_ip,
    recreated_guest_ipv4: $second_ip,
    checks: {
      uid_permissions: "passed",
      virtiofs_mount: "passed",
      synchronous_write: "passed",
      extended_attributes: "passed",
      reboot_remount: "passed",
      host_visibility: "passed",
      destroy_recreate_persistence: "passed"
    }
  }' >"$report_file"

proof_succeeded=yes
echo "VirtioFS persistence proof passed; report written to $report_file."
