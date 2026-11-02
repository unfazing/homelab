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


class BlueSummaryTests(unittest.TestCase):
    def status(self):
        return {'cpuinfo': {'cpus': 8}, 'uptime': 90000, 'loadavg': ['.1', '.2', '.3'],
                'memory': {'total': 16*1024**3, 'available': 8*1024**3},
                'swap': {'total': 1024**3, 'used': 0, 'free': 1024**3},
                'rootfs': {'total': 1000, 'used': 300, 'avail': 650}, 'secret': 'NEVER_EXPORT'}

    def test_node_summary_uses_available_ram_and_does_not_export_raw_fields(self):
        row = c.blue_summary(self.status(), 100)
        self.assertEqual(row['memory'], '8.0 GiB / 16.0 GiB')
        self.assertEqual(row['cpu_threads'], 8)
        self.assertEqual(row['uptime'], '1d 1h 0m')
        self.assertNotIn('NEVER_EXPORT', str(row))

    def test_rrd_rates_are_already_per_second_and_keep_sample_time(self):
        sample = {'time': 100, 'cpu': .25, 'netin': 1024, 'netout': 2048, 'iowait': .01, 'arcsize': 1024**3}
        row = c.blue_activity([sample], 8, 160)
        self.assertEqual(row['cpu'], '25.0% / 8 threads')
        self.assertEqual(row['network_in'], '1.0 KiB/s')
        self.assertEqual(row['activity_checked_at'], 100)
        self.assertEqual(row['arc'], '1.0 GiB')
        for bad, now in [([sample], 281), ([{**sample, 'time': 999}], 160),
                         ([{**sample, 'cpu': float('nan')}], 160), ([{**sample, 'iowait': 2}], 160)]:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                c.blue_activity(bad, 8, now)

    def test_zfs_export_omits_actions_paths_and_unknown_free_text(self):
        stores = [{'storage': 'local-lvm', 'total': 1000, 'used': 300, 'avail': 700, 'active': 1}]
        pools = [{'name': 'tank', 'size': 1000, 'alloc': 100, 'free': 900, 'health': 'ONLINE'}]
        detail = {'scan': 'scrub repaired 0B in 00:00:00 with 0 errors on Sun Oct 11 00:24:01 2026',
                  'errors': 'No known data errors', 'action': 'NEVER_EXPORT'}
        rows = c.blue_storage('root totals', stores, pools, detail, 'tank')
        self.assertEqual(next(r['summary'] for r in rows if r['name']=='tank health'), 'ONLINE')
        self.assertEqual(next(r['summary'] for r in rows if r['name']=='Last scrub'), '2026-10-11 · 0 errors · repaired 0B')
        self.assertNotIn('NEVER_EXPORT', str(rows))
        detail.update(scan='NEVER_EXPORT', errors='/private/NEVER_EXPORT')
        self.assertNotIn('NEVER_EXPORT', str(c.blue_storage('root', stores, pools, detail, 'tank')))

    def test_invalid_capacity_cannot_be_rendered_as_healthy(self):
        with self.assertRaises(ValueError):
            c.capacity(100, 200, 0)
        bad = self.status(); bad['memory']['available'] = 32*1024**3
        with self.assertRaises(ValueError):
            c.blue_summary(bad, 100)


