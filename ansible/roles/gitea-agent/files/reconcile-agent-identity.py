#!/usr/bin/env python3
"""Reconcile one narrowly scoped Gitea identity through the local Gitea API.

The temporary administrator token exists only in this process and is revoked
before exit. This script is installed on the Gitea VM by Ansible, not run from
the operator's laptop or from the Hermes container.
"""

import json
import re
import secrets
import sqlite3
import subprocess
import sys
from urllib import error, parse, request


class ProvisionError(Exception):
    pass


def require(condition, message):
    if not condition:
        raise ProvisionError(message)


def api(base, token, method, path, payload=None, accepted=(200,)):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = request.Request(
        base + path,
        data=data,
        method=method,
        headers={
            "Authorization": "token " + token,
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )
    try:
        with request.urlopen(req, timeout=15) as response:
            status = response.status
            body = response.read()
    except error.HTTPError as exc:
        status = exc.code
        body = exc.read(1024)
    except error.URLError as exc:
        raise ProvisionError(f"Gitea API unavailable at {path}: {exc.reason}") from exc
    if status not in accepted:
        detail = body.decode("utf-8", "replace")[:512]
        raise ProvisionError(f"Gitea API {method} {path} returned {status}: {detail}")
    return status, json.loads(body) if body else None


def provision(config, base, token):
    username = config["username"]
    email = config["email"]
    admin_username = config["admin_username"]
    repo_limit = config["repo_limit"]
    key = config["public_key"].strip()
    title = config["key_title"]
    for value in (username, admin_username, title):
        require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,39}", value), "Invalid Gitea identity")
    require(type(repo_limit) is int and 0 < repo_limit <= 100, "Repository quota must be between 1 and 100")
    require(re.fullmatch(r"ssh-ed25519 [A-Za-z0-9+/=]+(?: .+)?", key), "Expected one Ed25519 public key")
    require(re.fullmatch(r"[^@\s]+@[^@\s]+", email), "Invalid account email")
    user_path = "/users/" + parse.quote(username, safe="")
    changed = []

    status, user = api(base, token, "GET", user_path, accepted=(200, 404))
    if status == 404:
        _, user = api(base, token, "POST", "/admin/users", {
            "username": username,
            "email": email,
            "password": secrets.token_urlsafe(48),
            "must_change_password": False,
            "send_notify": False,
            "restricted": True,
            "visibility": "private",
        }, accepted=(201,))
        changed.append("user")
    require(user.get("login") == username, "Unexpected Gitea account identity")
    require(user.get("email", "").lower() == email.lower(), "Existing account has a different email")
    require(user.get("is_admin") is False, "Agent account must not be an administrator")
    require(user.get("restricted") is True, "Agent account must remain restricted")
    require(user.get("active") is True, "Agent account is disabled")
    # The public User API omits max_repo_creation; query the local SQLite DB
    # read-only so a changed quota is reported accurately to Ansible.
    database = sqlite3.connect("file:/srv/homelab/gitea/gitea/gitea.db?mode=ro", uri=True)
    try:
        row = database.execute("SELECT max_repo_creation FROM user WHERE name = ?", (username,)).fetchone()
    finally:
        database.close()
    require(row is not None, "Agent account is absent from the local database")
    if row[0] != repo_limit:
        changed.append("repository creation quota")
    api(base, token, "PATCH", "/admin/users/" + parse.quote(username, safe=""), {
        "admin": False,
        "restricted": True,
        "visibility": "private",
        "max_repo_creation": repo_limit,
        "allow_create_organization": False,
        "allow_git_hook": False,
        "allow_import_local": False,
    }, accepted=(200,))

    key_fields = key.split()[:2]
    _, keys = api(base, token, "GET", user_path + "/keys?limit=100", accepted=(200,))
    matching = [item for item in keys if item.get("key", "").split()[:2] == key_fields]
    require(not any(item.get("title") == title and item.get("key", "").split()[:2] != key_fields for item in keys),
            "Gitea key title already refers to a different key; rotate explicitly")
    if not matching:
        api(base, token, "POST", "/admin/users/" + parse.quote(username, safe="") + "/keys", {
            "key": key,
            "title": title,
            "read_only": False,
        }, accepted=(201,))
        changed.append("SSH public key")
    else:
        require(all(item.get("read_only") is False for item in matching), "Agent SSH key is read-only")

    # The personal access token is an HTTP API credential, separate from Git
    # SSH. Never replace an existing token silently: its raw value cannot be
    # recovered if the agents-side copy is lost.
    token_name = "homelab-hermes-issues-prs"
    token_scopes = {"write:issue", "write:repository"}
    database = sqlite3.connect("file:/srv/homelab/gitea/gitea/gitea.db?mode=ro", uri=True)
    try:
        rows = database.execute(
            "SELECT scope FROM access_token WHERE uid = ? AND name = ?",
            (user["id"], token_name),
        ).fetchall()
    finally:
        database.close()
    require(len(rows) <= 1, "Duplicate agent API tokens exist; inspect them before proceeding")
    api_token = None
    if rows:
        require(set(rows[0][0].split(",")) == token_scopes,
                "Existing agent API token has unexpected scopes; rotate it explicitly")
    else:
        created = subprocess.run(
            ["docker", "compose", "--project-directory", config["compose_dir"], "exec", "-T", "--user", "git",
             "gitea", "gitea", "admin", "user", "generate-access-token", "--username", username,
             "--token-name", token_name, "--raw", "--scopes", ",".join(sorted(token_scopes))],
            check=True, capture_output=True, text=True,
        )
        api_token = created.stdout.strip()
        require(re.fullmatch(r"[A-Za-z0-9_.-]{32,}", api_token), "Gitea did not return a raw agent API token")
        changed.append("scoped HTTP API token")

    return {"changed": bool(changed), "applied": changed, "api_token": api_token}


def main():
    config = json.load(sys.stdin)
    base = "http://" + config["api_address"] + ":3000/api/v1"
    token_name = "iac-agent-" + secrets.token_hex(8)
    cmd = ["docker", "compose", "--project-directory", config["compose_dir"], "exec", "-T", "--user", "git", "gitea",
           "gitea", "admin", "user", "generate-access-token", "--username", config["admin_username"],
           "--token-name", token_name, "--raw", "--scopes", "all"]
    created = subprocess.run(cmd, check=True, capture_output=True, text=True)
    token = created.stdout.strip()
    require(re.fullmatch(r"[A-Za-z0-9_.-]{32,}", token), "Gitea did not return a raw temporary token")
    result = None
    failure = None
    try:
        result = provision(config, base, token)
    except Exception as exc:  # Always attempt to revoke the temporary credential.
        failure = exc
    try:
        api(base, token, "DELETE", "/token", accepted=(204,))
    except Exception as exc:
        raise ProvisionError(f"Temporary admin token {token_name} could not be revoked; revoke it in Gitea: {exc}") from exc
    if failure:
        raise failure
    print(json.dumps(result))


if __name__ == "__main__":
    try:
        main()
    except (ProvisionError, subprocess.CalledProcessError) as exc:
        print(f"Agent identity reconciliation failed: {exc}", file=sys.stderr)
        sys.exit(1)
