import importlib.util
import pathlib
import json
import tempfile
import unittest

path = pathlib.Path(__file__).parents[1] / 'files' / 'deploy.py'
spec = importlib.util.spec_from_file_location('deploy', path)
deploy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deploy)


class AdmissionTests(unittest.TestCase):
    def setUp(self):
        self.contract = {'images': {'backend': {
            'repository': 'gitea.home.example.com/lab-agents-org/app-backend',
            'variable': 'BACKEND_IMAGE'}}}
        self.release = {'revision': 'a' * 40, 'images': {
            'backend': self.contract['images']['backend']['repository'] + '@sha256:' + 'b' * 64}}

    def test_accepts_only_admitted_digest(self):
        self.assertEqual(deploy.validate_release(self.contract, self.release), self.release)

    def test_rejects_mutable_tag(self):
        self.release['images']['backend'] = 'gitea.home.example.com/lab-agents-org/app-backend:latest'
        with self.assertRaises(ValueError):
            deploy.validate_release(self.contract, self.release)

    def test_rejects_another_repository(self):
        self.release['images']['backend'] = 'evil.example/app@sha256:' + 'b' * 64
        with self.assertRaises(ValueError):
            deploy.validate_release(self.contract, self.release)

    def test_rejects_unadmitted_service(self):
        self.release['images']['database'] = self.release['images']['backend']
        with self.assertRaises(ValueError):
            deploy.validate_release(self.contract, self.release)

    def test_rejects_compose_or_environment_injection(self):
        for name in ('compose', 'environment', 'command', 'path'):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    deploy.validate_release(self.contract, dict(self.release, **{name: 'attacker-controlled'}))

    def test_rejects_revision_shell_fragment(self):
        self.release['revision'] = 'main; touch /tmp/untrusted'
        with self.assertRaises(ValueError):
            deploy.validate_release(self.contract, self.release)

    def test_rejects_digest_with_newline(self):
        self.release['images']['backend'] += '\n'
        with self.assertRaises(ValueError):
            deploy.validate_release(self.contract, self.release)


class PromotionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = pathlib.Path(self.temp.name)
        self.old = {'revision': 'a' * 40, 'images': {'backend': 'old@sha256:123'}}
        self.new = {'revision': 'b' * 40, 'images': {'backend': 'new@sha256:456'}}
        deploy.atomic_json(self.state / 'current.json', self.old)

    def current(self):
        return json.loads((self.state / 'current.json').read_text())

    def test_success_records_previous_release(self):
        calls = []
        self.assertTrue(deploy.promote(self.state, self.new, lambda *a: calls.append(a)))
        self.assertEqual([c[0][0] for c in calls], ['pull', 'up'])
        self.assertEqual(self.current(), self.new)
        self.assertEqual(json.loads((self.state / 'previous.json').read_text()), self.old)
        self.assertFalse((self.state / 'pending.json').exists())

    def test_registry_failure_leaves_running_release_untouched(self):
        calls = []
        def fail_pull(*args):
            calls.append(args)
            raise RuntimeError('registry unavailable')
        with self.assertRaises(RuntimeError):
            deploy.promote(self.state, self.new, fail_pull)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0][0], 'pull')
        self.assertEqual(self.current(), self.old)

    def test_unhealthy_promotion_restores_previous_images(self):
        calls = []
        def run(args, release):
            calls.append((args[0], release))
            if args[0] == 'up' and release == self.new:
                raise RuntimeError('unhealthy')
        with self.assertRaisesRegex(RuntimeError, 'previous release restored'):
            deploy.promote(self.state, self.new, run)
        self.assertEqual(calls[-1], ('up', self.old))
        self.assertEqual(self.current(), self.old)
        self.assertFalse((self.state / 'pending.json').exists())

    def test_failed_rollback_retains_recovery_marker(self):
        def run(args, release):
            if args[0] == 'up':
                raise RuntimeError('unhealthy')
        with self.assertRaisesRegex(RuntimeError, 'operator recovery required'):
            deploy.promote(self.state, self.new, run)
        self.assertEqual(self.current(), self.old)
        self.assertTrue((self.state / 'pending.json').exists())

    def test_repeated_release_converges_without_erasing_rollback(self):
        deploy.atomic_json(self.state / 'previous.json', self.new)
        deploy.atomic_json(self.state / 'pending.json', self.new)
        calls = []
        self.assertFalse(deploy.promote(self.state, self.old, lambda *a: calls.append(a)))
        self.assertEqual([c[0][0] for c in calls], ['up'])
        self.assertEqual(json.loads((self.state / 'previous.json').read_text()), self.new)
        self.assertFalse((self.state / 'pending.json').exists())


if __name__ == '__main__':
    unittest.main()
