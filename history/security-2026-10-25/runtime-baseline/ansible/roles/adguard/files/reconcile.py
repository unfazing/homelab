#!/usr/bin/env python3
"""Bootstrap and reconcile the local-only AdGuard Home API from Ansible policy."""

import argparse
import base64
import json
import time
import urllib.error
import urllib.request
from pathlib import Path


class AdGuardAPI:
    def __init__(self, username: str, password: str, web_address: str, web_port: int):
        credential = base64.b64encode(f"{username}:{password}".encode()).decode()
        self.authorization = f"Basic {credential}"
        self.base = f"http://{web_address}:{web_port}/control"

    def request(self, path: str, method: str = "GET", body=None, auth: bool = True):
        data = None if body is None else json.dumps(body).encode()
        headers = {"Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        if auth:
            headers["Authorization"] = self.authorization
        request = urllib.request.Request(
            f"{self.base}/{path}", data=data, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                content = response.read()
                if not content:
                    return response.status, None
                try:
                    return response.status, json.loads(content)
                except json.JSONDecodeError:
                    # The first-install endpoint returns plain-text success.
                    return response.status, None
        except urllib.error.HTTPError as error:
            # Do not include response bodies: they may reflect credentials or policy.
            return error.code, None

    def require(self, path: str, method: str = "GET", body=None, auth: bool = True):
        status, response = self.request(path, method, body, auth)
        if status != 200:
            raise RuntimeError(f"AdGuard {method} /{path} returned HTTP {status}")
        return response


def bootstrap(
    api: AdGuardAPI,
    policy: dict,
    username: str,
    password: str,
    dns_address: str,
    web_address: str,
    web_port: int,
):
    status, _ = api.request("install/get_addresses", auth=False)
    if status in (403, 404):
        # Installed versions may hide the setup endpoint with either response.
        # The HTTP listener can open before the DNS engine finishes loading.
        for _ in range(30):
            current_status, state = api.request("status")
            if current_status == 200 and state and state.get("running"):
                return 0
            if current_status in (401, 403):
                raise RuntimeError("AdGuard administrator authentication failed")
            time.sleep(2)
        raise RuntimeError("AdGuard setup is unavailable but the authenticated API is unhealthy")
    if status != 200:
        raise RuntimeError(f"AdGuard install detection returned HTTP {status}")
    api.require(
        "install/configure",
        method="POST",
        auth=False,
        body={
            "web": {"ip": web_address, "port": web_port},
            "dns": {"ip": dns_address, "port": 53},
            "username": username,
            "password": password,
            "language": "en",
        },
    )
    for _ in range(30):
        status, state = api.request("status")
        if status == 200 and state and state.get("running"):
            return 1
        time.sleep(2)
    raise RuntimeError("AdGuard did not become authenticated and healthy after bootstrap")


def reconcile_rewrites(api: AdGuardAPI, desired: list[dict]) -> int:
    """Converge the complete rewrite set, reporting only real API changes."""
    desired_pairs = {(item["domain"], item["answer"]) for item in desired}
    current = api.require("rewrite/list")
    current_pairs = {(item["domain"], item["answer"]) for item in current}
    changed = 0

    for item in current:
        if (item["domain"], item["answer"]) not in desired_pairs:
            api.require("rewrite/delete", "POST", item)
            changed += 1
    for item in desired:
        if (item["domain"], item["answer"]) not in current_pairs:
            api.require("rewrite/add", "POST", item)
            changed += 1

    settings = api.require("rewrite/settings")
    if not settings.get("enabled"):
        api.require("rewrite/settings/update", "PUT", {"enabled": True})
        changed += 1
    return changed


def reconcile(api: AdGuardAPI, policy: dict, address: str, web_port: int):
    changed = 0
    status = api.require("status")
    if not status.get("running") or status.get("dns_port") != 53:
        raise RuntimeError("AdGuard DNS is not running on port 53")
    if address not in status.get("dns_addresses", []):
        raise RuntimeError("AdGuard DNS is not bound to the access VM address")
    if status.get("http_port") != web_port:
        raise RuntimeError("AdGuard admin API is not on the expected port")

    desired_dns = dict(policy["dns"], protection_enabled=True)
    current_dns = api.require("dns_info")
    # The API reports the default load-balancing mode as an empty string.
    if current_dns.get("upstream_mode") == "":
        current_dns["upstream_mode"] = "load_balance"
    if any(current_dns.get(key) != value for key, value in desired_dns.items()):
        api.require("dns_config", "POST", desired_dns)
        changed += 1

    desired_filtering = policy["filtering"]
    filtering = api.require("filtering/status")
    if any(filtering.get(key) != desired_filtering[key] for key in ("enabled", "interval")):
        api.require(
            "filtering/config",
            "POST",
            {key: desired_filtering[key] for key in ("enabled", "interval")},
        )
        changed += 1

    desired_filters = {item["url"]: item for item in policy["filters"]}
    current_filters = {item["url"]: item for item in filtering.get("filters", [])}
    for url in current_filters.keys() - desired_filters.keys():
        api.require("filtering/remove_url", "POST", {"url": url})
        changed += 1
    for url, item in desired_filters.items():
        if url not in current_filters:
            api.require(
                "filtering/add_url",
                "POST",
                {"name": item["name"], "url": url, "whitelist": False},
            )
            changed += 1
    filtering = api.require("filtering/status")
    current_filters = {item["url"]: item for item in filtering.get("filters", [])}
    for url, item in desired_filters.items():
        current = current_filters.get(url)
        if current is None:
            raise RuntimeError("AdGuard did not retain an expected filter list")
        if current["enabled"] != item["enabled"] or current["name"] != item["name"]:
            api.require(
                "filtering/set_url",
                "POST",
                {"url": url, "whitelist": False, "data": item},
            )
            changed += 1
    if filtering.get("user_rules", []) != desired_filtering["user_rules"]:
        api.require(
            "filtering/set_rules",
            "POST",
            {"rules": desired_filtering["user_rules"]},
        )
        changed += 1
    if filtering.get("whitelist_filters"):
        raise RuntimeError("Unexpected whitelist filter requires a reviewed migration")

    changed += reconcile_rewrites(api, policy["rewrites"])

    for endpoint, wanted in (
        ("querylog", policy["querylog"]),
        ("stats", policy["statistics"]),
    ):
        current = api.require(f"{endpoint}/config")
        if any(current.get(key) != value for key, value in wanted.items()):
            api.require(f"{endpoint}/config/update", "PUT", dict(current, **wanted))
            changed += 1

    return changed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--password-file", type=Path, required=True)
    parser.add_argument("--username", required=True)
    parser.add_argument("--dns-address", required=True)
    parser.add_argument("--web-address", required=True)
    parser.add_argument("--web-port", type=int, required=True)
    args = parser.parse_args()
    policy = json.loads(args.policy.read_text())
    password = args.password_file.read_text().strip()
    if len(password) < 9:
        raise RuntimeError("AdGuard administrator password must contain at least 9 characters")
    api = AdGuardAPI(args.username, password, args.web_address, args.web_port)
    changed = bootstrap(
        api,
        policy,
        args.username,
        password,
        args.dns_address,
        args.web_address,
        args.web_port,
    )
    changed += reconcile(api, policy, args.dns_address, args.web_port)
    print(f"AdGuard policy converged; changed={changed}")


if __name__ == "__main__":
    main()
