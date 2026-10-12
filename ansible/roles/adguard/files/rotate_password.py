#!/usr/bin/env python3
"""Rotate the AdGuard web password while keeping DNS config recoverable."""

import argparse
import base64
import json
import os
import re
import socket
import stat
import struct
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path


def replace_user_hash(config: str, username: str, password_hash: str) -> str:
    lines = config.splitlines(keepends=True)
    starts = [i for i, line in enumerate(lines) if line.strip() == "users:" and line == "users:\n"]
    if len(starts) != 1:
        raise RuntimeError("Expected exactly one top-level users section")
    start = starts[0] + 1
    end = next(
        (i for i in range(start, len(lines)) if lines[i].strip() and not lines[i][0].isspace()),
        len(lines),
    )
    body = lines[start:end]
    names = [line.strip().removeprefix("- name:").strip().strip("\"'") for line in body if re.match(r"^\s+- name:", line)]
    password_indexes = [i for i, line in enumerate(body) if re.match(r"^\s+password:", line)]
    if names != [username] or len(password_indexes) != 1:
        raise RuntimeError("Expected exactly one matching AdGuard web user")
    index = start + password_indexes[0]
    prefix = lines[index].split("password:", 1)[0]
    lines[index] = f"{prefix}password: {password_hash}\n"
    return "".join(lines)


