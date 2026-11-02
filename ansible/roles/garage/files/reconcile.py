#!/usr/bin/python3
"""Converge one single-node layout and a bucket-scoped application key via RPC API.

Secrets arrive only on stdin and stay out of subprocess arguments and output.
Existing unrelated buckets/keys are retained. Existing nonmatching layouts fail.
"""
import json
import re
import subprocess
import sys


class GarageError(RuntimeError):
    pass


def validate(config):
    if not re.fullmatch(r'[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]', config['bucket']):
        raise GarageError('Invalid bucket name')
    if not re.fullmatch(r'GK[a-f0-9]{24}', config['key_id']):
        raise GarageError('Invalid S3 access-key ID')
    if not re.fullmatch(r'[a-f0-9]{64}', config['key_secret']):
        raise GarageError('Invalid S3 secret format')
    if not re.fullmatch(r'[a-z][a-z0-9-]{0,39}', config['zone']):
        raise GarageError('Invalid layout zone')
    if not re.fullmatch(r'[a-z0-9][a-z0-9_.-]*', config['container']):
        raise GarageError('Invalid container name')
    if type(config['capacity_gib']) is not int or config['capacity_gib'] < 1:
        raise GarageError('Invalid storage capacity')


def docker_api(container):
    def call(operation, body=None):
        args = ['docker', 'exec', '-i', container, '/garage', '-c', '/etc/garage.toml', 'json-api', operation]
        if body is not None:
            args.append('-')
        result = subprocess.run(args, input=json.dumps(body) if body is not None else '', text=True,
                                capture_output=True, timeout=120)
        if result.returncode:
            raise GarageError('Garage RPC administration operation failed: ' + operation)
        try:
            return json.loads(result.stdout)
        except ValueError:
            raise GarageError('Garage returned a non-JSON administration response') from None
    return call


def reconcile(config, api):
    validate(config)
    if config.get('audit_only', False):
        original_api = api

        def audit_api(operation, body=None):
            if not operation.startswith(('Get', 'List')):
                raise GarageError('Configuration drift detected; run normal convergence')
            return original_api(operation, body)

        api = audit_api
    changed = []
    status = api('GetClusterStatus')
    layout = api('GetClusterLayout')
    nodes = status['nodes']
    if len(nodes) != 1:
        raise GarageError('Refusing to modify a multi-node or unexpected cluster')
    node = nodes[0]['id']
    desired = {'id': node, 'zone': config['zone'], 'capacity': config['capacity_gib'] * 1024**3, 'tags': []}
    if layout['version'] == 0 and not layout['roles']:
        staged = layout.get('stagedRoleChanges', [])
        if layout.get('stagedParameters') or (staged and staged != [desired]):
            raise GarageError('Refusing to apply unrelated staged layout changes')
        if not staged:
            api('UpdateClusterLayout', {'roles': [desired]})
        api('ApplyClusterLayout', {'version': 1})
        changed.append('initialized single-node layout')
    else:
        roles = layout['roles']
        if (len(roles) != 1 or any(roles[0].get(k) != desired[k] for k in ['id', 'zone', 'capacity', 'tags'])
                or layout.get('stagedRoleChanges') or layout.get('stagedParameters')):
            raise GarageError('Existing layout differs; use an explicit layout migration')
    buckets = api('ListBuckets')
    bucket = next((b for b in buckets if config['bucket'] in b['globalAliases']), None)
    if bucket is None:
        bucket = api('CreateBucket', {'globalAlias': config['bucket']})
        changed.append('created application bucket')
    bucket_id = bucket['id']
    info = api('GetBucketInfo', {'id': bucket_id})
    if info.get('websiteAccess'):
        api('UpdateBucket', {'id': bucket_id, 'body': {'websiteAccess': {'enabled': False}}})
        changed.append('disabled anonymous website access')
    keys = api('ListKeys')
    if not any(k['id'] == config['key_id'] for k in keys):
        api('ImportKey', {'accessKeyId': config['key_id'], 'secretAccessKey': config['key_secret'],
                          'name': 'homelab-' + config['bucket']})
        changed.append('imported application key')
    key = api('GetKeyInfo', {'id': config['key_id'], 'showSecretKey': True})
    if key.get('secretAccessKey') != config['key_secret'] or key.get('expired'):
        raise GarageError('Application key is expired or differs from the protected credential; explicit recovery required')
    if key.get('permissions', {}).get('createBucket'):
        api('UpdateKey', {'id': config['key_id'], 'body': {'deny': {'createBucket': True}}})
        changed.append('removed bucket-creation authority')
    target_permissions = {}
    for grant in key.get('buckets', []):
        permissions = grant['permissions']
        if grant['id'] != bucket_id and any(permissions.values()):
            api('DenyBucketKey', {'bucketId': grant['id'], 'accessKeyId': config['key_id'],
                                  'permissions': {'read': True, 'write': True, 'owner': True}})
            changed.append('removed unrelated application-key grant')
        elif grant['id'] == bucket_id:
            target_permissions = permissions
    if target_permissions.get('owner'):
        api('DenyBucketKey', {'bucketId': bucket_id, 'accessKeyId': config['key_id'],
                              'permissions': {'read': False, 'write': False, 'owner': True}})
        changed.append('removed bucket-owner authority')
    if not target_permissions.get('read') or not target_permissions.get('write'):
        api('AllowBucketKey', {'bucketId': bucket_id, 'accessKeyId': config['key_id'],
                               'permissions': {'read': True, 'write': True, 'owner': False}})
        changed.append('granted application bucket read/write')
    return {'changed': bool(changed), 'applied': changed}


if __name__ == '__main__':
    try:
        config = json.load(sys.stdin)
        print(json.dumps(reconcile(config, docker_api(config['container']))))
    except (GarageError, ValueError, KeyError, TypeError, OSError, subprocess.TimeoutExpired) as error:
        print('Garage convergence failed; inspect protected host configuration: ' + type(error).__name__, file=sys.stderr)
        raise SystemExit(1)
