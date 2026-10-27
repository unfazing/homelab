#!/usr/bin/env python3
"""Local privileged reader; export only approved metadata, never raw Caddy JSON."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from fnmatch import fnmatchcase
import json
import math
import os
from pathlib import Path
import re
import socket
import ssl
import subprocess
import time
from urllib.request import Request, urlopen

ROOT = Path('/opt/homelab/homepage')
OUTPUT = Path('/var/lib/homelab/homepage-observer/snapshot.json')
SECRETS = Path('/etc/homelab/homepage')


def safe_dial(value):
    # No URL credentials, headers, socket paths or dynamic placeholders.
    return value if isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_.:\[\]-]{1,160}', value) else '[dynamic/private destination]'


def extract_routes(config, domain):
    found = {}
    suffix = '.home.' + domain

    def record(hosts, handler):
        if hosts is None:
            return
        kind = handler.get('handler')
        if kind not in ('reverse_proxy', 'static_response'):
            return
        target = ', '.join(sorted({safe_dial(u.get('dial')) for u in handler.get('upstreams', [])})) if kind == 'reverse_proxy' else 'response ' + str(handler.get('status_code', 200))
        for host in hosts:
            if host.endswith(suffix) and re.fullmatch(r'(?:\*\.)?[a-z0-9.-]+', host):
                found.setdefault(host, set()).add(target or 'dynamic upstream')

    def walk(value, hosts=None):
        if isinstance(value, list):
            for child in value:
                walk(child, hosts)
        elif isinstance(value, dict):
            matches = value.get('match')
            if matches:
                for match in matches:  # Caddy match sets are OR; nested routes are AND.
                    own = match.get('host')
                    selected = hosts
                    if own is not None:
                        if hosts is None:
                            selected = own
                        else:
                            selected = {candidate for a in hosts for b in own
                                        for candidate in (a, b)
                                        if fnmatchcase(candidate, a) and fnmatchcase(candidate, b)}
                    record(selected, value)
                    for key, child in value.items():
                        if key != 'match':
                            walk(child, selected)
            else:
                record(hosts, value)
                for child in value.values():
                    walk(child, hosts)

    for server in config.get('apps', {}).get('http', {}).get('servers', {}).values():
        if any(str(address).endswith(':443') for address in server.get('listen', [])):
            walk(server.get('routes', []))
    return [{'hostname': host, 'destination': '; '.join(sorted(targets)),
             'kind': 'wildcard / fallback' if '*' in host else 'exact hostname'}
            for host, targets in sorted(found.items())]


def tls_policy(config):
    result = set()
    policies = config.get('apps', {}).get('tls', {}).get('automation', {}).get('policies', [])
    for policy in policies:
        for issuer in policy.get('issuers', []):
            module = issuer.get('module')
            if module == 'acme':
                dns = issuer.get('challenges', {}).get('dns')
                provider = dns.get('provider', {}).get('name') if isinstance(dns, dict) else None
                result.add('ACME / DNS-01' + (' / Cloudflare' if provider == 'cloudflare' else '') if dns else 'ACME / automatic challenge')
            elif module in ('internal', 'zerossl'):
                result.add(module)
    return ', '.join(sorted(result)) or 'Caddy automatic HTTPS / inspect policy'


def probe_tls(route, address, now):
    row = dict(route)
    if '*' in row['hostname']:
        row.update(tls_status='not probed', certificate='Wildcard matcher; concrete routes probed separately')
        return row
    try:
        with socket.create_connection((address, 443), timeout=3) as connection:
            with ssl.create_default_context().wrap_socket(connection, server_hostname=row['hostname']) as secured:
                cert = secured.getpeercert()
                expiry = ssl.cert_time_to_seconds(cert['notAfter'])
                issuer = dict(part for group in cert.get('issuer', ()) for part in group)
                row.update(tls_status='valid', issuer=issuer.get('commonName', 'Unknown issuer'),
                           expires_at=datetime.fromtimestamp(expiry, timezone.utc).isoformat(),
                           days_remaining=math.floor((expiry - now) / 86400), protocol=secured.version())
                row['certificate'] = f"{row['issuer']} · {row['days_remaining']}d · {row['expires_at'][:10]} · {row['protocol']}"
    except Exception as exc:
        # Error messages may include configuration data; export category only.
        row.update(tls_status='FAILED: ' + type(exc).__name__, certificate='Unavailable / TLS probe failed')
    return row


def human_bytes(value):
    value = float(value)
    for unit in ('B', 'KiB', 'MiB', 'GiB', 'TiB'):
        if abs(value) < 1024 or unit == 'TiB':
            return f'{value:.1f} {unit}'
        value /= 1024


def vm_summary(current, previous, now):
    raw = {key: current[key] for key in ('status', 'cpu', 'cpus', 'mem', 'memhost', 'maxmem', 'uptime', 'netin', 'netout', 'diskread', 'diskwrite') if key in current}
    uptime = int(current.get('uptime', 0))
    running = current.get('status') == 'running'
    row = {'checked_at': now, 'raw': raw, 'status': str(current.get('status', 'unknown')),
           'cpu': f"{100 * current.get('cpu', 0):.1f}% / {current.get('cpus', '?')} vCPU" if running else '—',
           'memory': human_bytes(current.get('memhost', current.get('mem', 0))) + ' / ' + human_bytes(current.get('maxmem', 0)),
           'uptime': f'{uptime // 86400}d {uptime % 86400 // 3600}h {uptime % 3600 // 60}m' if running else '—'}
    elapsed = now - previous.get('checked_at', now)
    old = previous.get('raw', {})
    for source, dest in (('netin', 'network_in'), ('netout', 'network_out'), ('diskread', 'disk_read'), ('diskwrite', 'disk_write')):
        valid = running and 1 <= elapsed <= 180 and source in raw and source in old and raw[source] >= old[source] and uptime >= old.get('uptime', uptime)
        row[dest] = human_bytes((raw[source] - old[source]) / elapsed) + '/s' if valid else 'warming up' if running else '—'
    return row


def proxmox_context(cafile):
    context = ssl.create_default_context(cafile=str(cafile))
    # This existing private Proxmox CA lacks the newer strict key-usage extension.
    # Match Node/OpenSSL's legacy validation for this CA only; retain chain and
    # hostname verification. Public certificate probes keep default strict flags.
    context.verify_flags &= ~ssl.VERIFY_X509_STRICT
    return context


def collect(config, previous, now):
    result = dict(previous)
    result.update(generated_at=now, collector_status='ok', errors=[])
    try:
        raw = subprocess.check_output(['docker', 'exec', 'caddy', 'wget', '-qO-', 'http://127.0.0.1:2019/config/'], timeout=5)
        active = json.loads(raw)
        routes = extract_routes(active, config['domain'])
        policy = tls_policy(active)
        with ThreadPoolExecutor(max_workers=8) as workers:
            rows = list(workers.map(lambda route: probe_tls(route, config['caddy_address'], now), routes[:64]))
        for row in rows:
            row['tls_policy'] = policy
        result.update(routes=rows, caddy_checked_at=now, tls_policy=policy,
                      routes_truncated=len(routes) > 64)
    except Exception as exc:
        result['errors'].append('Caddy collection: ' + type(exc).__name__)
    context = proxmox_context(SECRETS / 'proxmox-ca.pem')
    token = (SECRETS / 'proxmox-token').read_text().strip()
    vms = dict(previous.get('vms', {}))
    for vm in config['vms']:
        ident = str(vm['id'])
        try:
            req = Request(f"https://192.168.1.10:8006/api2/json/nodes/blue/qemu/{ident}/status/current",
                          headers={'Authorization': 'PVEAPIToken=homepage@pve!dashboard=' + token})
            with urlopen(req, context=context, timeout=4) as response:
                data = json.load(response)['data']
            vms[ident] = vm_summary(data, vms.get(ident, {}), now)
            vms[ident]['name'] = vm['name']
        except Exception as exc:
            result['errors'].append('VM ' + ident + ': ' + type(exc).__name__)
    result['vms'] = vms
    if result['errors']:
        result['collector_status'] = 'partial failure'
    return result


def main():
    config = json.loads((ROOT / 'observer.json').read_text())
    try:
        previous = json.loads(OUTPUT.read_text())
    except (FileNotFoundError, ValueError):
        previous = {}
    snapshot = collect(config, previous, time.time())
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT.with_suffix('.tmp')
    temporary.write_text(json.dumps(snapshot, separators=(',', ':')))
    os.chown(temporary, 0, 10001)
    os.chmod(temporary, 0o640)
    os.replace(temporary, OUTPUT)


if __name__ == '__main__':
    main()
