"""Browser service: own Chrome and expose only the restricted adapter API."""

from __future__ import annotations

import os
from pathlib import Path
import shlex
import threading

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


def run_browser_service() -> None:
    process, server, stop_event = build_browser_service()
    process.start()
    watcher = threading.Thread(target=process.watch, args=(stop_event,), daemon=True)
    watcher.start()
    try:
        server.serve_forever()
    finally:
        stop_event.set()
        process.stop()
        server.server_close()
