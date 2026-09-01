#!/usr/bin/env python3
"""Spec 72 regression tests: Chrome never stores credentials and CfT updates
re-run every PMO City customization before launch."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
CUSTOMIZER = Path(os.environ.get("CUSTOMIZER", HERE / "chrome-customize-spec72.py"))
WRAPPER = Path(os.environ.get("WRAPPER", HERE / "slot-prepare-chrome-spec72.sh"))
POLICY_INIT = Path(os.environ.get("POLICY_INIT", HERE / "slot-policy-init-spec72.sh"))
VIEWER_WRAPPER = Path(os.environ.get("VIEWER_WRAPPER", HERE / "prepare-chrome.sh"))
VIEWER_POLICY_INIT = Path(os.environ.get("VIEWER_POLICY_INIT", HERE / "policy-init.conf"))
RESTART_API = Path(os.environ.get("RESTART_API", HERE / "restart-api.py"))


def load_customizer():
    spec = importlib.util.spec_from_file_location("chrome_customize", CUSTOMIZER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {CUSTOMIZER}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class ChromeCustomizationTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_customizer()
        self.td = tempfile.TemporaryDirectory()
        self.root = Path(self.td.name)
        self.profile = self.root / "profile"
        self.default = self.profile / "Default"
        self.default.mkdir(parents=True)
        (self.profile / "Preferences").write_text(json.dumps({
            "credentials_enable_service": True,
            "profile": {"password_manager_enabled": True},
            "autofill": {"profile_enabled": True, "credit_card_enabled": True},
            "session": {"restore_on_startup": 1},
            "translate": {"enabled": True},
        }))
        self.login_db = self.default / "Login Data"
        con = sqlite3.connect(self.login_db)
        con.execute("CREATE TABLE logins (origin_url TEXT, username_value TEXT, password_value BLOB)")
        con.execute("INSERT INTO logins VALUES ('https://example.invalid', 'u', X'0102')")
        con.commit(); con.close()

    def tearDown(self):
        self.td.cleanup()

    def test_profile_security_is_reapplied_and_saved_passwords_are_purged(self):
        policy = self.root / "policy.json"
        policy.write_text(json.dumps(self.mod.REQUIRED_POLICY))
        ext = self.root / "extension"
        ext.mkdir()
        (ext / "manifest.json").write_text(json.dumps({"version": "1.14.0"}))
        self.mod.prepare_profile(
            self.profile, policy, ext,
            browser_version="Google Chrome for Testing 128.0.6613.137",
        )
        prefs = json.loads((self.profile / "Preferences").read_text())
        self.assertIs(prefs["credentials_enable_service"], False)
        self.assertIs(prefs["credentials_enable_autosignin"], False)
        self.assertIs(prefs["profile"]["password_manager_enabled"], False)
        self.assertIs(prefs["autofill"]["profile_enabled"], False)
        self.assertIs(prefs["autofill"]["credit_card_enabled"], False)
        self.assertEqual(prefs["session"]["restore_on_startup"], 5)
        self.assertIs(prefs["translate"]["enabled"], False)
        self.assertFalse(self.login_db.exists(), "legacy Chrome Login Data must be deleted before launch")
        state = json.loads((self.profile / ".pmo-city-customization.json").read_text())
        self.assertEqual(state["browser_version"], "Google Chrome for Testing 128.0.6613.137")
        self.assertEqual(state["extension_version"], "1.14.0")

    def test_policy_install_covers_stock_and_cft_and_disables_storage(self):
        stock = self.root / "chrome" / "policies" / "managed"
        cft = self.root / "chrome_for_testing" / "policies" / "managed"
        self.mod.install_policies([stock, cft])
        for d in (stock, cft):
            p = json.loads((d / "pmo-city-security.json").read_text())
            self.assertIs(p["PasswordManagerEnabled"], False)
            self.assertIs(p["AutofillAddressEnabled"], False)
            self.assertIs(p["AutofillCreditCardEnabled"], False)
            self.assertIs(p["PDFViewerEnabled"], False)

    def test_version_change_refreshes_customization_receipt(self):
        policy = self.root / "policy.json"
        policy.write_text(json.dumps(self.mod.REQUIRED_POLICY))
        ext = self.root / "extension"; ext.mkdir()
        (ext / "manifest.json").write_text('{"version":"1"}')
        self.mod.prepare_profile(self.profile, policy, ext, browser_version="CfT 128")
        self.mod.prepare_profile(self.profile, policy, ext, browser_version="CfT 129")
        state = json.loads((self.profile / ".pmo-city-customization.json").read_text())
        self.assertEqual(state["browser_version"], "CfT 129")

    def test_viewer_wrapper_uses_the_same_version_independent_fail_closed_customizer(self):
        wrapper = VIEWER_WRAPPER.read_text()
        self.assertIn("CFT_CHROME_BIN", wrapper)
        self.assertIn("cft-chrome-current/chrome", wrapper)
        self.assertNotIn('exec "$PROFILE/cft-chrome-128/chrome"', wrapper)
        self.assertIn("pmo-city-chrome-policy.ready", wrapper)
        self.assertIn("chrome-customize.py prepare-profile", wrapper)
        self.assertIn("--restore-mode last-session", wrapper)
        self.assertIn("exec \"$CFT_CHROME_BIN\"", wrapper)

    def test_viewer_policy_init_installs_the_same_mandatory_dual_root_policy(self):
        policy_init = VIEWER_POLICY_INIT.read_text()
        self.assertIn("chrome-customize.py", policy_init)
        self.assertIn("install-policy", policy_init)
        self.assertIn("/etc/opt/chrome/policies/managed", policy_init)
        self.assertIn("/etc/opt/chrome_for_testing/policies/managed", policy_init)
        self.assertIn("pmo-city-chrome-policy.ready", policy_init)
        self.assertNotIn("cp /etc/neko/supervisord/bitwarden-policy.json", policy_init)

    def test_wrapper_is_version_independent_and_fail_closed(self):
        text = WRAPPER.read_text()
        self.assertIn('CFT_CHROME_BIN="${CFT_CHROME_BIN:-', text)
        self.assertIn('for candidate in "$CFT_ROOT"/cft-chrome-*/chrome', text)
        self.assertIn("chrome-customize.py prepare-profile", text)
        self.assertIn("mandatory policy init did not complete", text)
        self.assertLess(text.index("chrome-customize.py prepare-profile"), text.index('exec "$CFT_CHROME_BIN"'))
        self.assertNotIn("exec /home/neko/.config/cft-chrome-128/chrome", text)

    def test_profile_wipe_has_no_version_specific_binary_exception(self):
        restart_api = RESTART_API.read_text()
        self.assertNotIn('if n == "cft-chrome-128"', restart_api)
        self.assertIn("CfT binaries live as siblings", restart_api)

    def test_policy_init_installs_cft_policy_on_every_container_boot(self):
        text = POLICY_INIT.read_text()
        self.assertIn("chrome_for_testing/policies/managed", text)
        self.assertIn('"$CUSTOMIZER" install-policy', text)
        self.assertIn('touch "$READY"', text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
