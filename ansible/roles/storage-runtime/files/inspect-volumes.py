#!/usr/bin/python3
"""Read-only LVM/mount inspection before any storage provisioning."""
import json
import os
import pathlib
import re
import subprocess
import sys
from decimal import Decimal


def plan_volume(spec, existing, fs, target_empty, mounted_source=None):
    if not re.fullmatch(r'homelab-[a-z][a-z0-9-]*', spec['lv']):
        raise ValueError('Unexpected logical-volume name')
    if not spec['mount'].startswith('/srv/homelab/') or '..' in pathlib.Path(spec['mount']).parts:
        raise ValueError('Unexpected mount path')
    if not isinstance(spec['size_gib'], int) or spec['size_gib'] <= 0:
        raise ValueError('Storage allocation must be a positive GiB count')
    if not existing and fs is not None:
        raise ValueError('Filesystem has no managed logical-volume provenance')
    if existing:
        if spec['tag'] not in existing['tags']:
            raise ValueError('Refusing to adopt an untagged existing logical volume')
        if existing['size'] < spec['size_gib'] * 1024 ** 3:
            raise ValueError('Existing volume is smaller than requested; no automatic resize')
        if fs is not None and (fs.get('TYPE') != 'ext4' or fs.get('LABEL') != spec['label']):
            raise ValueError('Existing filesystem is not the expected managed ext4 volume')
    elif mounted_source:
        raise ValueError('Target is already mounted from an unrelated source')
    if mounted_source:
        if fs is None or os.path.realpath(mounted_source) != os.path.realpath(spec['device']):
            raise ValueError('Target mount does not match its managed logical volume')
    elif not target_empty:
        raise ValueError('Unmounted target contains files; refusing to cover or replace data')
    return dict(spec, create=not bool(existing), format=fs is None)


def command(args):
    return subprocess.run(args, text=True, capture_output=True)


def main():
    policy = json.load(sys.stdin)
    vg = policy['volume_group']
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9-]*', vg):
        raise ValueError('Unexpected volume group')
    r = command(['vgs', '--reportformat', 'json', '--units', 'b', '--nosuffix', '-o', 'vg_name,vg_free', vg])
    if r.returncode:
        raise ValueError('Cannot inspect the requested volume group')
    groups = json.loads(r.stdout)['report'][0]['vg']
    if len(groups) != 1 or groups[0]['vg_name'].strip() != vg:
        raise ValueError('Volume group is ambiguous')
    free = int(Decimal(groups[0]['vg_free'].strip()))
    r = command(['lvs', '--reportformat', 'json', '--units', 'b', '--nosuffix', '-o', 'lv_name,lv_size,lv_tags', vg])
    if r.returncode:
        raise ValueError('Cannot inspect logical volumes')
    existing = {v['lv_name'].strip(): {'size': int(Decimal(v['lv_size'].strip())),
                                     'tags': v['lv_tags'].strip().split(',')}
                for v in json.loads(r.stdout)['report'][0]['lv']}
    plans = []
    for spec in policy['volumes']:
        spec['device'] = '/dev/' + vg + '/' + spec['lv']
        fs = None
        if spec['lv'] in existing:
            r = command(['blkid', '-p', '-o', 'export', spec['device']])
            if r.returncode not in (0, 2):
                raise ValueError('Filesystem signatures are ambiguous')
            if r.returncode == 0:
                fs = dict(line.split('=', 1) for line in r.stdout.splitlines() if '=' in line)
        path = pathlib.Path(spec['mount'])
        mounted = None
        if os.path.ismount(path):
            r = command(['findmnt', '--noheadings', '--output', 'SOURCE', '--mountpoint', str(path)])
            if r.returncode:
                raise ValueError('Cannot determine current mount source')
            mounted = r.stdout.strip()
        empty = not path.exists() or (path.is_dir() and not any(path.iterdir()))
        plan = plan_volume(spec, existing.get(spec['lv']), fs, empty, mounted)
        for line in pathlib.Path('/etc/fstab').read_text().splitlines():
            fields = line.split()
            if line.lstrip().startswith('#') or len(fields) < 2 or fields[1] != str(path):
                continue
            allowed = {spec['device'], os.path.realpath(spec['device'])}
            if fs and fs.get('UUID'):
                allowed.add('UUID=' + fs['UUID'])
            if fields[0] not in allowed:
                raise ValueError('Existing fstab entry belongs to another filesystem')
        if policy.get('require_mounted') and not mounted:
            raise ValueError('Required durable filesystem is not mounted')
        plans.append(plan)
    needed = sum(p['size_gib'] * 1024 ** 3 for p in plans if p['create'])
    if free < needed:
        raise ValueError('Insufficient unallocated LVM space; existing volumes will not be resized')
    print(json.dumps({'free_bytes': free, 'required_bytes': needed, 'volumes': plans}))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, OSError, TypeError) as exc:
        print('Storage inspection failed: ' + str(exc) + '. Inspect vgs/lvs/findmnt before retrying.', file=sys.stderr)
        raise SystemExit(1)
