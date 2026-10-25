"""Regression checks for the AdGuard rewrite reconciliation contract."""

import importlib.util
import unittest
from unittest.mock import patch
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "files" / "reconcile.py"
SPEC = importlib.util.spec_from_file_location("adguard_reconcile", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FakeAPI:
    def __init__(self, rewrites, enabled=True):
        self.rewrites = list(rewrites)
        self.enabled = enabled
        self.writes = []

    def require(self, path, method="GET", body=None):
        if method != "GET":
            self.writes.append((path, body))
        if path == "rewrite/list":
            return list(self.rewrites)
        if path == "rewrite/delete":
            self.rewrites.remove(body)
        elif path == "rewrite/add":
            self.rewrites.append(body)
        elif path == "rewrite/settings":
            return {"enabled": self.enabled}
        elif path == "rewrite/settings/update":
            self.enabled = body["enabled"]
        else:
            raise AssertionError(f"unexpected API path: {path}")
        return None


class RewriteConvergenceTests(unittest.TestCase):
    def test_removed_nextcloud_rewrite_changes_once(self):
        desired = [{"domain": "gitea.home.example", "answer": "192.168.1.101"}]
        old = {"domain": "nextcloud.home.net", "answer": "192.168.1.5"}
        api = FakeAPI([old, *desired])

        self.assertEqual(MODULE.reconcile_rewrites(api, desired), 1)
        self.assertEqual(api.rewrites, desired)
        self.assertEqual(MODULE.reconcile_rewrites(api, desired), 0)
        self.assertEqual(len(api.writes), 1)

    def test_changed_answer_and_disabled_rewrites_converge_once(self):
        desired = [{"domain": "adguard.home.net", "answer": "192.168.1.100"}]
        api = FakeAPI(
            [{"domain": "adguard.home.net", "answer": "192.168.1.9"}],
            enabled=False,
        )

        self.assertEqual(MODULE.reconcile_rewrites(api, desired), 3)
        self.assertEqual(api.rewrites, desired)
        self.assertTrue(api.enabled)
        self.assertEqual(MODULE.reconcile_rewrites(api, desired), 0)
        self.assertEqual(len(api.writes), 3)


class BootstrapDetectionTests(unittest.TestCase):
    def test_installed_service_waits_for_dns_readiness_without_reconfiguration(self):
        class StartingAPI:
            calls = 0

            def request(self, path, auth=True):
                if path == "install/get_addresses":
                    return 404, None
                self.calls += 1
                return 200, {"running": self.calls > 1}

        api = StartingAPI()
        with patch.object(MODULE.time, "sleep") as sleep:
            self.assertEqual(MODULE.bootstrap(api, {}, "server", "unused",
                                             "192.168.1.100", "192.168.1.100", 3000), 0)
        sleep.assert_called_once_with(2)
        self.assertEqual(api.calls, 2)

    def test_installed_service_hiding_setup_endpoint_is_not_reconfigured(self):
        class InstalledAPI:
            def request(self, path, auth=True):
                if path == "install/get_addresses":
                    return 404, None
                if path == "status":
                    return 200, {"running": True}
                raise AssertionError(path)

        self.assertEqual(
            MODULE.bootstrap(
                InstalledAPI(),
                {},
                "server",
                "unused",
                "192.168.1.100",
                "192.168.1.100",
                3000,
            ),
            0,
        )


if __name__ == "__main__":
    unittest.main()
