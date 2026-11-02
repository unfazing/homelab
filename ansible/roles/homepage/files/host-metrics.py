#!/usr/bin/python3 -I
"""Fixed, unprivileged Linux host report. No commands, processes or app data."""
import json
import os
from pathlib import Path
import re
import sys

SERVICE_CACHE = Path("/var/lib/homelab/storage-observer/snapshot.json")
SERVICE_FIELDS = {
    "garage": ["bucketCount", "totalObjectCount", "totalObjectBytes", "api_s3_request_counter", "api_s3_error_counter"],
    "postgresql": ["databases", "tables", "database_bytes", "transactions", "connections", "active", "blocked", "connection_limit", "server_start"],
}

def read_services(path=SERVICE_CACHE):
    """Read only the bounded, generated aggregate cache; no credentials or app mounts."""
    try:
        if path.is_symlink() or path.stat().st_size > 16384:
            return {}
        raw = json.loads(path.read_text())
        if raw.get("version") != 1:
            return {}
        result = {}
        for name, fields in SERVICE_FIELDS.items():
            sample = raw.get(name, {})
            checked = sample.get("checked_at")
            values = sample.get("values") or {}
            if type(checked) is not int or checked <= 0 or not all(type(values.get(k)) in (int, float) and 0 <= values[k] <= 9e15 and values[k] == int(values[k]) for k in fields):
                continue
            clean = {"checked_at": checked, "values": {k: int(values[k]) for k in fields}}
            if name == "garage":
                if sample.get("health") not in ("healthy", "degraded", "unavailable"):
                    continue
                clean["health"] = sample["health"]
            else:
                if not re.fullmatch(r"[a-f0-9]{32}", sample.get("reset_id", "")):
                    continue
                clean["reset_id"] = sample["reset_id"]
            if sample.get("error"):
                clean["error"] = "collection failed"
            result[name] = clean
        return result
    except (OSError, ValueError, TypeError, OverflowError):
        return {}


def collect(config, proc=Path('/proc')):
    cpu = next(line.split()[1:9] for line in (proc / 'stat').read_text().splitlines()
               if line.startswith('cpu '))
    ticks = list(map(int, cpu))
    memory = {}
    for line in (proc / 'meminfo').read_text().splitlines():
        parts = line.split()
        if parts[0] in ['MemTotal:', 'MemAvailable:', 'SwapTotal:', 'SwapFree:']:
            memory[parts[0][:-1]] = int(parts[1]) * 1024
    network = {'netin': 0, 'netout': 0}
    found_interfaces = set()
    for line in (proc / 'net/dev').read_text().splitlines():
        if ':' not in line:
            continue
        name, counters = line.split(':', 1)
        if name.strip() in config['network_interfaces']:
            fields = counters.split()
            network['netin'] += int(fields[0])
            network['netout'] += int(fields[8])
            found_interfaces.add(name.strip())
    if found_interfaces != set(config['network_interfaces']):
        raise ValueError('Configured physical network interface is missing')
    disk = {'diskread': 0, 'diskwrite': 0}
    found_disks = set()
    for line in (proc / 'diskstats').read_text().splitlines():
        fields = line.split()
        if fields[2] in config['disks']:
            # Linux diskstats sectors always use 512-byte accounting units.
            disk['diskread'] += int(fields[5]) * 512
            disk['diskwrite'] += int(fields[9]) * 512
            found_disks.add(fields[2])
    if found_disks != set(config['disks']):
        raise ValueError('Configured physical disk is missing')
    filesystems = {}
    for name, path in config['mounts'].items():
        if not os.path.ismount(path):
            filesystems[name] = {'mounted': False}
            continue
        stats = os.statvfs(path)
        filesystems[name] = {'mounted': True, 'total': stats.f_blocks * stats.f_frsize,
                             'used': (stats.f_blocks - stats.f_bfree) * stats.f_frsize,
                             'available': stats.f_bavail * stats.f_frsize}
    return {'version': 1, 'boot_id': (proc / 'sys/kernel/random/boot_id').read_text().strip(),
            'uptime': int(float((proc / 'uptime').read_text().split()[0])),
            'cpus': os.cpu_count(), 'cpu_total': sum(ticks), 'cpu_idle': ticks[3] + ticks[4],
            'load': list(map(float, (proc / 'loadavg').read_text().split()[:3])),
            'memory_total': memory['MemTotal'], 'memory_available': memory['MemAvailable'],
            'swap_total': memory['SwapTotal'], 'swap_free': memory['SwapFree'],
            'filesystems': filesystems, 'storage_metrics': read_services(), **network, **disk}


def validate(config):
    for key in ['network_interfaces', 'disks']:
        if not config[key] or not all(re.fullmatch(r'[a-zA-Z0-9_.-]{1,32}', x) for x in config[key]):
            raise ValueError('Invalid counter sources')
    if not config['mounts'] or not all(re.fullmatch(r'[a-z][a-z0-9_]{0,31}', k)
                                      and isinstance(v, str) and v.startswith('/')
                                      for k, v in config['mounts'].items()):
        raise ValueError('Invalid filesystem sources')


if __name__ == '__main__':
    try:
        if len(sys.argv) != 1:
            raise ValueError('This reporter accepts no arguments')
        config = json.loads(Path('/etc/homelab/homepage-host-metrics.json').read_text())
        validate(config)
        print(json.dumps(collect(config), separators=(',', ':')))
    except Exception:
        # Never echo source contents, SSH environment or arbitrary exception data.
        print('Host metrics unavailable', file=sys.stderr)
        raise SystemExit(1)