class HostSummaryTests(unittest.TestCase):
    def report(self, **changes):
        return {'version': 1, 'boot_id': '00000000-0000-0000-0000-000000000001',
                'uptime': 3600, 'cpus': 4, 'cpu_total': 100, 'cpu_idle': 70,
                'load': [.1, .2, .3], 'memory_total': 4 * 1024 ** 3, 'memory_available': 3 * 1024 ** 3,
                'swap_total': 1024 ** 3, 'swap_free': 1024 ** 3,
                'netin': 1000, 'netout': 2000, 'diskread': 3000, 'diskwrite': 4000,
                'filesystems': {'root': {'mounted': True, 'total': 1000, 'used': 400, 'available': 500}},
                'unexpected_secret': 'NEVER_EXPORT', **changes}

    def test_first_sample_has_usage_but_does_not_invent_rates(self):
        row = c.host_summary(self.report(), {}, 100)
        self.assertEqual(row['memory'], '1.0 GiB / 4.0 GiB')
        self.assertEqual(row['cpu'], 'warming up')
        self.assertEqual(row['network_in'], 'warming up')
        self.assertIn('NOT MOUNTED', row['garage_disk'])
        self.assertNotIn('NEVER_EXPORT', str(row))

    def test_cpu_and_io_rates_use_two_valid_host_samples(self):
        first = c.host_summary(self.report(), {}, 100)
        row = c.host_summary(self.report(cpu_total=200, cpu_idle=140, uptime=3660, netin=1060), first, 160)
        self.assertEqual(row['cpu'], '30.0% / 4 threads')
        self.assertEqual(row['network_in'], '1.0 B/s')

    def test_reboot_counter_reset_and_stale_samples_restart_sampling(self):
        first = c.host_summary(self.report(), {}, 100)
        for raw, now in [(self.report(boot_id='00000000-0000-0000-0000-000000000002'), 160),
                         (self.report(uptime=1, cpu_total=1, cpu_idle=0, netin=0), 160),
                         (self.report(cpu_total=200, cpu_idle=100), 400)]:
            row = c.host_summary(raw, first, now)
            self.assertEqual(row['cpu'], 'warming up')
            self.assertEqual(row['network_in'], 'warming up')

    def test_invalid_metrics_are_not_published(self):
        for change in [{'memory_available': -1}, {'memory_available': 99 * 1024 ** 3},
                       {'load': [float('nan'), 0, 0]}, {'cpu_idle': 999}, {'version': 2}]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                c.host_summary(self.report(**change), {}, 100)

    def test_storage_usage_uses_filesystem_bytes_not_application_statistics(self):
        raw = self.report(filesystems={'postgresql': {'mounted': True, 'total': 1000, 'used': 125, 'available': 800},
                                       'garage': {'mounted': False}})
        row = c.host_summary(raw, {}, 100)
        usage = row['filesystem_usage']['postgresql']
        self.assertEqual(usage['utilisation'], '12.5%')
        self.assertEqual(usage['available'], '800.0 B')
        self.assertEqual(row['filesystem_usage']['garage'], {'mounted': False})
        self.assertNotIn('database_size', usage)

    def test_ssh_host_identity_and_key_checks_cannot_be_silently_bypassed(self):
        from unittest.mock import patch
        import json
        target = {'id': 'red', 'ssh_user': 'homepage-monitor', 'address': '192.168.1.9'}
        with patch.object(c.subprocess, 'run') as run:
            run.return_value.stdout = json.dumps(self.report())
            c.read_host(target)
            args = run.call_args.args[0]
            self.assertIn('StrictHostKeyChecking=yes', args)
            self.assertIn('IdentitiesOnly=yes', args)
            self.assertIn('/etc/homelab/homepage-observer/host-red-key', args)
            self.assertEqual(args[-2:], ['homepage-monitor@192.168.1.9', 'metrics'])
        with self.assertRaises(ValueError):
            c.read_host({**target, 'id': '../private-key'})


class ServiceTests(unittest.TestCase):
    def sample(self, **changes):
        sample={'checked_at':100,'health':'healthy','values':{'bucketCount':1,'totalObjectCount':3,
          'totalObjectBytes':1024,'api_s3_request_counter':10,'api_s3_error_counter':2}}
        sample.update(changes)
        return sample

    def test_counts_rates_reset_stale_and_duplicate_reads(self):
        first=c.service_summary('garage',self.sample(),{})
        self.assertEqual(first['objects'],'3')
        self.assertEqual(first['requests_per_min'],'warming up')
        raw=self.sample(checked_at=160)
        raw['values']['api_s3_request_counter']=70
        second=c.service_summary('garage',raw,first)
        self.assertEqual(second['requests_per_min'],'60.0')
        self.assertEqual(c.service_summary('garage',raw,second)['requests_per_min'],'60.0')
        for timestamp,count in [(220,1),(400,100)]:
            raw=self.sample(checked_at=timestamp)
            raw['values']['api_s3_request_counter']=count
            self.assertEqual(c.service_summary('garage',raw,second)['requests_per_min'],'warming up')

    def test_allowlist_and_invalid_values(self):
        sample=self.sample(password='NEVER_EXPORT',query='NEVER_EXPORT')
        self.assertNotIn('NEVER_EXPORT',str(c.service_summary('garage',sample,{})))
        sample['values']['totalObjectCount']=-1
        self.assertEqual(c.service_summary('garage',sample,{}),{})

    def test_transaction_rate_requires_matching_reset_and_server_identity(self):
        sample={'checked_at':100,'reset_id':'a'*32,'values':dict(databases=1,tables=2,database_bytes=1024,
          transactions=100,connections=2,active=1,blocked=0,connection_limit=30,server_start=1)}
        first=c.service_summary('postgresql',sample,{})
        sample['checked_at']=160;sample['values']['transactions']=160
        self.assertEqual(c.service_summary('postgresql',sample,first)['transactions_per_sec'],'1.0')
        sample['reset_id']='b'*32
        self.assertEqual(c.service_summary('postgresql',sample,first)['transactions_per_sec'],'warming up')
        sample['reset_id']='a'*32;sample['values']['server_start']=2
        self.assertEqual(c.service_summary('postgresql',sample,first)['transactions_per_sec'],'warming up')


if __name__ == '__main__':
    unittest.main()
