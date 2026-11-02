import copy
import importlib.util
import pathlib
import unittest

PATH = pathlib.Path(__file__).parents[1] / 'files' / 'reconcile.py'
SPEC = importlib.util.spec_from_file_location('postgresql_reconcile', PATH)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def config():
    return {'container': 'homelab-postgresql', 'admin_password': 'A' * 32,
            'applications': [{'database': 'book_dev', 'owner_role': 'book_owner',
                              'runtime_role': 'book_app', 'migration_role': 'book_migrator',
                              'runtime_password': 'B' * 32, 'migration_password': 'C' * 32}]}


class CredentialTests(unittest.TestCase):
    def test_scram_round_trip_and_wrong_password(self):
        verifier = module.scram_verifier('A' * 32)
        self.assertTrue(module.password_matches('A' * 32, verifier))
        self.assertFalse(module.password_matches('B' * 32, verifier))
        self.assertNotIn('A' * 32, verifier)

    def test_random_salts_do_not_force_rotation(self):
        first = module.scram_verifier('A' * 32)
        second = module.scram_verifier('A' * 32)
        self.assertNotEqual(first, second)
        self.assertTrue(module.password_matches('A' * 32, first))
        self.assertTrue(module.password_matches('A' * 32, second))

    def test_corrupt_and_legacy_verifiers_fail_closed(self):
        for value in (None, '', 'md5' + '0' * 32, 'SCRAM-SHA-256$bad$keys'):
            self.assertFalse(module.password_matches('A' * 32, value))


class ContractTests(unittest.TestCase):
    def test_valid_multi_app_contract(self):
        c = config()
        c['applications'].append(dict(database='second_dev', owner_role='second_owner',
                                      runtime_role='second_app', migration_role='second_migrator',
                                      runtime_password='D' * 32, migration_password='E' * 32))
        self.assertEqual(module.validate(c), c)

    def test_identifier_injection_and_reserved_names_rejected(self):
        for value in ('book;DROP DATABASE postgres', 'pg_read_all_data', 'postgres', 'template1', 'a"b', 'UPPER'):
            with self.subTest(value=value):
                c = config(); c['applications'][0]['runtime_role'] = value
                with self.assertRaises(module.ProvisionError): module.validate(c)

    def test_credential_newline_and_shell_fragments_rejected(self):
        for value in ('x' * 32 + '\n', "x'" * 20, '$(command)' * 5, 'é' * 32):
            c = config(); c['applications'][0]['runtime_password'] = value
            with self.assertRaises(module.ProvisionError): module.validate(c)

    def test_shared_admin_runtime_or_migrator_secret_rejected(self):
        for field in ('runtime_password', 'migration_password'):
            c = config(); c['applications'][0][field] = c['admin_password']
            with self.assertRaises(module.ProvisionError): module.validate(c)
        c = config(); c['applications'][0]['runtime_password'] = c['applications'][0]['migration_password']
        with self.assertRaises(module.ProvisionError): module.validate(c)

    def test_cross_application_role_reuse_rejected(self):
        c = config(); second = copy.deepcopy(c['applications'][0]); second['database'] = 'second_dev'
        c['applications'].append(second)
        with self.assertRaises(module.ProvisionError): module.validate(c)

    def test_duplicate_database_rejected(self):
        c = config(); c['applications'].append(copy.deepcopy(c['applications'][0]))
        with self.assertRaises(module.ProvisionError): module.validate(c)

    def test_existing_owner_mismatch_does_not_change_database(self):
        class FakeSql:
            def value(self, sql, database='postgres'): return 'unmanaged_owner'
            def run(self, *args): raise AssertionError('Must not mutate a database owned elsewhere')
        with self.assertRaises(module.ProvisionError):
            module.ensure_database(FakeSql(), config()['applications'][0], [])

    def test_owner_collision_fails_before_any_password_or_role_change(self):
        class FakeSql:
            def value(self, sql, database='postgres'): return 'unmanaged_owner'
            def run(self, *args): raise AssertionError('No mutations permitted on owner collision')
        with self.assertRaises(module.ProvisionError):
            module.reconcile(config(), FakeSql())


if __name__ == '__main__':
    unittest.main()
