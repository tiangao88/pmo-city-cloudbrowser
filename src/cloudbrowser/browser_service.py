"""Browser service: own Chrome and expose only the restricted adapter API."""

from __future__ import annotations

import hmac
import os
import shlex
import threading
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cloudbrowser.browser_slots.lifecycle import BrowserBinding

from cloudbrowser.browser_slots.basic_auth import BasicAuthCapability
from cloudbrowser.browser_slots.browser_process import (
    BrowserProcess,
    BrowserProcessConfig,
    chrome_version_is_ready,
)
from cloudbrowser.browser_slots.browser_server import create_browser_server
from cloudbrowser.browser_slots.chrome_adapter import ChromeBrowserAdapter, ChromeHttpClient


def build_browser_service() -> tuple[
    BrowserProcess, object, threading.Event, "DownloadWatcherRegistry"
]:
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
            download_dir=(
                Path(download_dir)
                if (download_dir := os.environ.get("CB_BROWSER_DOWNLOAD_DIR"))
                else None
            ),
        ),
        probe=lambda: chrome_version_is_ready(chrome.json_request("/json/version")),
    )
    from cloudbrowser.browser_slots.page_actions import CdpPageActionAdapter, _WebSocket

    # Real page actions (navigate, page_info) via the local DevTools endpoint.
    # click/type stay fail-closed inside the adapter until an approved
    # element-interaction channel exists (decision 2026-09-08).
    page_actions = CdpPageActionAdapter(chrome)
    basic_auth = BasicAuthCapability(
        chrome,
        ws_factory=lambda url, timeout_s: _WebSocket(
            url, open_timeout_s=3.0, command_timeout_s=timeout_s
        ),
    )
    adapter = ChromeBrowserAdapter(
        chrome,
        owner=owner,
        generation=generation,
        start_callback=process.start,
        stop_callback=process.stop,
        page_actions=page_actions,
    )
    registry = DownloadWatcherRegistry()
    server = create_browser_server(
        adapter,
        process,
        instance_id=instance_id,
        release_version=release_version,
        address=("0.0.0.0", service_port),
        binding_listener=registry.on_binding,
        basic_auth=basic_auth,
        broker_submit_secret=os.environ.get("CB_BROKER_SUBMIT_SECRET", ""),
    )
    return process, server, threading.Event(), registry


