import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[4]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


volumes = load('storage_volume_guards', Path(__file__).parents[1] / 'files/inspect-volumes.py')
credentials = load('storage_credentials', ROOT / 'taskfiles/scripts/app/storage-secrets.py')


class VolumeSafetyTests(unittest.TestCase):
    def setUp(self):
        self.spec = {'lv': 'homelab-postgresql', 'mount': '/srv/homelab/postgresql',
                     'device': '/dev/ubuntu-vg/homelab-postgresql', 'size_gib': 20,
                     'tag': 'homelab-managed-postgresql', 'label': 'homelab-pg'}
        self.existing = {'size': 20 * 1024 ** 3, 'tags': ['homelab-managed-postgresql']}
        self.fs = {'TYPE': 'ext4', 'LABEL': 'homelab-pg'}

    def test_fresh_empty_target_is_provisionable(self):
        p = volumes.plan_volume(self.spec, None, None, True)
        self.assertTrue(p['create'])
        self.assertTrue(p['format'])

    def test_known_mounted_data_is_not_reformatted(self):
        p = volumes.plan_volume(self.spec, self.existing, self.fs, False, self.spec['device'])
        self.assertFalse(p['create'])
        self.assertFalse(p['format'])

    def test_unmounted_fallback_data_is_not_hidden(self):
        with self.assertRaises(ValueError):
            volumes.plan_volume(self.spec, self.existing, self.fs, False)

    def test_untagged_existing_volume_is_not_adopted(self):
        with self.assertRaises(ValueError):
            volumes.plan_volume(self.spec, dict(self.existing, tags=[]), self.fs, True)

    def test_unexpected_filesystem_is_not_formatted(self):
        for fs in [{'TYPE': 'ntfs'}, {'TYPE': 'ext4', 'LABEL': 'other-data'}]:
            with self.subTest(fs=fs), self.assertRaises(ValueError):
                volumes.plan_volume(self.spec, self.existing, fs, True)

    def test_unrelated_mount_is_not_replaced(self):
        with self.assertRaises(ValueError):
            volumes.plan_volume(self.spec, self.existing, self.fs, False, '/dev/other/data')

    def test_existing_volume_is_not_resized(self):
        with self.assertRaises(ValueError):
            volumes.plan_volume(self.spec, dict(self.existing, size=10 * 1024 ** 3), self.fs, True)

    def test_interrupted_new_tagged_volume_can_finish_formatting(self):
        p = volumes.plan_volume(self.spec, self.existing, None, True)
        self.assertFalse(p['create'])
        self.assertTrue(p['format'])

    def test_unowned_signature_is_not_adopted(self):
        with self.assertRaises(ValueError):
            volumes.plan_volume(self.spec, None, self.fs, True)


class SecretConvergenceTests(unittest.TestCase):
    def test_retry_preserves_every_credential(self):
        apps = credentials.applications()
        first = credentials.converge({}, apps)
        self.assertEqual(credentials.converge(first, apps), first)

    def test_new_application_does_not_rotate_existing_passwords(self):
        apps = credentials.applications()
        first = credentials.converge({}, apps)
        second = credentials.converge(first, apps + [{'database': 'other_app'}])
        self.assertEqual(first['garage'], second['garage'])
        self.assertEqual(first['postgresql']['applications'][apps[0]['database']],
                         second['postgresql']['applications'][apps[0]['database']])
        self.assertIn('other_app', second['postgresql']['applications'])

    def test_removed_application_secrets_are_retained(self):
        first = credentials.converge({}, credentials.applications())
        self.assertEqual(credentials.converge(first, []), first)

    def test_invalid_existing_credentials_are_not_silently_replaced(self):
        first = credentials.converge({}, credentials.applications())
        first['garage']['rpc_secret'] = 'invalid'
        with self.assertRaises(ValueError):
            credentials.converge(first, credentials.applications())


if __name__ == '__main__':
    unittest.main()