def atomic_write(path: Path, content: bytes, *, mode: int, uid: int, gid: int) -> None:
    descriptor, temp_name = tempfile.mkstemp(prefix=".adguard-rotate-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            os.fchmod(stream.fileno(), mode)
            os.fchown(stream.fileno(), uid, gid)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def compose(project: Path, *args: str) -> None:
    result = subprocess.run(
        ["docker", "compose", "--project-directory", str(project), *args],
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise RuntimeError("AdGuard Compose operation failed")


def web_healthy(username: str, password: str, address: str, port: int) -> bool:
    credential = base64.b64encode(f"{username}:{password}".encode()).decode()
    request = urllib.request.Request(
        f"http://{address}:{port}/control/status",
        headers={"Authorization": f"Basic {credential}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            return response.status == 200 and json.load(response).get("running") is True
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return False


def dns_answers(address: str, name: str, expected_ip: str) -> bool:
    query_id = os.urandom(2)
    labels = name.rstrip(".").encode("ascii").split(b".")
    question = b"".join(bytes([len(label)]) + label for label in labels) + b"\x00\x00\x01\x00\x01"
    packet = query_id + struct.pack("!HHHHH", 0x0100, 1, 0, 0, 0) + question
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(3)
        sock.sendto(packet, (address, 53))
        response, _ = sock.recvfrom(4096)
    if len(response) < 12 or response[:2] != query_id:
        return False
    flags, qdcount, ancount = struct.unpack_from("!HHH", response, 2)
    if not flags & 0x8000 or flags & 0x000F or qdcount != 1:
        return False
    offset = 12
    for _ in range(qdcount):
        offset = skip_dns_name(response, offset) + 4
    for _ in range(ancount):
        offset = skip_dns_name(response, offset)
        if offset + 10 > len(response):
            return False
        record_type, record_class, _, length = struct.unpack_from("!HHIH", response, offset)
        offset += 10
        if offset + length > len(response):
            return False
        if record_type == 1 and record_class == 1 and length == 4:
            if socket.inet_ntoa(response[offset : offset + length]) == expected_ip:
                return True
        offset += length
    return False


def skip_dns_name(packet: bytes, offset: int) -> int:
    while offset < len(packet):
        length = packet[offset]
        if length == 0:
            return offset + 1
        if length & 0xC0 == 0xC0:
            return offset + 2
        if length & 0xC0 or offset + length + 1 > len(packet):
            break
        offset += length + 1
    raise RuntimeError("Invalid DNS response")


def wait_healthy(username: str, password: str, address: str, port: int, dns_address: str, name: str, expected_ip: str) -> None:
    for _ in range(30):
        if web_healthy(username, password, address, port):
            try:
                if dns_answers(dns_address, name, expected_ip):
                    return
            except (OSError, RuntimeError):
                pass
        time.sleep(2)
    raise RuntimeError("AdGuard login or private DNS did not become healthy")


def read_password(path: Path) -> str:
    content = path.read_text(encoding="utf-8")
    if not content.endswith("\n") or content.count("\n") != 1:
        raise RuntimeError("Password file must contain exactly one newline-terminated line")
    password = content[:-1]
    if any(ord(character) < 32 or ord(character) == 127 for character in password):
        raise RuntimeError("Password contains a control character")
    return password


def rotate(args: argparse.Namespace) -> None:
    current_file = Path(args.current_password_file)
    expected_file = Path(args.expected_password_file)
    new_file = Path(args.new_password_file)
    config_file = Path(args.config_file)
    backup_file = Path(args.backup_file)
    if backup_file.exists():
        raise RuntimeError("A prior AdGuard rotation backup exists; inspect it before retrying")
    current = read_password(current_file)
    expected = read_password(expected_file)
    replacement = read_password(new_file)
    if current != expected or len(current) < 9 or len(replacement) < 9 or replacement == current:
        raise RuntimeError("Current or replacement password failed preflight")
    if not web_healthy(args.username, current, args.web_address, args.web_port):
        raise RuntimeError("Current AdGuard administrator login failed preflight")
    original = config_file.read_bytes()
    metadata = config_file.stat()
    hashed = subprocess.run(
        ["htpasswd", "-B", "-C", "10", "-i", "-n", args.username],
        input=f"{replacement}\n".encode(),
        capture_output=True,
        check=False,
    )
    if hashed.returncode or not hashed.stdout.startswith(f"{args.username}:$2".encode()):
        raise RuntimeError("Could not create the bcrypt password hash")
    new_config = replace_user_hash(
        original.decode("utf-8"), args.username, hashed.stdout.decode().strip().split(":", 1)[1]
    ).encode("utf-8")

    descriptor = os.open(backup_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(original)
        stream.flush()
        os.fsync(stream.fileno())
    stopped = False
    secret_committed = False
    try:
        compose(Path(args.compose_dir), "stop", "--timeout", "30", "adguard")
        stopped = True
        atomic_write(
            config_file,
            new_config,
            mode=stat.S_IMODE(metadata.st_mode),
            uid=metadata.st_uid,
            gid=metadata.st_gid,
        )
        compose(Path(args.compose_dir), "up", "--detach", "--no-deps", "adguard")
        wait_healthy(
            args.username, replacement, args.web_address, args.web_port,
            args.dns_address, args.verify_name, args.expected_ip,
        )
        secret_metadata = current_file.stat()
        atomic_write(
            current_file,
            f"{replacement}\n".encode(),
            mode=0o600,
            uid=secret_metadata.st_uid,
            gid=secret_metadata.st_gid,
        )
        secret_committed = True
    except Exception as error:
        if stopped and not secret_committed:
            rollback_error = None
            try:
                compose(Path(args.compose_dir), "stop", "--timeout", "30", "adguard")
                atomic_write(
                    config_file, original,
                    mode=stat.S_IMODE(metadata.st_mode),
                    uid=metadata.st_uid,
                    gid=metadata.st_gid,
                )
                compose(Path(args.compose_dir), "up", "--detach", "--no-deps", "adguard")
                wait_healthy(
                    args.username, current, args.web_address, args.web_port,
                    args.dns_address, args.verify_name, args.expected_ip,
                )
            except Exception as failure:
                rollback_error = failure
            if rollback_error is not None:
                raise RuntimeError(
                    f"Rotation and rollback failed; recover from {backup_file}"
                ) from error
            backup_file.unlink()
            raise RuntimeError("Rotation failed; prior password and DNS were restored") from error
        if not stopped:
            backup_file.unlink()
        raise RuntimeError("Rotation failed before the password changed") from error
    if secret_committed:
        try:
            backup_file.unlink()
        except OSError:
            print(f"Warning: remove the old-password backup at {backup_file} after inspection")
        print("AdGuard password rotated; new login and private DNS verified")


def main() -> None:
    parser = argparse.ArgumentParser()
    for option in (
        "current-password-file", "expected-password-file", "new-password-file",
        "config-file", "backup-file", "compose-dir", "username", "web-address",
        "dns-address", "verify-name", "expected-ip",
    ):
        parser.add_argument(f"--{option}", required=True)
    parser.add_argument("--web-port", type=int, required=True)
    try:
        rotate(parser.parse_args())
    except Exception as error:
        raise SystemExit(f"AdGuard password rotation: {error}") from None


if __name__ == "__main__":
    main()
