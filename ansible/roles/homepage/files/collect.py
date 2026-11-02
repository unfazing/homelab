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
HOST_KEYS = Path('/etc/homelab/homepage-observer')


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


def capacity(total, used, available):
    values = [total, used, available]
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v >= 0 for v in values) or total <= 0 or used > total or available > total:
        raise ValueError('Invalid capacity totals')
    return f'{human_bytes(used)} / {human_bytes(total)} · {human_bytes(available)} free'


def blue_summary(status, now):
    memory, swap, root = status['memory'], status['swap'], status['rootfs']
    total, available = memory['total'], memory['available']
    capacity(total, total - available, available)
    capacity(swap['total'], swap['used'], swap['free']) if swap['total'] else None
    load = [float(v) for v in status['loadavg']]
    if len(load) != 3 or not all(math.isfinite(v) and v >= 0 for v in load):
        raise ValueError('Invalid node load')
    uptime = int(status['uptime'])
    cpus = int(status['cpuinfo']['cpus'])
    if uptime < 0 or cpus <= 0:
        raise ValueError('Invalid node counters')
    return {'checked_at': now, 'status': 'online', 'cpu': 'unknown', 'cpu_threads': cpus,
            'load': ' / '.join(f'{v:.2f}' for v in load),
            'memory': human_bytes(total - available) + ' / ' + human_bytes(total),
            'swap': human_bytes(swap['used']) + ' / ' + human_bytes(swap['total']),
            'uptime': f'{uptime // 86400}d {uptime % 86400 // 3600}h {uptime % 3600 // 60}m',
            'root_disk': capacity(root['total'], root['used'], root['avail'])}


def blue_activity(samples, cpus, now):
    valid = [r for r in samples if isinstance(r.get('time'), (int, float)) and 0 <= now - r['time'] <= 180
             and all(isinstance(r.get(k), (int, float)) and not isinstance(r[k], bool) and math.isfinite(r[k]) and r[k] >= 0
                     for k in ['cpu', 'netin', 'netout', 'iowait', 'arcsize'])]
    if not valid:
        raise ValueError('No fresh complete RRD sample')
    sample = max(valid, key=lambda r: r['time'])
    if sample['cpu'] > 1 or sample['iowait'] > 1:
        raise ValueError('Invalid RRD percentage')
    return {'activity_checked_at': sample['time'], 'cpu_checked_at': sample['time'],
            'cpu': f"{100 * sample['cpu']:.1f}% / {cpus} threads",
            'network_in': human_bytes(sample['netin']) + '/s', 'network_out': human_bytes(sample['netout']) + '/s',
            'io_wait': f"{100 * sample['iowait']:.2f}%", 'arc': human_bytes(sample['arcsize'])}


def scrub_summary(value):
    # Do not export arbitrary pool error messages, filenames or suggested commands.
    match = re.fullmatch(r'(scrub|resilver) repaired ([0-9.]+[KMGTPE]?B) in [0-9:]+ with ([0-9]+) errors on (.+)', value or '')
    if match:
        try:
            date = datetime.strptime(match[4], '%a %b %d %H:%M:%S %Y').date().isoformat()
            return f'{date} · {match[3]} errors · repaired {match[2]}'
        except ValueError:
            pass
    if re.match(r'(scrub|resilver) in progress', value or ''):
        return 'In progress'
    return 'No completed scrub reported · inspect Proxmox'


def blue_storage(root_disk, stores, pools, detail, pool_name):
    store = next(row for row in stores if row['storage'] == 'local-lvm')
    pool = next(row for row in pools if row['name'] == pool_name)
    health = pool.get('health')
    if health not in ['ONLINE', 'DEGRADED', 'FAULTED', 'OFFLINE', 'REMOVED', 'UNAVAIL', 'SUSPENDED']:
        health = 'unknown'
    return [
        {'name': 'Root filesystem', 'summary': root_disk},
        {'name': 'VM OS disks', 'summary': capacity(store['total'], store['used'], store['avail']) + (' · INACTIVE' if not store.get('active') else '')},
        {'name': pool_name + ' capacity', 'summary': capacity(pool['size'], pool['alloc'], pool['free'])},
        {'name': pool_name + ' health', 'summary': health},
        {'name': 'Last scrub', 'summary': scrub_summary(detail.get('scan'))},
        {'name': 'Data errors', 'summary': 'none reported' if detail.get('errors') == 'No known data errors' else 'Inspect Proxmox for pool errors'},
    ]


