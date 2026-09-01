#!/usr/bin/env python3
"""RED/GREEN regression tests for the stale-auth-flow recovery incident.

The live incident had two independent failure modes:
- Authentik MFA/auth-flow URLs were accepted into the persistent tab snapshot;
- a same-owner wake returned before the existing zero-tab browser got the
  normal restore/homepage consumer.

These tests import the real restart-api module and use only deterministic
stubs.  They do not start Chrome or a server and never create or close tabs.
"""
import importlib.util
import json
import tempfile
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("restart-api.py")
spec = importlib.util.spec_from_file_location("restart_api_under_test", MODULE_PATH)
ra = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(ra)

AUTH_FLOW = (
    "https://auth.aikumi.app/if/flow/default-authentication-flow/"
    "?next=%2Fapplication%2Fo%2Fauthorize%3Fclient_id%3Dtest"
)
AUTH_ERROR = "https://auth.aikumi.app/error"
APP = "https://crm.getunlatch.com/dashboard"


def test_auth_flow_is_not_sso_snapshot_material() -> None:
    assert ra._is_sso_error(AUTH_FLOW), "Authentik auth-flow must be rejected"
    assert ra._is_sso_error(AUTH_ERROR), "legacy Authentik error remains rejected"


def test_snapshot_and_load_drop_auth_flow() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "tab-snapshot.json"
        ra.SNAPSHOT_FILE = str(path)
        ra.page_urls = lambda: [AUTH_FLOW, APP]
        ra.snapshot_tabs()
        assert json.loads(path.read_text())["urls"] == [APP]

        path.write_text(json.dumps({"ts": 1, "urls": [AUTH_FLOW, APP]}))
        assert ra.load_snapshot() == [APP]


def test_same_owner_zero_tab_wake_requests_restore() -> None:
    calls = []
    ra._slot_user = "spike-user@aikumi.pro"
    ra._slot_index = 1
    ra._need_restore = False
    ra._restore_done = True
    ra._suspended = True
    ra._grace_until = 123.0
    ra._chrome_running = lambda: True
    ra.page_urls = lambda: []
    ra.restore_tabs = lambda: calls.append("restore")

    out = ra._do_wake_impl("spike-user@aikumi.pro")

    assert out.get("ok") is True
    assert calls == ["restore"], calls


if __name__ == "__main__":
    tests = [
        test_auth_flow_is_not_sso_snapshot_material,
        test_snapshot_and_load_drop_auth_flow,
        test_same_owner_zero_tab_wake_requests_restore,
    ]
    passed = 0
    for test in tests:
        try:
            test()
            print(f"PASS {test.__name__}")
            passed += 1
        except Exception as exc:
            print(f"FAIL {test.__name__}: {exc}")
    print(f"{passed}/{len(tests)} passed")
    raise SystemExit(0 if passed == len(tests) else 1)
