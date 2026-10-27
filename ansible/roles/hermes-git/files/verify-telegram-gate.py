#!/usr/bin/env python3
"""Fail closed unless the Hermes Telegram gateway is limited to one user.

Only a generic success or failure is printed. Never log the user ID or tokens.
"""

import json
import pathlib
import re
import subprocess
import sys


DATA = pathlib.Path("/srv/homelab/hermes")


def env_values(text):
    values = {}
    for line in text.splitlines():
        match = re.match(r"^\s*([A-Z][A-Z0-9_]*)\s*=\s*(.*?)\s*$", line)
        if match:
            values[match.group(1)] = match.group(2).strip("\"'")
    return values


def main():
    env_file = DATA / ".env"
    if not env_file.is_file():
        raise ValueError("Hermes environment file is absent")
    values = env_values(env_file.read_text())
    container = subprocess.run(
        ["docker", "inspect", "hermes", "--format", "{{json .Config.Env}}"],
        check=True, capture_output=True, text=True,
    )
    values.update(env_values("\n".join(json.loads(container.stdout))))
    allowed = [part.strip() for part in values.get("TELEGRAM_ALLOWED_USERS", "").split(",") if part.strip()]
    if len(allowed) != 1 or not allowed[0].isdigit():
        raise ValueError("Telegram must allow exactly one numeric user ID")
    for name in ("TELEGRAM_ALLOW_ALL_USERS", "GATEWAY_ALLOW_ALL_USERS"):
        if values.get(name, "").lower() in ("1", "true", "yes", "on"):
            raise ValueError("An allow-all flag is enabled")
    for name in ("GATEWAY_ALLOWED_USERS", "TELEGRAM_GROUP_ALLOWED_USERS", "TELEGRAM_GROUP_ALLOWED_CHATS"):
        if values.get(name, "").strip():
            raise ValueError("A secondary gateway or group allowlist is configured")
    config_file = DATA / "config.yaml"
    if not config_file.is_file() or re.search(r"(?m)^\s*allow_all_users:\s*(true|yes|on)\s*$", config_file.read_text(), re.I):
        raise ValueError("Hermes configuration is absent or enables allow-all access")
    for directory in (DATA / "pairing", DATA / "platforms" / "pairing"):
        if directory.exists() and any(path.is_file() for path in directory.rglob("*")):
            raise ValueError("A paired messaging identity is present")
    print("Telegram gate: one allowed user, no broad grants or pairings")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print("Telegram gate failed: " + str(exc), file=sys.stderr)
        sys.exit(1)