def rate_summary(raw, previous, now, running=True):
    elapsed = now - previous.get('checked_at', now)
    old = previous.get('raw', {})
    result = {}
    same_boot = raw.get('boot_id') == old.get('boot_id')
    for source, dest in (('netin', 'network_in'), ('netout', 'network_out'), ('diskread', 'disk_read'), ('diskwrite', 'disk_write')):
        valid = running and same_boot and 1 <= elapsed <= 180 and source in raw and source in old and raw[source] >= old[source] and raw.get('uptime', 0) >= old.get('uptime', 0)
        result[dest] = human_bytes((raw[source] - old[source]) / elapsed) + '/s' if valid else 'warming up' if running else '—'
    return result


def vm_summary(current, previous, now):
    raw = {key: current[key] for key in ('status', 'cpu', 'cpus', 'mem', 'memhost', 'maxmem', 'uptime', 'netin', 'netout', 'diskread', 'diskwrite') if key in current}
    uptime = int(current.get('uptime', 0))
    running = current.get('status') == 'running'
    row = {'checked_at': now, 'raw': raw, 'status': str(current.get('status', 'unknown')),
           'cpu': f"{100 * current.get('cpu', 0):.1f}% / {current.get('cpus', '?')} vCPU" if running else '—',
           'memory': human_bytes(current.get('memhost', current.get('mem', 0))) + ' / ' + human_bytes(current.get('maxmem', 0)),
           'uptime': f'{uptime // 86400}d {uptime % 86400 // 3600}h {uptime % 3600 // 60}m' if running else '—'}
    row.update(rate_summary(raw, previous, now, running))
    return row


def service_summary(name, current, previous):
    """Strict aggregates only; sample ages belong to the service, not the SSH read."""
    fields = {'garage': ['bucketCount','totalObjectCount','totalObjectBytes','api_s3_request_counter','api_s3_error_counter'],
              'postgresql': ['databases','tables','database_bytes','transactions','connections','active','blocked','connection_limit','server_start']}[name]
    checked = current.get('checked_at')
    raw = current.get('values', {})
    if type(checked) is not int or checked <= 0 or not all(type(raw.get(k)) in (int,float) and math.isfinite(raw[k]) and 0 <= raw[k] <= 9e15 and int(raw[k]) == raw[k] for k in fields):
        return {}
    values = {k: int(raw[k]) for k in fields}
    row = {'checked_at': checked, 'raw': values}
    if current.get('error'):
        row['error'] = 'collection failed'
    old = previous.get('raw', {})
    elapsed = checked - previous.get('checked_at', checked)
    valid = 1 <= elapsed <= 180
    if name == 'garage':
        if current.get('health') not in ('healthy','degraded','unavailable'):
            return {}
        row.update(buckets=str(values['bucketCount']), objects=str(values['totalObjectCount']),
                   object_bytes=human_bytes(values['totalObjectBytes']), health=current['health'])
        counters = [('api_s3_request_counter','requests_per_min',60),('api_s3_error_counter','errors_per_min',60)]
    else:
        reset = current.get('reset_id')
        if not isinstance(reset,str) or not re.fullmatch(r'[a-f0-9]{32}',reset):
            return {}
        row['reset_id'] = reset
        valid = valid and reset == previous.get('reset_id') and values['server_start'] == old.get('server_start')
        row.update(databases=str(values['databases']),tables=str(values['tables']),
                   database_bytes=human_bytes(values['database_bytes']),
                   connections=f"{values['active']} / {values['connections']} / {values['connection_limit']}",
                   blocked=str(values['blocked']))
        counters = [('transactions','transactions_per_sec',1)]
    for source, target, scale in counters:
        usable = valid and source in old and values[source] >= old[source]
        row[target] = f"{scale * (values[source] - old[source]) / elapsed:.1f}" if usable else 'warming up'
        # Duplicate reads of the same service sample must retain its earlier rate.
        if elapsed == 0 and values == old and target in previous:
            row[target] = previous[target]
    return row


