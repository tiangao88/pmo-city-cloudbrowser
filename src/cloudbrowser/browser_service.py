"""Browser service: own Chrome and expose only the restricted adapter API."""

from __future__ import annotations

import os
import shlex
import threading
from pathlib import Path

from cloudbrowser.browser_slots.browser_process import (
    BrowserProcess,
    BrowserProcessConfig,
    chrome_version_is_ready,
)
from cloudbrowser.browser_slots.browser_server import create_browser_server
from cloudbrowser.browser_slots.chrome_adapter import ChromeBrowserAdapter, ChromeHttpClient


def build_browser_service() -> tuple[BrowserProcess, object, threading.Event]:
    """Construct the browser process, adapter server, and shutdown signal."""
    instance_id = os.environ.get("CB_INSTANCE_ID")
    release_version = os.environ.get("CB_RELEASE_VERSION")
    if not instance_id or not release_version:
        raise ValueError("instance and release metadata are required")
    owner = os.environ.get("CB_PRINCIPAL_ID", "principal-unassigned")
    generation = os.environ.get("CB_BINDING_GENERATION", "generation-0")
    chrome = ChromeHttpClient(os.environ.get("CB_CHROME_HTTP_URL", "http://127.0.0.1:9222"))
    try:
        chrome_port = int(os.environ.get("CB_CHROME_HTTP_PORT", "9222"))
        service_port = int(os.environ.get("CB_PORT", "9230"))
    except ValueError as exc:
        raise SystemExit("browser ports must be integers") from exc
    process = BrowserProcess(
        BrowserProcessConfig(
            executable=os.environ.get("CB_CHROME_EXECUTABLE", "/usr/bin/google-chrome"),
            profile_dir=Path(os.environ.get("CB_PROFILE_DIR", "/data/profile")),
            http_port=chrome_port,
            owner=owner,
            generation=generation,
            extra_args=tuple(shlex.split(os.environ.get("CB_CHROME_EXTRA_ARGS", ""))),
        ),
        probe=lambda: chrome_version_is_ready(chrome.json_request("/json/version")),
    )
    adapter = ChromeBrowserAdapter(
        chrome,
        owner=owner,
        generation=generation,
        start_callback=process.start,
        stop_callback=process.stop,
    )
    server = create_browser_server(
        adapter,
        process,
        instance_id=instance_id,
        release_version=release_version,
        address=("0.0.0.0", service_port),
    )
    return process, server, threading.Event()


def build_download_watcher():
    """Construct the production download emitter from server configuration.

    The download directory, the internal CloudFiles ingest receiver URL, and
    the shared secret are all server-configured; the owner binding is the
    browser's own server identity. Returns ``None`` when the transport is not
    configured, so the browser service behaves exactly as before.
    """
    download_dir = os.environ.get("CB_BROWSER_DOWNLOAD_DIR")
    ingest_url = os.environ.get("CB_DOWNLOADS_INGEST_URL")
    ingest_secret = os.environ.get("CB_DOWNLOADS_INGEST_SECRET")
    if not download_dir or not ingest_url or not ingest_secret:
        return None
    try:
        max_bytes = int(os.environ.get("CB_BROWSER_DOWNLOAD_MAX_BYTES", str(1024 * 1024 * 1024)))
    except ValueError as exc:
        raise SystemExit("CB_BROWSER_DOWNLOAD_MAX_BYTES must be an integer") from exc
    from cloudbrowser.cloudfiles.browser_downloads import (
        BrowserDownloadCompleted,
        BrowserDownloadWatcher,
        DownloadWatchConfig,
        IngestReceipt,
    )
    from cloudbrowser.cloudfiles.contracts import PrincipalBinding
    from cloudbrowser.cloudfiles.ingest_client import IngestClient

    try:
        config = DownloadWatchConfig(
            download_dir=Path(download_dir),
            binding=PrincipalBinding(
                principal_id=os.environ.get("CB_PRINCIPAL_ID", "principal-unassigned"),
                profile_id=os.environ.get("CB_PROFILE_ID", "profile-unassigned"),
                browser_id=os.environ.get("CB_BROWSER_ID", "browser-unassigned"),
                generation=os.environ.get("CB_BINDING_GENERATION", "generation-0"),
            ),
            max_bytes=max_bytes,
        )
    except ValueError as exc:
        raise SystemExit(f"download watcher configuration is invalid: {exc}") from exc
    client = IngestClient(base_url=ingest_url, shared_secret=ingest_secret)

    def submit(event: BrowserDownloadCompleted) -> IngestReceipt:
        assert event.size is not None, "watcher events always carry the completed size"
        return client.submit(
            binding=event.binding,
            source_name=event.source_name,
            source=event.source,
            size=event.size,
        )

    return BrowserDownloadWatcher(config, submit=submit)


def run_browser_service() -> None:
    process, server, stop_event = build_browser_service()
    process.start()
    watcher = threading.Thread(target=process.watch, args=(stop_event,), daemon=True)
    watcher.start()
    download_watcher = build_download_watcher()
    download_thread = None
    if download_watcher is not None:
        download_thread = threading.Thread(
            target=download_watcher.run,
            args=(stop_event,),
            daemon=True,
        )
        download_thread.start()
    try:
        server.serve_forever()
    finally:
        stop_event.set()
        process.stop()
        server.server_close()
        if download_watcher is not None:
            download_watcher.close()
