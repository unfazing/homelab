"""Parse actual Compose templates with Ansible's YAML parser, without secrets."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class ComposeMountTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('ansible-playbook'), 'Ansible required')
    def test_tmpfs_options_remain_single_absolute_mount_entries(self):
        roles = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tasks = []
            for role in ['postgresql', 'garage', 'garage-ui']:
                template = roles / role / 'templates/compose.yml.j2'
                # Read just the literal tmpfs fields. Other template values need
                # deployment facts/credentials and must not be evaluated here.
                tasks.append({'ansible.builtin.copy': {
                    'content': "{{ ((lookup('file', " + repr(str(template)) + ") | regex_replace('(?m)^[{]%.*%[}]', '') | from_yaml).services.values() | first).tmpfs | to_json }}",
                    'dest': str(root / (role + '.json')), 'mode': '0600'}})
            playbook = root / 'compose-check.yml'
            playbook.write_text(json.dumps([{'hosts': 'localhost', 'gather_facts': False, 'tasks': tasks}]))
            environment = dict(os.environ, ANSIBLE_LOCAL_TEMP=directory,
                               ANSIBLE_REMOTE_TEMP=directory, ANSIBLE_NOCOLOR='1')
            result = subprocess.run(['ansible-playbook', '-i', 'localhost,', '-c', 'local', str(playbook)],
                                    capture_output=True, text=True, env=environment, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            for role in ['postgresql', 'garage', 'garage-ui']:
                with self.subTest(role=role):
                    mounts = json.loads((root / (role + '.json')).read_text())
                    self.assertIsInstance(mounts, list)
                    self.assertTrue(mounts)
                    self.assertTrue(all(isinstance(m, str) and m.startswith('/') for m in mounts), mounts)
                    if role != 'postgresql':
                        self.assertEqual(len(mounts), 1)
                        target, options = mounts[0].split(':', 1)
                        self.assertEqual(target, '/tmp')
                        self.assertTrue({'nosuid', 'nodev', 'noexec', 'size=16m'} <= set(options.split(',')))


if __name__ == '__main__':
    unittest.main()
