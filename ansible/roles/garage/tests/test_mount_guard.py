"""Run the real role entry points in check mode with no verified data mount."""
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest


class MissingMountTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('ansible-playbook'), 'Ansible required')
    def test_both_roles_refuse_before_any_file_or_container_operation(self):
        roles = pathlib.Path(__file__).resolve().parents[2]
        for role in ['garage', 'garage-ui']:
            with self.subTest(role=role), tempfile.TemporaryDirectory() as directory:
                playbook = pathlib.Path(directory) / 'guard.yml'
                playbook.write_text('---\n- hosts: localhost\n  gather_facts: false\n  vars:\n    storage_mounts_verified: false\n  roles:\n    - ' + role + '\n')
                environment = dict(os.environ, ANSIBLE_ROLES_PATH=str(roles), ANSIBLE_LOCAL_TEMP=directory,
                                   ANSIBLE_REMOTE_TEMP=directory, ANSIBLE_NOCOLOR='1')
                result = subprocess.run(['ansible-playbook', '-i', 'localhost,', '-c', 'local', '--check', str(playbook)],
                                        capture_output=True, text=True, env=environment, timeout=30)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('storage_mounts_verified', result.stdout)
                self.assertIn('changed=0', result.stdout)
                self.assertNotIn('Start Garage', result.stdout)
                self.assertNotIn('Create root-owned', result.stdout)


if __name__ == '__main__':
    unittest.main()
