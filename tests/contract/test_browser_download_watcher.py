"""Production browser-download watcher contract tests (RED first).

The watcher is the browser-side half of the secure local-filesystem handoff:
Chromium writes into a server-configured download directory and the watcher
emits only completed, regular, confined files under the server binding.

Invariants under test:
- only completed files are emitted (`.crdownload` partials are excluded);
- symlinks and non-regular entries are never followed or emitted;
- oversized files are skipped and retained for operator attention;
- unsafe names are skipped;
- a failed submit keeps the file for retry (no loss, safe duplicates);
- receipts and events never leak the raw principal or absolute path;
- the poll loop stops cleanly and `close()` is idempotent.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from cloudbrowser.cloudfiles.contracts import PrincipalBinding


def _binding() -> PrincipalBinding:
    return PrincipalBinding(
        principal_id="owner-a@example.test",
        profile_id="profile-a",
        browser_id="browser-a",
        generation="generation-a",
    )


def _receipt(name: str, request_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        name=name,
        size=7,
        status="published",
        request_id=request_id,
        sha256="a" * 64,
    )


def _watcher(tmp_path: Path, *, submit=None, max_bytes: int = 1024):
    from cloudbrowser.cloudfiles.browser_downloads import (
        BrowserDownloadWatcher,
        DownloadWatchConfig,
    )

    download_dir = tmp_path / "downloads"
    download_dir.mkdir()
    emitted: list = []

    def default_submit(event):
        # The stream is valid only for the duration of the submit call (the
        # client streams it over HTTP); capture the content inside the call.
        emitted.append((event, event.source.read()))
        return _receipt(event.source_name, event.binding.request_id)

    watcher = BrowserDownloadWatcher(
        DownloadWatchConfig(download_dir=download_dir, binding=_binding(), max_bytes=max_bytes),
        submit=submit or default_submit,
    )
    return watcher, download_dir, emitted


def test_completed_file_is_emitted_with_server_binding_and_removed(tmp_path: Path) -> None:
    watcher, download_dir, emitted = _watcher(tmp_path)
    (download_dir / "report.pdf").write_bytes(b"payload")
    (download_dir / "report.pdf.crdownload").write_bytes(b"partial")

    receipts = watcher.emit_once()

    assert len(receipts) == 1
    assert receipts[0].name == "report.pdf"
    event, content = emitted[0]
    assert event.binding.principal_id == "owner-a@example.test"
    assert event.binding.profile_id == "profile-a"
    assert event.binding.browser_id == "browser-a"
    assert event.binding.generation == "generation-a"
    assert event.source_name == "report.pdf", "only the basename may leave the watcher"
    assert event.size == len(b"payload")
    assert content == b"payload"
    assert event.binding.request_id.startswith("req-")
    assert not (download_dir / "report.pdf").exists(), "completed file is consumed"
    assert (download_dir / "report.pdf.crdownload").exists(), "partial is never consumed"


def test_symlink_and_directory_entries_are_never_emitted(tmp_path: Path) -> None:
    watcher, download_dir, emitted = _watcher(tmp_path)
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"secret-outside")
    (download_dir / "link.pdf").symlink_to(outside)
    (download_dir / "subdir").mkdir()
    (download_dir / "subdir" / "nested.pdf").write_bytes(b"nested")

    assert watcher.emit_once() == []
    assert emitted == []
    assert outside.read_bytes() == b"secret-outside", "symlink target must never be read"


def test_oversized_completed_file_is_skipped_and_kept(tmp_path: Path) -> None:
    watcher, download_dir, emitted = _watcher(tmp_path, max_bytes=4)
    (download_dir / "big.bin").write_bytes(b"12345")

    assert watcher.emit_once() == []
    assert emitted == []
    assert (download_dir / "big.bin").read_bytes() == b"12345"


def test_hidden_and_unsafe_names_are_skipped(tmp_path: Path) -> None:
    watcher, download_dir, emitted = _watcher(tmp_path)
    (download_dir / ".secret.pdf").write_bytes(b"hidden")
    (download_dir / "ok.txt").write_bytes(b"ok")

    receipts = watcher.emit_once()

    assert [receipt.name for receipt in receipts] == ["ok.txt"]
    assert [event.source_name for event, _ in emitted] == ["ok.txt"]
    assert (download_dir / ".secret.pdf").exists()


def test_failed_submit_keeps_file_for_retry(tmp_path: Path) -> None:
    report_attempts = {"count": 0}

    def submit(event):
        if event.source_name == "report.pdf":
            report_attempts["count"] += 1
            if report_attempts["count"] == 1:
                raise RuntimeError("ingest dependency unavailable")
        return _receipt(event.source_name, event.binding.request_id)

    watcher, download_dir, _ = _watcher(tmp_path, submit=submit)
    (download_dir / "report.pdf").write_bytes(b"payload")
    (download_dir / "later.txt").write_bytes(b"later")

    # A failed submit is caught per file: the batch survives, the failed file
    # is kept for the next scan, and other candidates still get processed.
    receipts = watcher.emit_once()
    assert [receipt.name for receipt in receipts] == ["later.txt"]
    assert (download_dir / "report.pdf").exists(), "failed submits must not lose the file"
    assert not (download_dir / "later.txt").exists(), "successful submits are consumed"

    receipts = watcher.emit_once()
    assert [receipt.name for receipt in receipts] == ["report.pdf"]
    assert not (download_dir / "report.pdf").exists()


def test_symlinked_download_dir_is_not_followed(tmp_path: Path) -> None:
    from cloudbrowser.cloudfiles.browser_downloads import completed_downloads

    real = tmp_path / "real"
    real.mkdir()
    (real / "report.pdf").write_bytes(b"payload")
    link = tmp_path / "download-link"
    link.symlink_to(real, target_is_directory=True)

    # A symlinked watch directory is resolved to its target; only regular
    # children under the resolved root are eligible (no escape).
    candidates = completed_downloads(link, max_bytes=1024)
    assert [path.name for path in candidates] == ["report.pdf"]


def test_run_logs_per_file_failures_and_keeps_polling(tmp_path: Path, caplog) -> None:
    import logging

    from cloudbrowser.cloudfiles.browser_downloads import BrowserDownloadWatcher

    attempts = {"count": 0}

    def submit(event):
        attempts["count"] += 1
        raise RuntimeError("receiver unavailable")

    watcher, download_dir, _ = _watcher(tmp_path, submit=submit)
    (download_dir / "report.pdf").write_bytes(b"payload")

    waits: list[float] = []

    class Stop:
        def __init__(self):
            self._done = False

        def wait(self, timeout):
            waits.append(float(timeout))
            if len(waits) >= 5:
                self._done = True
            return self._done

    with caplog.at_level(logging.WARNING, logger="cloudbrowser.cloudfiles.browser_downloads"):
        watcher.run(Stop(), interval_s=0.05)

    assert any("receiver unavailable" in record.message for record in caplog.records)
    assert len(waits) >= 5, "the watcher keeps polling across failures"
    assert (download_dir / "report.pdf").exists(), "failed submits keep the file"
    assert attempts["count"] >= 4, "each scan retries the failed file"


def test_receipts_and_events_never_leak_principal_or_path(tmp_path: Path) -> None:
    watcher, download_dir, emitted = _watcher(tmp_path)
    (download_dir / "report.pdf").write_bytes(b"payload")

    receipts = watcher.emit_once()
    text = str(receipts[0])
    assert "owner-a@example.test" not in text
    assert str(download_dir) not in text
    event = emitted[0]
    assert not hasattr(event, "principal_id")
    assert not hasattr(event, "destination")
    assert not hasattr(event, "path")


def test_run_polls_until_stop_event_and_close_is_idempotent(tmp_path: Path) -> None:
    watcher, download_dir, _ = _watcher(tmp_path)
    stop = threading.Event()
    thread = threading.Thread(
        target=watcher.run,
        args=(stop,),
        kwargs={"interval_s": 0.01},
        daemon=True,
    )
    thread.start()
    (download_dir / "a.txt").write_bytes(b"a")

    deadline = time.monotonic() + 5
    while (download_dir / "a.txt").exists() and time.monotonic() < deadline:
        time.sleep(0.02)

    stop.set()
    thread.join(timeout=3)
    assert not thread.is_alive()
    assert not (download_dir / "a.txt").exists()

    watcher.close()
    watcher.close()
    with pytest.raises(RuntimeError, match="closed"):
        watcher.emit_once()


def test_watch_config_requires_absolute_directory_and_positive_limit(tmp_path: Path) -> None:
    from cloudbrowser.cloudfiles.browser_downloads import DownloadWatchConfig

    with pytest.raises(ValueError, match="absolute"):
        DownloadWatchConfig(download_dir=Path("relative"), binding=_binding())
    with pytest.raises(ValueError, match="positive"):
        DownloadWatchConfig(download_dir=tmp_path / "d", binding=_binding(), max_bytes=0)
