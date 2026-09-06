"""Download watcher must attribute downloads to the CURRENT binding.

In boot-stopped mode the watcher starts without a binding (placeholder env)
or with the boot binding; after the browser adopts a server-minted binding,
downloads must be attributed to the new binding, never the stale one.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from cloudbrowser.cloudfiles.browser_downloads import (
    BrowserDownloadCompleted,
    BrowserDownloadWatcher,
    DownloadWatchConfig,
)
from cloudbrowser.cloudfiles.contracts import PrincipalBinding


def _binding(pid: str) -> PrincipalBinding:
    return PrincipalBinding(
        principal_id=pid,
        profile_id=f"profile-{pid}",
        browser_id="browser-1",
        generation="generation-1",
    )


def test_watcher_update_binding_rotates_attribution(tmp_path) -> None:
    submitted: list[BrowserDownloadCompleted] = []

    def submit(event: BrowserDownloadCompleted):
        submitted.append(event)
        return "receipt"

    config = DownloadWatchConfig(
        download_dir=Path(tmp_path) / "dl",
        binding=_binding("principal-old"),
    )
    watcher = BrowserDownloadWatcher(config, submit=submit)
    watcher.update_binding(_binding("principal-new"))
    (Path(tmp_path) / "dl").mkdir(parents=True, exist_ok=True)
    (Path(tmp_path) / "dl" / "file.pdf").write_bytes(b"hello")
    receipts = watcher.emit_once()
    assert receipts == ["receipt"]
    assert len(submitted) == 1
    assert submitted[0].binding.principal_id == "principal-new"


def test_watcher_keeps_default_binding_without_update(tmp_path) -> None:
    submitted: list[BrowserDownloadCompleted] = []

    def submit(event: BrowserDownloadCompleted):
        submitted.append(event)
        return "receipt"

    dl = Path(tmp_path) / "dl"
    config = DownloadWatchConfig(download_dir=dl, binding=_binding("principal-boot"))
    watcher = BrowserDownloadWatcher(config, submit=submit)
    dl.mkdir(parents=True, exist_ok=True)
    (dl / "file.pdf").write_bytes(b"hello")
    receipts = watcher.emit_once()
    assert receipts == ["receipt"]
    assert submitted[0].binding.principal_id == "principal-boot"
