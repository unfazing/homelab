"""Regression tests for guarded AdGuard password rotation."""

import argparse
import importlib.util
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[1] / "files" / "rotate_password.py"
SPEC = importlib.util.spec_from_file_location("adguard_rotate_password", SOURCE)
rotation = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(rotation)


class ConfigEditTests(unittest.TestCase):
    def test_only_named_single_users_password_changes(self):
        original = (
            "users:\n  - name: server\n    password: $2a$old\n"
            "auth_attempts: 5\nupstream_dns:\n  - https://example.org/dns-query\n"
        )
        changed = rotation.replace_user_hash(original, "server", "$2y$new")
        self.assertIn("password: $2y$new\n", changed)
        self.assertIn("auth_attempts: 5\n", changed)
        self.assertNotIn("$2a$old", changed)

    def test_multiple_users_are_rejected(self):
        config = (
            "users:\n  - name: server\n    password: old\n"
            "  - name: other\n    password: other\n"
        )
        with self.assertRaisesRegex(RuntimeError, "exactly one"):
            rotation.replace_user_hash(config, "server", "$2y$new")

    def test_password_file_preserves_surrounding_spaces(self):
        with tempfile.TemporaryDirectory() as directory:
            secret = Path(directory) / "password"
            secret.write_text("  a long password with spaces!  \n")
            self.assertEqual(rotation.read_password(secret), "  a long password with spaces!  ")

    def test_password_file_rejects_multiple_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            secret = Path(directory) / "password"
            secret.write_text("first\nsecond\n")
            with self.assertRaisesRegex(RuntimeError, "exactly one"):
                rotation.read_password(secret)


class TransactionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.config = root / "AdGuardHome.yaml"
        self.original = "users:\n  - name: server\n    password: $2a$old\nauth_attempts: 5\n"
        self.config.write_text(self.original)
        self.current = root / "admin-password"
        self.expected = root / "admin-password.expected"
        self.new = root / "admin-password.next"
        self.backup = root / "AdGuardHome.yaml.pre-rotation"
        self.current.write_text("a" * 64 + "\n")
        self.expected.write_text("a" * 64 + "\n")
        self.new.write_text("b" * 64 + "\n")
        self.args = argparse.Namespace(
            current_password_file=str(self.current),
            expected_password_file=str(self.expected),
            new_password_file=str(self.new),
            config_file=str(self.config),
            backup_file=str(self.backup),
            compose_dir=str(root),
            username="server",
            web_address="192.168.1.100",
            web_port=3000,
            dns_address="192.168.1.100",
            verify_name="adguard.home.example.org",
            expected_ip="192.168.1.101",
        )

    def _patch_runtime(self, wait_side_effect=None):
        stack = self.enterContext(patch.object(rotation, "compose"))
        self.enterContext(patch.object(rotation, "web_healthy", return_value=True))
        wait = self.enterContext(patch.object(rotation, "wait_healthy", side_effect=wait_side_effect))
        self.enterContext(
            patch.object(
                rotation.subprocess,
                "run",
                return_value=SimpleNamespace(returncode=0, stdout=b"server:$2y$newhash\n"),
            )
        )
        return stack, wait

    def test_success_commits_guest_secret_after_verification(self):
        compose, wait = self._patch_runtime()
        rotation.rotate(self.args)
        self.assertEqual(self.current.read_text(), "b" * 64 + "\n")
        self.assertIn("password: $2y$newhash", self.config.read_text())
        self.assertFalse(self.backup.exists())
        self.assertEqual(wait.call_count, 1)
        self.assertEqual(compose.call_count, 2)

    def test_failed_new_login_restores_old_config_and_secret(self):
        compose, wait = self._patch_runtime([RuntimeError("new login failed"), None])
        with self.assertRaisesRegex(RuntimeError, "were restored"):
            rotation.rotate(self.args)
        self.assertEqual(self.config.read_text(), self.original)
        self.assertEqual(self.current.read_text(), "a" * 64 + "\n")
        self.assertFalse(self.backup.exists())
        self.assertEqual(wait.call_count, 2)
        self.assertEqual(compose.call_count, 4)

    def test_mismatched_controller_password_fails_before_stopping_dns(self):
        self.expected.write_text("c" * 64 + "\n")
        compose, _ = self._patch_runtime()
        with self.assertRaisesRegex(RuntimeError, "preflight"):
            rotation.rotate(self.args)
        compose.assert_not_called()
        self.assertFalse(self.backup.exists())

    def test_short_new_password_fails_before_stopping_dns(self):
        self.new.write_text("eight888\n")
        compose, _ = self._patch_runtime()
        with self.assertRaisesRegex(RuntimeError, "preflight"):
            rotation.rotate(self.args)
        compose.assert_not_called()

    def test_nine_character_password_is_accepted(self):
        self.new.write_text("ninechars\n")
        self._patch_runtime()
        rotation.rotate(self.args)
        self.assertEqual(self.current.read_text(), "ninechars\n")

    def test_new_password_with_spaces_is_not_trimmed(self):
        chosen = "  passphrase with spaces!  "
        self.new.write_text(chosen + "\n")
        self._patch_runtime()
        with patch.object(rotation.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout=b"server:$2y$newhash\n")) as htpasswd:
            rotation.rotate(self.args)
        self.assertEqual(htpasswd.call_args.kwargs["input"], (chosen + "\n").encode())
        self.assertEqual(self.current.read_text(), chosen + "\n")


if __name__ == "__main__":
    unittest.main()