def build_download_watcher(binding: "object | None" = None):
    """Construct the production download emitter from server configuration.

    The download directory, the internal CloudFiles ingest receiver URL, and
    the shared secret are all server-configured; the owner binding is the
    browser's own server identity (the boot env binding, or an explicitly
    adopted binding passed by the registry after a binding push). Returns
    ``None`` when the transport is not configured, so the browser service
    behaves exactly as before.
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
    principal_id = os.environ.get("CB_PRINCIPAL_ID", "principal-unassigned")
    unassigned = {
        "principal-unassigned",
        "profile-unassigned",
        "browser-unassigned",
        "generation-0",
    }
    if binding is None and (
        principal_id in unassigned
        or any(
            os.environ.get(key, default) in unassigned
            for key, default in (
                ("CB_PROFILE_ID", "profile-unassigned"),
                ("CB_BROWSER_ID", "browser-unassigned"),
                ("CB_BINDING_GENERATION", "generation-0"),
            )
        )
    ):
        # A download watcher with a placeholder binding would attribute
        # files to a non-identity; refuse to start the transport. An
        # explicitly adopted binding (boot-stopped lazy build) bypasses the
        # env check — the adopted identity IS the real binding.
        raise SystemExit(
            "download watcher requires a real server binding "
            "(CB_PRINCIPAL_ID/CB_PROFILE_ID/CB_BROWSER_ID/CB_BINDING_GENERATION)"
        )
    from cloudbrowser.cloudfiles.browser_downloads import (
        BrowserDownloadCompleted,
        BrowserDownloadWatcher,
        DownloadWatchConfig,
        IngestReceipt,
    )
    from cloudbrowser.cloudfiles.contracts import PrincipalBinding
    from cloudbrowser.cloudfiles.ingest_client import IngestClient
    if binding is not None and not isinstance(binding, PrincipalBinding):
        raise SystemExit("download watcher binding is invalid")

    if binding is None:
        principal_id = os.environ.get("CB_PRINCIPAL_ID", "principal-unassigned")
        binding = PrincipalBinding(
            principal_id=principal_id,
            profile_id=os.environ.get("CB_PROFILE_ID", "profile-unassigned"),
            browser_id=os.environ.get("CB_BROWSER_ID", "browser-unassigned"),
            generation=os.environ.get("CB_BINDING_GENERATION", "generation-0"),
        )
    else:
        principal_id = binding.principal_id
    try:
        config = DownloadWatchConfig(
            download_dir=Path(download_dir),
            binding=binding,
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


_MAX_BINDING_FIELD = 256


def parse_binding_push(payload: object, *, provided_secret: str | None) -> "BrowserBinding":  # noqa: F821
    """Validate a trusted-secret-gated binding push from the slot supervisor.

    The secret gate runs before any payload inspection: without a configured
    ``CB_ROUTER_SHARED_SECRET`` (or with a mismatching value) the push is
    refused regardless of contents. Only the allowlisted ``BrowserBinding``
    fields are accepted — no free-form keys.
    """

    from cloudbrowser.browser_slots import BrowserBinding

    expected = os.environ.get("CB_ROUTER_SHARED_SECRET")
    if not expected or not provided_secret or not hmac.compare_digest(expected, provided_secret):
        raise PermissionError("binding push rejected: trusted secret mismatch")
    if not isinstance(payload, dict):
        raise ValueError("binding push payload must be an object")
    allowed = {"principal_id", "profile_id", "browser_id", "generation"}
    unknown = set(payload) - allowed
    if unknown:
        raise ValueError(f"binding push has unexpected fields: {sorted(unknown)}")
    missing = allowed - set(payload)
    if missing:
        raise ValueError(f"binding push is missing fields: {sorted(missing)}")
    values: dict[str, str] = {}
    for field in sorted(allowed):
        value = payload[field]
        if (
            not isinstance(value, str)
            or not value
            or len(value) > _MAX_BINDING_FIELD
            or any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in value)
        ):
            raise ValueError(f"binding push field {field!r} is invalid")
        values[field] = value
    return BrowserBinding(
        profile_id=values["profile_id"],
        principal_id=values["principal_id"],
        browser_id=values["browser_id"],
        generation=values["generation"],
    )


class DownloadWatcherRegistry:
    """Owns the browser service's download watcher across binding pushes.

    In eager-start mode the watcher is built at boot from the env binding and
    the registry only rotates its attribution binding on rebinds. In
    boot-stopped mode (CB_BROWSER_AUTOSTART=0) the boot env binding is a
    placeholder, so the watcher is built lazily on the first adopted
    server-minted binding and then rotated on every subsequent push.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._watcher = None
        self._stop_event: threading.Event | None = None

    def attach_stop_event(self, stop_event: threading.Event) -> None:
        self._stop_event = stop_event

    def close(self) -> None:
        with self._lock:
            if self._watcher is not None:
                self._watcher.close()
                self._watcher = None

    def on_binding(self, binding) -> None:
        """Binding-push callback: build or rotate the download watcher."""

        from cloudbrowser.cloudfiles.contracts import PrincipalBinding

        principal = PrincipalBinding(
            principal_id=binding.principal_id,
            profile_id=binding.profile_id,
            browser_id=binding.browser_id,
            generation=binding.generation,
        )
        with self._lock:
            if self._watcher is not None:
                self._watcher.update_binding(principal)
                return
            watcher = build_download_watcher(binding=principal)
            if watcher is None:
                # Transport not configured (dev profiles): attribution is
                # inert, nothing to maintain.
                return
            self._watcher = watcher
            if self._stop_event is not None:
                threading.Thread(
                    target=watcher.run,
                    args=(self._stop_event,),
                    daemon=True,
                ).start()


def _autostart_enabled() -> bool:
    """Return whether Chrome should start eagerly at service boot.

    Defaults to true (the historical eager-start contract). Set
    ``CB_BROWSER_AUTOSTART=0`` for activation-driven slots: the browser
    boots stopped so the supervisor can adopt a server-minted binding
    (adoption is stopped-only) and Chrome starts on the first wake.
    """

    return os.environ.get("CB_BROWSER_AUTOSTART", "1") not in ("0", "false", "no")


def run_browser_service() -> None:
    process, server, stop_event, registry = build_browser_service()
    registry.attach_stop_event(stop_event)
    autostart = _autostart_enabled()
    if autostart:
        process.start()
    watcher = threading.Thread(target=process.watch, args=(stop_event,), daemon=True)
    watcher.start()
    download_watcher = build_download_watcher() if autostart else None
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
        registry.close()
