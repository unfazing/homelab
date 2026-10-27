"""Collector security and discovery regression tests; no live credentials."""
import importlib.util
from pathlib import Path
import unittest
import ssl

spec = importlib.util.spec_from_file_location('collector', Path(__file__).parents[1] / 'files/collect.py')
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)


def configuration(hosts):
    routes = [{'match': [{'host': ['*.home.test.invalid']}], 'handle': [
        {'handler': 'subroute', 'routes': [
            {'match': [{'host': [host]}], 'handle': [
                {'handler': 'authentication', 'secret': 'NEVER_EXPORT'},
                {'handler': 'reverse_proxy', 'headers': {'Authorization': 'NEVER_EXPORT'},
                 'upstreams': [{'dial': 'backend:3000'}]}]} for host in hosts]}]}]
    return {'apps': {'http': {'servers': {'public': {'listen': [':443'], 'routes': routes},
          'admin': {'listen': ['172.30.90.2:2020'], 'routes': [{'match': [{'host': ['hidden.home.test.invalid']}]}]}}}}}


class CollectorTests(unittest.TestCase):
    def test_private_ca_compatibility_retains_certificate_and_hostname_checks(self):
        from unittest.mock import patch
        context = ssl.create_default_context()
        with patch.object(c.ssl, 'create_default_context', return_value=context):
            result = c.proxmox_context('private-ca.pem')
        self.assertEqual(result.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(result.check_hostname)
        self.assertFalse(result.verify_flags & ssl.VERIFY_X509_STRICT)

    def test_automatic_addition_removal_and_redaction(self):
        a = 'a.home.test.invalid'; b = 'b.home.test.invalid'
        self.assertEqual([r['hostname'] for r in c.extract_routes(configuration([a]), 'test.invalid')], [a])
        expanded = c.extract_routes(configuration([a, b]), 'test.invalid')
        self.assertEqual([r['hostname'] for r in expanded], [a, b])
        self.assertNotIn('NEVER_EXPORT', str(expanded))
        self.assertEqual([r['hostname'] for r in c.extract_routes(configuration([b]), 'test.invalid')], [b])

    def test_outside_namespace_is_not_probed(self):
        self.assertEqual(c.extract_routes(configuration(['evil.invalid']), 'test.invalid'), [])

    def test_or_matchers_are_separate_branches(self):
        data = configuration(['a.home.test.invalid'])
        route = data['apps']['http']['servers']['public']['routes'][0]['handle'][0]['routes'][0]
        route['match'] = [{'host': ['a.home.test.invalid']}, {'host': ['b.home.test.invalid']}]
        self.assertEqual(len(c.extract_routes(data, 'test.invalid')), 2)

    def test_wildcard_is_preserved_not_invented(self):
        rows = c.extract_routes(configuration(['*.home.test.invalid']), 'test.invalid')
        self.assertEqual(rows[0]['kind'], 'wildcard / fallback')
        self.assertEqual(c.probe_tls(rows[0], '127.0.0.1', 1)['tls_status'], 'not probed')

    def test_credentials_and_dynamic_dials_are_not_exported(self):
        self.assertEqual(c.safe_dial('https://user:password@backend'), '[dynamic/private destination]')
        self.assertEqual(c.safe_dial('{env.SECRET}'), '[dynamic/private destination]')
        self.assertEqual(c.safe_dial('192.168.1.9:3000'), '192.168.1.9:3000')

    def test_rate_sampling_and_restart(self):
        raw = {'status': 'running', 'cpu': .125, 'cpus': 2, 'uptime': 500,
               'netin': 1000, 'diskwrite': 2000, 'mem': 1024, 'maxmem': 4096}
        first = c.vm_summary(raw, {}, 100)
        self.assertEqual(first['network_in'], 'warming up')
        second = c.vm_summary({**raw, 'netin': 1060, 'uptime': 560}, first, 160)
        self.assertEqual(second['network_in'], '1.0 B/s')
        self.assertEqual(second['cpu'], '12.5% / 2 vCPU')
        reset = c.vm_summary({**raw, 'uptime': 1}, second, 220)
        self.assertEqual(reset['network_in'], 'warming up')
        stale = c.vm_summary(raw, first, 500)
        self.assertEqual(stale['network_in'], 'warming up')


if __name__ == '__main__':
    unittest.main()
