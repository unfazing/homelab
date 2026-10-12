#!/usr/bin/env bash
set -euo pipefail

[[ "${HOMELAB_CONFIRM_ADGUARD_ROTATION:-}" == yes ]] || {
  echo 'Set HOMELAB_CONFIRM_ADGUARD_ROTATION=yes to allow a brief AdGuard DNS interruption.' >&2
  exit 1
}

secret=.generated/secrets/adguard-admin-password
lock=.generated/secrets/.adguard-rotate.lock
[[ -f "$secret" && -s "$secret" && ! -L "$secret" ]] || {
  echo 'The ignored AdGuard administrator password is missing or invalid.' >&2
  exit 1
}
mkdir "$lock" || {
  echo 'Another AdGuard rotation may be in progress; inspect the lock directory.' >&2
  exit 1
}

umask 077
candidate=''
began=0
cleanup() {
  local result=$?
  if (( result != 0 && began == 0 )) && [[ -n "$candidate" && -f "$candidate" ]]; then
    rm -f "$candidate"
  fi
  rmdir "$lock"
}
trap cleanup EXIT
trap 'exit 1' INT TERM

[[ -r /dev/tty && -w /dev/tty ]] || {
  echo 'An interactive terminal is required to choose or generate the new AdGuard password.' >&2
  exit 1
}
printf 'New AdGuard password (at least 9 characters; Enter generates 16 random characters): ' > /dev/tty
IFS= read -r -s replacement < /dev/tty || {
  printf '\n' > /dev/tty
  echo 'Could not read the new password.' >&2
  exit 1
}
printf '\n' > /dev/tty
if [[ -z "$replacement" ]]; then
  replacement=$(openssl rand -base64 12)
  [[ ${#replacement} -eq 16 ]] || {
    echo 'Could not generate a 16-character AdGuard password.' >&2
    exit 1
  }
  echo 'Generated a random 16-character password. View it after success with task apps:adguard:credentials.'
else
  printf 'Confirm new AdGuard password: ' > /dev/tty
  IFS= read -r -s confirmation < /dev/tty || {
    printf '\n' > /dev/tty
    echo 'Could not read the confirmation.' >&2
    exit 1
  }
  printf '\n' > /dev/tty
  [[ ${#replacement} -ge 9 && "$replacement" == "$confirmation" ]] || {
    echo 'Passwords must match and contain at least 9 characters.' >&2
    exit 1
  }
fi

candidate=$(mktemp .generated/secrets/.adguard-password-new.XXXXXX)
chmod 600 "$candidate"
printf '%s\n' "$replacement" > "$candidate"
unset replacement confirmation

echo 'Rotating AdGuard administrator password; DNS will pause briefly.'
began=1
if ansible-playbook -i .generated/ansible/hosts.json \
  -e "adguard_expected_current_password_file=$PWD/$secret" \
  -e "adguard_new_password_file=$PWD/$candidate" \
  ansible/playbooks/adguard-rotate-password.yml; then
  mv -f "$candidate" "$secret"
  echo 'Rotation complete. Run task apps:adguard:credentials to view the new password.'
else
  echo 'Rotation failed; the previous controller password is unchanged.' >&2
  echo "The new candidate remains at $candidate in case guest recovery is needed." >&2
  exit 1
fi