def host_summary(current, previous, now):
    """Build an explicit allowlist; never forward arbitrary remote JSON fields."""
    fields = ('uptime', 'cpus', 'cpu_total', 'cpu_idle', 'memory_total', 'memory_available',
              'swap_total', 'swap_free', 'netin', 'netout', 'diskread', 'diskwrite')
    if current.get('version') != 1 or not re.fullmatch(r'[a-f0-9-]{36}', current.get('boot_id', '')):
        raise ValueError('Unknown host report')
    for key in fields:
        if not isinstance(current.get(key), int) or isinstance(current[key], bool) or current[key] < 0:
            raise ValueError('Invalid host counter')
    if not current['cpus'] or not current['memory_total'] or current['cpu_idle'] > current['cpu_total'] or current['memory_available'] > current['memory_total'] or current['swap_free'] > current['swap_total']:
        raise ValueError('Invalid host totals')
    load = current.get('load')
    if not isinstance(load, list) or len(load) != 3 or not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v >= 0 for v in load):
        raise ValueError('Invalid load averages')
    raw = {key: current[key] for key in fields}
    raw['boot_id'] = current['boot_id']
    uptime = raw['uptime']
    row = {'checked_at': now, 'raw': raw, 'status': 'online',
           'cpu': 'warming up', 'load': ' / '.join(f'{v:.2f}' for v in load),
           'memory': human_bytes(raw['memory_total'] - raw['memory_available']) + ' / ' + human_bytes(raw['memory_total']),
           'swap': human_bytes(raw['swap_total'] - raw['swap_free']) + ' / ' + human_bytes(raw['swap_total']),
           'uptime': f'{uptime // 86400}d {uptime % 86400 // 3600}h {uptime % 3600 // 60}m'}
    old = previous.get('raw', {})
    elapsed = now - previous.get('checked_at', now)
    if 1 <= elapsed <= 180 and old.get('boot_id') == raw['boot_id'] and uptime >= old.get('uptime', 0):
        total = raw['cpu_total'] - old.get('cpu_total', raw['cpu_total'])
        idle = raw['cpu_idle'] - old.get('cpu_idle', raw['cpu_idle'])
        if total > 0 and 0 <= idle <= total:
            row['cpu'] = f"{100 * (total - idle) / total:.1f}% / {raw['cpus']} threads"
    row.update(rate_summary(raw, previous, now))
    row['filesystem_usage'] = {}
    for name in ['root', 'postgresql', 'garage']:
        disk = current.get('filesystems', {}).get(name, {})
        if disk.get('mounted') is not True:
            row[name + '_disk'] = 'NOT MOUNTED / unknown'
            row['filesystem_usage'][name] = {'mounted': False}
            continue
        if not all(isinstance(disk.get(k), int) and not isinstance(disk[k], bool) and disk[k] >= 0 for k in ['total', 'used', 'available']) or disk['total'] <= 0 or disk['used'] > disk['total'] or disk['available'] > disk['total']:
            raise ValueError('Invalid filesystem counters')
        row[name + '_disk'] = f"{human_bytes(disk['used'])} / {human_bytes(disk['total'])} · {human_bytes(disk['available'])} free"
        row['filesystem_usage'][name] = {'mounted': True,
            'used_total': human_bytes(disk['used']) + ' / ' + human_bytes(disk['total']),
            'available': human_bytes(disk['available']),
            'utilisation': f"{100 * disk['used'] / disk['total']:.1f}%"}
    row['services'] = {name: service_summary(name, current.get('storage_metrics', {}).get(name, {}), previous.get('services', {}).get(name, {})) for name in ['garage', 'postgresql']}
    return row


def host_ssh_command(target, command='metrics'):
    if not re.fullmatch(r'[a-z][a-z0-9_-]{0,31}', target['id']) or not re.fullmatch(r'[a-z_][a-z0-9_-]{0,31}', target['ssh_user']) or not re.fullmatch(r'[0-9.]+', target['address']):
        raise ValueError('Invalid SSH telemetry target')
    key = HOST_KEYS / ('host-' + target['id'] + '-key')
    known = HOST_KEYS / ('host-' + target['id'] + '-known_hosts')
    return ['ssh', '-F', '/dev/null', '-T', '-i', str(key),
        '-o', 'BatchMode=yes', '-o', 'IdentitiesOnly=yes', '-o', 'StrictHostKeyChecking=yes',
        '-o', 'UpdateHostKeys=no', '-o', 'UserKnownHostsFile=' + str(known),
        '-o', 'HostKeyAlgorithms=ssh-ed25519', '-o', 'ConnectTimeout=3', '-o', 'ConnectionAttempts=1',
        target['ssh_user'] + '@' + target['address'], command]


