#!/usr/bin/env python3
"""Focused regression tests for restart-api tab snapshot semantics."""

import importlib.util
import json
import tempfile
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("restart-api.py")
spec = importlib.util.spec_from_file_location("restart_api_under_test", MODULE_PATH)
ra = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(ra)


def use_temp_snapshot(tmp: str) -> Path:
    path = Path(tmp) / "tab-snapshot.json"
    ra.SNAPSHOT_FILE = str(path)
    ra.SNAPSHOT_MAX = 10
    return path


def test_home_only_is_not_persisted() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = use_temp_snapshot(tmp)
        ra.page_urls = lambda: ["https://pmo.city/"]
        ra.snapshot_tabs()
        assert not path.exists(), "fallback-only homepage must not be snapshotted"


def test_home_is_persisted_when_part_of_workspace() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = use_temp_snapshot(tmp)
        ra.page_urls = lambda: [
            "https://agenticpmo.org/",
            "https://pmo.city/",
            "https://exa.ai/",
        ]
        ra.snapshot_tabs()
        urls = json.loads(path.read_text())["urls"]
        assert urls == [
            "https://agenticpmo.org/",
            "https://pmo.city/",
            "https://exa.ai/",
        ], f"multi-tab homepage was lost: {urls!r}"


def test_home_is_restored_only_with_other_tabs() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = use_temp_snapshot(tmp)
        path.write_text(json.dumps({
            "ts": 1,
            "urls": ["https://agenticpmo.org/", "https://pmo.city/"],
        }))
        assert ra.load_snapshot() == [
            "https://agenticpmo.org/", "https://pmo.city/"
        ]
        path.write_text(json.dumps({"ts": 1, "urls": ["https://pmo.city/"]}))
        assert ra.load_snapshot() == [], "fallback-only homepage must not restore"


def test_authentik_flow_is_never_persisted_or_restored() -> None:
    auth_flow = (
        "https://auth.aikumi.app/if/flow/default-authentication-flow/"
        "?next=%2Fapplication%2Fo%2Fauthorize%3Fclient_id%3Dtest"
    )
    app = "https://crm.getunlatch.com/dashboard"
    with tempfile.TemporaryDirectory() as tmp:
        path = use_temp_snapshot(tmp)
        ra.page_urls = lambda: [auth_flow, app]
        ra.snapshot_tabs()
        assert json.loads(path.read_text())["urls"] == [app]
        path.write_text(json.dumps({"ts": 1, "urls": [auth_flow, app]}))
        assert ra.load_snapshot() == [app]


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
        test_home_only_is_not_persisted,
        test_home_is_persisted_when_part_of_workspace,
        test_home_is_restored_only_with_other_tabs,
        test_authentik_flow_is_never_persisted_or_restored,
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
