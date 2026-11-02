import copy
import importlib.util
import json
import pathlib
import unittest
from unittest import mock

path = pathlib.Path(__file__).parents[1] / 'files' / 'reconcile.py'
spec = importlib.util.spec_from_file_location('garage_reconcile', path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class FakeGarage:
    def __init__(self):
        self.calls = []
        self.layout = {'version': 0, 'roles': [], 'stagedRoleChanges': []}
        self.buckets = []
        self.keys = {}

    def __call__(self, operation, body=None):
        self.calls.append((operation, copy.deepcopy(body)))
        if operation == 'GetClusterStatus':
            return {'nodes': [{'id': 'node-a'}]}
        if operation == 'GetClusterLayout':
            return copy.deepcopy(self.layout)
        if operation == 'UpdateClusterLayout':
            self.layout['stagedRoleChanges'] = body['roles']
        elif operation == 'ApplyClusterLayout':
            self.layout.update(version=body['version'], roles=self.layout['stagedRoleChanges'], stagedRoleChanges=[])
        elif operation == 'ListBuckets':
            return copy.deepcopy(self.buckets)
        elif operation == 'CreateBucket':
            result = {'id': 'bucket-a', 'globalAliases': [body['globalAlias']], 'websiteAccess': False}
            self.buckets.append(result)
            return copy.deepcopy(result)
        elif operation == 'GetBucketInfo':
            return copy.deepcopy(next(b for b in self.buckets if b['id'] == body['id']))
        elif operation == 'ListKeys':
            return [{'id': key} for key in self.keys]
        elif operation == 'ImportKey':
            self.keys[body['accessKeyId']] = {'secretAccessKey': body['secretAccessKey'], 'expired': False,
                                             'permissions': {'createBucket': False}, 'buckets': []}
        elif operation == 'GetKeyInfo':
            return copy.deepcopy(self.keys[body['id']])
        elif operation == 'UpdateKey':
            self.keys[body['id']]['permissions']['createBucket'] = False
        elif operation in ('AllowBucketKey', 'DenyBucketKey'):
            key = self.keys[body['accessKeyId']]
            grant = next((g for g in key['buckets'] if g['id'] == body['bucketId']), None)
            if grant is None:
                grant = {'id': body['bucketId'], 'permissions': {'read': False, 'write': False, 'owner': False}}
                key['buckets'].append(grant)
            for permission, selected in body['permissions'].items():
                if selected:
                    grant['permissions'][permission] = operation == 'AllowBucketKey'
        else:
            raise AssertionError(operation)
        return {}


class ReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.api = FakeGarage()
        self.config = {'container': 'homelab-garage', 'bucket': 'colouring-book-dev', 'zone': 'red',
                       'capacity_gib': 64, 'key_id': 'GK' + 'a' * 24, 'key_secret': 'b' * 64}

    def test_fresh_install_and_repeat_do_not_duplicate_layout_bucket_or_key(self):
        self.assertTrue(module.reconcile(self.config, self.api)['changed'])
        before = len(self.api.calls)
        self.assertFalse(module.reconcile(self.config, self.api)['changed'])
        mutations = [name for name, _ in self.api.calls[before:] if not name.startswith(('Get', 'List'))]
        self.assertEqual(mutations, [])
        self.assertEqual(len(self.api.buckets), 1)
        self.assertEqual(len(self.api.keys), 1)
        self.assertEqual(self.api.layout['version'], 1)

    def test_audit_only_detects_drift_without_modifying_state(self):
        self.config['audit_only'] = True
        with self.assertRaises(module.GarageError):
            module.reconcile(self.config, self.api)
        self.assertEqual(self.api.layout['version'], 0)
        self.assertEqual(self.api.buckets, [])
        self.assertFalse(any(name.startswith(('Update', 'Create', 'Apply', 'Import')) for name, _ in self.api.calls))

    def test_staged_first_install_can_resume_after_interruption(self):
        self.api.layout['stagedRoleChanges'] = [{'id': 'node-a', 'zone': 'red', 'capacity': 64 * 1024**3, 'tags': []}]
        module.reconcile(self.config, self.api)
        self.assertNotIn('UpdateClusterLayout', [name for name, _ in self.api.calls])

    def test_existing_different_layout_is_not_rewritten(self):
        module.reconcile(self.config, self.api)
        self.api.layout['roles'][0]['capacity'] = 128 * 1024**3
        before = len(self.api.calls)
        with self.assertRaises(module.GarageError):
            module.reconcile(self.config, self.api)
        self.assertEqual([name for name, _ in self.api.calls[before:]], ['GetClusterStatus', 'GetClusterLayout'])

    def test_unrelated_staged_change_is_not_applied(self):
        self.api.layout['stagedRoleChanges'] = [{'id': 'another-node', 'remove': True}]
        with self.assertRaises(module.GarageError):
            module.reconcile(self.config, self.api)
        self.assertNotIn('ApplyClusterLayout', [name for name, _ in self.api.calls])

    def test_unrelated_staged_parameters_are_not_applied(self):
        self.api.layout['stagedParameters'] = {'zoneRedundancy': 2}
        with self.assertRaises(module.GarageError):
            module.reconcile(self.config, self.api)
        self.assertNotIn('ApplyClusterLayout', [name for name, _ in self.api.calls])

    def test_managed_key_excess_permissions_are_revoked_without_deleting_data(self):
        module.reconcile(self.config, self.api)
        key = self.api.keys[self.config['key_id']]
        key['permissions']['createBucket'] = True
        key['buckets'][0]['permissions']['owner'] = True
        key['buckets'].append({'id': 'unrelated-bucket', 'permissions': {'read': True, 'write': True, 'owner': True}})
        self.assertTrue(module.reconcile(self.config, self.api)['changed'])
        self.assertFalse(key['permissions']['createBucket'])
        self.assertEqual(key['buckets'][0]['permissions'], {'read': True, 'write': True, 'owner': False})
        self.assertFalse(any(key['buckets'][1]['permissions'].values()))
        self.assertFalse(any(name.startswith('Delete') for name, _ in self.api.calls))

    def test_existing_different_secret_requires_explicit_recovery(self):
        module.reconcile(self.config, self.api)
        self.config['key_secret'] = 'c' * 64
        with self.assertRaises(module.GarageError):
            module.reconcile(self.config, self.api)
        self.assertEqual(sum(name == 'ImportKey' for name, _ in self.api.calls), 1)

    def test_invalid_access_key_fails_before_calling_api(self):
        self.config['key_id'] = 'wrong'
        with self.assertRaises(module.GarageError):
            module.reconcile(self.config, self.api)
        self.assertEqual(self.api.calls, [])

    def test_json_api_secret_is_stdin_only_and_never_printed(self):
        with mock.patch.object(module.subprocess, 'run', return_value=mock.Mock(returncode=0, stdout='{}')) as run:
            module.docker_api('homelab-garage')('ImportKey', {'secretAccessKey': self.config['key_secret']})
        args = run.call_args.args[0]
        self.assertNotIn(self.config['key_secret'], ' '.join(args))
        self.assertEqual(args[-1], '-')
        self.assertEqual(json.loads(run.call_args.kwargs['input'])['secretAccessKey'], self.config['key_secret'])


if __name__ == '__main__':
    unittest.main()
