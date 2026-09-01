#!/usr/bin/env python3
"""W3-7 RED/GREEN tests for durable last-good tab snapshots.

The live snapshot is updated in-place during normal watchdog/suspend work.
W3-7 requires a second durable copy so a later bad or incomplete write cannot
remove the most recent known-good workspace from the recovery path.
"""
import importlib.util
import json
import tempfile
import time
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parent / "restart-api.py"
spec = importlib.util.spec_from_file_location("restart_api_under_test", MODULE_PATH)
ra = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(ra)


def configure(tmp: str) -> tuple[Path, Path]:
    live = Path(tmp) / "tab-snapshot.json"
    good = Path(tmp) / "tab-snapshot.last-good.json"
    ra.SNAPSHOT_FILE = str(live)
    ra.LAST_GOOD_SNAPSHOT_FILE = str(good)
    ra.SNAPSHOT_MAX = 10
    ra.SNAPSHOT_STALE_S = 300
    return live, good


def test_snapshot_writes_last_good_copy_atomically() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        live, good = configure(tmp)
        ra.page_urls = lambda: [
            "https://crm.example/",
            "https://inbox.example/",
        ]
        ra.snapshot_tabs()
        expected = ["https://crm.example/", "https://inbox.example/"]
        assert json.loads(live.read_text())["urls"] == expected
        assert json.loads(good.read_text())["urls"] == expected
        assert not Path(str(good) + ".tmp").exists()


def test_load_snapshot_recovers_last_good_when_live_is_invalid() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        live, good = configure(tmp)
        good.write_text(json.dumps({
            "ts": int(time.time()),
            "urls": ["https://crm.example/", "https://inbox.example/"],
        }))
        live.write_text("{not-json")
        assert ra.load_snapshot() == [
            "https://crm.example/", "https://inbox.example/"
        ]


def test_valid_empty_live_snapshot_does_not_resurrect_old_workspace() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        live, good = configure(tmp)
        good.write_text(json.dumps({
            "ts": int(time.time()),
            "urls": ["https://old.example/"],
        }))
        live.write_text(json.dumps({"ts": int(time.time()), "urls": []}))
        assert ra.load_snapshot() == []


def test_snapshot_backfills_missing_last_good_from_richer_live_state() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        live, good = configure(tmp)
        expected = ["https://crm.example/", "https://inbox.example/"]
        live.write_text(json.dumps({"ts": int(time.time()), "urls": expected}))
        ra.page_urls = lambda: ["https://crm.example/"]
        ra.snapshot_tabs()
        assert json.loads(good.read_text())["urls"] == expected


def test_load_snapshot_prefers_valid_live_snapshot() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        live, good = configure(tmp)
        good.write_text(json.dumps({
            "ts": int(time.time()),
            "urls": ["https://old.example/"],
        }))
        live.write_text(json.dumps({
            "ts": int(time.time()),
            "urls": ["https://crm.example/", "https://inbox.example/"],
        }))
        assert ra.load_snapshot() == [
            "https://crm.example/", "https://inbox.example/"
        ]


def test_last_good_recovery_still_filters_auth_flow() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        _live, good = configure(tmp)
        good.write_text(json.dumps({
            "ts": int(time.time()),
            "urls": [
                "https://auth.aikumi.app/if/flow/default-authentication-flow/",
                "https://crm.example/",
            ],
        }))
        assert ra.load_snapshot() == ["https://crm.example/"]


def test_owner_mismatch_clears_both_snapshot_copies() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        live, good = configure(tmp)
        live.write_text(json.dumps({"ts": int(time.time()), "urls": [
            "https://foreign.example/"
        ]}))
        good.write_text(json.dumps({"ts": int(time.time()), "urls": [
            "https://foreign.example/"
        ]}))
        ra._slot_user = "alice@example"
        ra._started_for_user = "bob@example"
        ra._chrome_running = lambda: True
        ra.sup_status = lambda: {ra.CHROME_PROG: "RUNNING"}
        ra.subprocess.run = lambda *args, **kwargs: type(
            "Result", (), {"stdout": "", "stderr": "", "returncode": 0}
        )()
        ra.wipe_slot_dirs = lambda: None
        ra.clear_chrome_start = lambda: None
        ra.clear_slot_user = lambda: None
        ra._suspended = False
        ra._do_suspend_impl()
        assert not live.exists()
        assert not good.exists()


TESTS = [
    test_snapshot_writes_last_good_copy_atomically,
    test_load_snapshot_recovers_last_good_when_live_is_invalid,
    test_valid_empty_live_snapshot_does_not_resurrect_old_workspace,
    test_snapshot_backfills_missing_last_good_from_richer_live_state,
    test_load_snapshot_prefers_valid_live_snapshot,
    test_last_good_recovery_still_filters_auth_flow,
    test_owner_mismatch_clears_both_snapshot_copies,
]


if __name__ == "__main__":
    passed = 0
    for test in TESTS:
        try:
            test()
            print(f"PASS {test.__name__}")
            passed += 1
        except Exception as exc:
            print(f"FAIL {test.__name__}: {exc}")
    print(f"{passed}/{len(TESTS)} passed")
    raise SystemExit(0 if passed == len(TESTS) else 1)
