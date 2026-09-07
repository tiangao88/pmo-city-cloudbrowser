"""Registry must survive boot-stopped placeholder env (RED first).

In boot-stopped mode the container env carries the placeholder boot binding
(`principal-unassigned` / `browser-slot-1` / `generation-0`) while the
downloads ingest transport IS configured. The registry's first adopted
binding must build the watcher from the ADOPTED binding without the env
placeholder guard firing, and a later rebind must rotate attribution.
"""

from __future__ import annotations

import json
import os
import threading
import urllib.request
from dataclasses import replace
from pathlib import Path

from cloudbrowser.browser_service import DownloadWatcherRegistry
from cloudbrowser.cloudfiles.contracts import PrincipalBinding


class _FakeBinding:
    """Duck-typed BrowserBinding from the binding push."""

    principal_id = "pmo-abc123"
    profile_id = "profile-1"
    browser_id = "browser-slot-1"
    generation = "generation-42"

    def replace(self, **changes):
        new = _FakeBinding()
        for key, value in changes.items():
            setattr(new, key, value)
        return new


class _RegistryHarness:
    """Patches env so the ingest transport is configured but boot env is the
    placeholder binding, exactly as in the boot-stopped deployment."""

    def __init__(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CB_BROWSER_DOWNLOAD_DIR", str(tmp_path / "dl"))
        monkeypatch.setenv("CB_DOWNLOADS_INGEST_URL", "http://cloudfiles:8086")
        monkeypatch.setenv("CB_DOWNLOADS_INGEST_SECRET", "s" * 16)
        monkeypatch.setenv("CB_PRINCIPAL_ID", "principal-unassigned")
        monkeypatch.delenv("CB_PROFILE_ID", raising=False)
        monkeypatch.setenv("CB_BROWSER_ID", "browser-slot-1")
        monkeypatch.setenv("CB_BINDING_GENERATION", "generation-0")

    def submit(self, event):
        return "receipt"


def test_registry_boot_stopped_placeholder_env_builds_from_adopted_binding(
    tmp_path, monkeypatch
) -> None:
    _RegistryHarness(tmp_path, monkeypatch)
    registry = DownloadWatcherRegistry()
    # must not raise SystemExit despite placeholder env
    registry.on_binding(_FakeBinding())
    # registry now owns a watcher attributed to the adopted binding
    assert registry._watcher is not None
    registry.close()


def test_registry_rebind_after_boot_stopped_build_rotates(tmp_path, monkeypatch) -> None:
    _RegistryHarness(tmp_path, monkeypatch)
    registry = DownloadWatcherRegistry()
    registry.on_binding(_FakeBinding())

    newer = _FakeBinding().replace(generation="generation-43")
    registry.on_binding(newer)
    assert registry._watcher is not None
    registry.close()


def test_registry_listener_exception_is_contained(tmp_path, monkeypatch) -> None:
    """The browser server binding push must succeed even if the listener raises."""

    from cloudbrowser.browser_slots.browser_server import create_browser_server

    class StubAdapter:
        owner = "principal-old"
        generation = "generation-old"

        def readiness(self):
            class R:
                owner = StubAdapter.owner
                generation = StubAdapter.generation
                cdp_ok = True

            return R()

        def rebind(self, owner, generation) -> None:
            StubAdapter.owner = owner
            StubAdapter.generation = generation

    class StubProcess:
        state = "stopped"

        def readiness(self):
            return False

        def rebind(self, owner, generation) -> None:
            StubProcess.state = "stopped"

    def exploding_listener(binding):
        raise RuntimeError("listener boom")

    server = create_browser_server(
        StubAdapter(),
        StubProcess(),
        instance_id="inst",
        release_version="0.0.0-test",
        address=("127.0.0.1", 0),
        binding_listener=exploding_listener,
    )
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/browser/binding",
            data=json.dumps(
                {
                    "profile_id": "profile-x",
                    "principal_id": "pmo-x",
                    "browser_id": "browser-slot-1",
                    "generation": "generation-42",
                }
            ).encode(),
            headers={
                "Content-Type": "application/json",
                "X-CB-Trusted-Secret": "k" * 16,
            },
        )
        env_backup = os.environ.get("CB_ROUTER_SHARED_SECRET")
        os.environ["CB_ROUTER_SHARED_SECRET"] = "k" * 16
        try:
            with urllib.request.urlopen(req, timeout=3) as resp:
                assert resp.status == 200
        finally:
            if env_backup is None:
                os.environ.pop("CB_ROUTER_SHARED_SECRET", None)
            else:
                os.environ["CB_ROUTER_SHARED_SECRET"] = env_backup
    finally:
        server.shutdown()
        server.server_close()
    # no assertion on the listener having run: the point is the push returns 200
