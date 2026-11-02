"""Linux reporter fixtures: only selected counters, no privileged/app reads."""
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('host_metrics', Path(__file__).parents[1] / 'files/host-metrics.py')
reporter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reporter)


class ReporterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.proc = Path(self.tmp.name)
        fixtures = {
            'stat': 'cpu 100 20 30 200 10 5 5 0 50 10\ncpu0 1 2 3 4\n',
            'meminfo': 'MemTotal: 1000 kB\nMemAvailable: 600 kB\nSwapTotal: 200 kB\nSwapFree: 180 kB\n',
            'uptime': '3600.5 200.0\n', 'loadavg': '0.10 0.20 0.30 1/100 1234\n',
            'sys/kernel/random/boot_id': '00000000-0000-0000-0000-000000000001\n',
            'net/dev': 'eno1: 1000 1 0 0 0 0 0 0 2000 2 0 0 0 0 0 0\ndocker0: 9000000 1 0 0 0 0 0 0 9000000 1 0 0 0 0 0 0\n',
            'diskstats': '8 0 sda 1 2 3 4 5 6 7 8 9 10 11\n8 1 sda1 99 99 99999 99 99 99 99999 99 99 99 99\n',
            'cmdline': 'NEVER_EXPORT_APPLICATION_SECRET',
        }
        for name, text in fixtures.items():
            path = self.proc / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        self.config = {'network_interfaces': ['eno1'], 'disks': ['sda'],
                       'mounts': {'root': '/', 'postgresql': '/srv/homelab/postgresql', 'garage': '/srv/homelab/garage'}}

    def report(self):
        fs = SimpleNamespace(f_blocks=100, f_bfree=50, f_bavail=40, f_frsize=1024)
        with patch.object(reporter.os.path, 'ismount', side_effect=lambda p: p != '/srv/homelab/garage'), \
             patch.object(reporter.os, 'statvfs', return_value=fs), patch.object(reporter.os, 'cpu_count', return_value=4):
            return reporter.collect(self.config, self.proc)

    def test_linux_cpu_guest_ticks_are_not_counted_twice(self):
        result = self.report()
        self.assertEqual(result['cpu_total'], 370)
        self.assertEqual(result['cpu_idle'], 210)

    def test_only_physical_sources_are_counted(self):
        result = self.report()
        self.assertEqual((result['netin'], result['netout']), (1000, 2000))
        self.assertEqual((result['diskread'], result['diskwrite']), (3 * 512, 7 * 512))
        self.assertNotIn('NEVER_EXPORT', json.dumps(result))

    def test_missing_mount_is_not_reported_as_root_disk_space(self):
        result = self.report()
        self.assertEqual(result['filesystems']['garage'], {'mounted': False})
        self.assertEqual(result['filesystems']['root']['available'], 40 * 1024)
        self.assertEqual(result['memory_available'], 600 * 1024)

    def test_missing_interface_and_disk_fail_instead_of_showing_zero(self):
        for field, value in [('network_interfaces', ['missing0']), ('disks', ['missingdisk'])]:
            with self.subTest(field=field):
                original = self.config[field]
                self.config[field] = value
                with self.assertRaises(ValueError):
                    self.report()
                self.config[field] = original

    def test_invalid_counter_source_is_rejected(self):
        self.config['network_interfaces'] = ['eno1\nprocesses']
        with self.assertRaises(ValueError):
            reporter.validate(self.config)


class ServiceCacheTests(unittest.TestCase):
    def test_missing_invalid_and_secret_fields_do_not_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'snapshot.json'
            self.assertEqual(reporter.read_services(path),{})
            path.write_text('not json')
            self.assertEqual(reporter.read_services(path),{})
            raw={'version':1,'garage':{'checked_at':100,'health':'healthy','password':'NEVER_EXPORT',
                'values':{'bucketCount':1,'totalObjectCount':2,'totalObjectBytes':3,
                    'api_s3_request_counter':4,'api_s3_error_counter':0,'secret':'NEVER_EXPORT'}}}
            path.write_text(json.dumps(raw))
            result=reporter.read_services(path)
            self.assertEqual(result['garage']['values']['totalObjectCount'],2)
            self.assertNotIn('NEVER_EXPORT',str(result))
            raw['garage']['values']['bucketCount']=float('nan');path.write_text(json.dumps(raw))
            self.assertEqual(reporter.read_services(path),{})

if __name__ == '__main__':
    unittest.main()
