#!/bin/sh

# Internal helper; invoke through Task.

set -eu

mode=${1:-status}
proxmox_host=${PROXMOX_SSH_HOST:-root@192.168.1.10}
data_device=/dev/disk/by-id/ata-CT1000MX500SSD1_2424E8B7E144
expected_serial=2424E8B7E144
expected_model=CT1000MX500SSD1
pool=tank
confirmation=ata-CT1000MX500SSD1_2424E8B7E144

case "$mode" in
  status|reconcile)
    ;;
  bootstrap)
    if [ "${HOMELAB_CONFIRM_DATA_WIPE:-}" != "$confirmation" ]; then
      echo "Refusing destructive storage bootstrap." >&2
      echo "Set HOMELAB_CONFIRM_DATA_WIPE=$confirmation after verifying the disk contents." >&2
      exit 1
    fi
    ;;
  *)
    echo "Usage: $0 [status|reconcile|bootstrap]" >&2
    exit 2
    ;;
esac

ssh \
  -o BatchMode=yes \
  -o ConnectTimeout=8 \
  -o StrictHostKeyChecking=yes \
  "$proxmox_host" \
  sh -s -- "$mode" "$data_device" "$pool" "$expected_model" "$expected_serial" <<'REMOTE'
set -eu

mode=$1
data_device=$2
pool=$3
expected_model=$4
expected_serial=$5

if [ "$mode" = status ]; then
  if zpool list -H -o name "$pool" >/dev/null 2>&1; then
    zpool status -P "$pool"
    zfs list -r -o name,used,avail,refer,mountpoint,canmount "$pool"
  else
    echo "ZFS pool $pool does not exist."
    lsblk -o NAME,TYPE,SIZE,FSTYPE,MODEL,SERIAL,MOUNTPOINTS "$data_device"
  fi
  exit 0
fi

for command_name in blockdev findmnt grep lsblk readlink wipefs zfs zpool; do
  command -v "$command_name" >/dev/null 2>&1 || {
    echo "Missing required Proxmox command: $command_name" >&2
    exit 1
  }
done

test -e "$data_device" || {
  echo "Expected data device does not exist: $data_device" >&2
  exit 1
}

resolved_device=$(readlink -f "$data_device")
device_type=$(lsblk -dn -o TYPE "$resolved_device" | tr -d ' ')
device_model=$(lsblk -dn -o MODEL "$resolved_device" | sed 's/[[:space:]]*$//')
device_serial=$(lsblk -dn -o SERIAL "$resolved_device" | tr -d ' ')
device_size=$(blockdev --getsize64 "$resolved_device")
root_source=$(findmnt -n -o SOURCE /)

test "$device_type" = disk || {
  echo "Refusing non-disk target: $resolved_device ($device_type)" >&2
  exit 1
}
test "$device_model" = "$expected_model" || {
  echo "Unexpected model for $resolved_device: $device_model" >&2
  exit 1
}
test "$device_serial" = "$expected_serial" || {
  echo "Unexpected serial for $resolved_device: $device_serial" >&2
  exit 1
}
test "$device_size" -ge 900000000000 && test "$device_size" -le 1100000000000 || {
  echo "Unexpected size for $resolved_device: $device_size bytes" >&2
  exit 1
}

if lsblk -srno PATH "$root_source" | grep -Fxq "$resolved_device"; then
  echo "Refusing to use the device containing the root filesystem: $resolved_device" >&2
  exit 1
fi

if lsblk -nrpo MOUNTPOINTS "$resolved_device" | grep -q '[^[:space:]]'; then
  echo "Refusing mounted device or partition under $resolved_device:" >&2
  lsblk -o NAME,SIZE,FSTYPE,MOUNTPOINTS "$resolved_device" >&2
  exit 1
fi

echo "Verified $data_device -> $resolved_device ($device_model, $device_serial, $device_size bytes)."

if [ "$mode" = reconcile ] && ! zpool list -H -o name "$pool" >/dev/null 2>&1; then
  echo "Pool $pool does not exist; use the separately authorized bootstrap workflow first." >&2
  exit 1
fi

if zpool list -H -o name "$pool" >/dev/null 2>&1; then
  if ! zpool status -P "$pool" | grep -Fq "$data_device" && ! zpool status -P "$pool" | grep -Fq "$resolved_device"; then
    echo "Pool $pool exists but is not backed by the authorized device." >&2
    exit 1
  fi
  echo "Pool $pool already exists on the authorized device; reconciling properties and datasets."
else
  echo "Existing signatures that will be replaced:"
  wipefs -n "$resolved_device" || true
  zpool create -f \
    -o ashift=12 \
    -o autotrim=on \
    -O acltype=posixacl \
    -O atime=off \
    -O compression=lz4 \
    -O dedup=off \
    -O encryption=off \
    -O mountpoint=none \
    -O xattr=sa \
    "$pool" "$data_device"
fi

zpool set autotrim=on "$pool"
zfs set acltype=posixacl "$pool"
zfs set atime=off "$pool"
zfs set compression=lz4 "$pool"
zfs set dedup=off "$pool"
zfs set xattr=sa "$pool"

ensure_dataset() {
  dataset=$1
  if ! zfs list -H -o name "$dataset" >/dev/null 2>&1; then
    zfs create "$dataset"
  fi
}

ensure_dataset "$pool/homelab"
zfs set canmount=off "$pool/homelab"
zfs set mountpoint=/srv/homelab "$pool/homelab"

for group in access services agents; do
  ensure_dataset "$pool/homelab/$group"
  zfs unmount "$pool/homelab/$group" 2>/dev/null || true
  zfs set canmount=off "$pool/homelab/$group"
done

for dataset in \
  access/adguard \
  access/wireguard \
  services/nextcloud-files \
  services/nextcloud-db \
  services/gitea \
  services/reverse-proxy \
  services/vaultwarden \
  agents/hermes; do
  ensure_dataset "$pool/homelab/$dataset"
done

zfs mount -a
zpool status -P "$pool"
zfs list -r -o name,used,avail,refer,mountpoint,canmount "$pool"
REMOTE