def read_host(target):
    response = subprocess.run(host_ssh_command(target),
        capture_output=True, text=True, timeout=8, check=True)
    if len(response.stdout) > 65536:
        raise ValueError('Oversize host report')
    return json.loads(response.stdout)


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
    pool_name = config.get('blue_zfs_pool', 'tank')
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_.-]{0,63}', pool_name):
        raise ValueError('Invalid pool target')
    paths = {'node': 'status', 'activity': 'rrddata?timeframe=hour&cf=AVERAGE', 'stores': 'storage',
             'pools': 'disks/zfs', 'pool': 'disks/zfs/' + pool_name}
    paths.update({'vm:' + str(vm['id']): 'qemu/' + str(vm['id']) + '/status/current' for vm in config['vms']})
    def query(path):
        req = Request('https://192.168.1.10:8006/api2/json/nodes/blue/' + path,
                      headers={'Authorization': 'PVEAPIToken=homepage@pve!dashboard=' + token})
        with urlopen(req, context=context, timeout=4) as response:
            return json.load(response)['data']
    responses = {}
    with ThreadPoolExecutor(max_workers=4) as workers:
        pending = {key: workers.submit(query, path) for key, path in paths.items()}
        for key, future in pending.items():
            try:
                responses[key] = future.result()
            except Exception as exc:
                result['errors'].append('Proxmox ' + key + ': ' + type(exc).__name__)
    vms = dict(previous.get('vms', {}))
    for vm in config['vms']:
        ident = str(vm['id'])
        try:
            data = responses['vm:' + ident]
            vms[ident] = vm_summary(data, vms.get(ident, {}), now)
            vms[ident]['name'] = vm['name']
        except Exception as exc:
            result['errors'].append('VM ' + ident + ': ' + type(exc).__name__)
    result['vms'] = vms
    old_blue = previous.get('hosts', {}).get('blue', {})
    blue = dict(old_blue)
    try:
        blue.update(blue_summary(responses['node'], now))
        blue.pop('error', None)
    except Exception as exc:
        blue['error'] = type(exc).__name__
        result['errors'].append('Blue status: ' + type(exc).__name__)
    try:
        blue.update(blue_activity(responses['activity'], blue['cpu_threads'], now))
        blue.pop('activity_error', None)
    except Exception as exc:
        blue['activity_error'] = type(exc).__name__
        result['errors'].append('Blue activity: ' + type(exc).__name__)
    try:
        # Root status and all storage reads must succeed before refreshing age.
        if 'node' not in responses:
            raise ValueError('Node status missing')
        blue['storage_rows'] = blue_storage(blue['root_disk'], responses['stores'], responses['pools'], responses['pool'], pool_name)
        rows = {r['name']: r['summary'] for r in blue['storage_rows']}
        blue['storage_warning'] = ('ZFS ' + rows[pool_name + ' health'] if rows[pool_name + ' health'] != 'ONLINE'
                                   else 'Pool data errors' if rows['Data errors'] != 'none reported'
                                   else 'VM storage inactive' if rows['VM OS disks'].endswith('INACTIVE') else '')
        blue['storage_checked_at'] = now
        blue.pop('storage_error', None)
    except Exception as exc:
        blue['storage_error'] = type(exc).__name__
        result['errors'].append('Blue storage: ' + type(exc).__name__)
    hosts = {'blue': blue}
    for target in config.get('hosts', []):
        ident = target['id']
        old = previous.get('hosts', {}).get(ident, {})
        try:
            hosts[ident] = host_summary(read_host(target), old, now)
        except Exception as exc:
            hosts[ident] = {**old, 'error': type(exc).__name__}
            result['errors'].append('Host ' + ident + ': ' + type(exc).__name__)
    result['hosts'] = hosts
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
