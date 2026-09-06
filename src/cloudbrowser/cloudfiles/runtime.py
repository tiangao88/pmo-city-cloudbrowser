"""Phase 3 gateway configuration and Phase 4 operational service wiring.

Production assembly: ``create_cloudfiles_runtime`` constructs the public
gateway app (page actions unchanged and fail-closed) together with the
operational components the Phase 4 plan requires:

- ``ClamAvScanner`` with fail-closed production defaults (clamd INSTREAM
  over TCP on 127.0.0.1:3310, 10 s timeout, 1 GiB cap, 64 KiB chunks);
- ``RetentionJanitor`` with the 90-day default;
- bounded ``Metrics`` (never identity or filenames);
- an erasure hook bound to the durable store root (redacted audit events);
- a redacted quarantine notification hook (threat T14) that never raises;
- idempotent lifecycle cleanup (``close``).

No janitor loop, scheduler, or background lifecycle is started here: the
retention sweep and erasure are operator-invoked (see the lifecycle runbook),
and page actions remain exactly the gateway surface.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .api import create_cloudfiles_app
from .audit import redact_event
from .downloads_adapter import DownloadsStoreAdapter
from .downloads_client import DownloadsClient
from .erasure import erase_principal as _erase_principal
from .identity_adapter import resolve_tinyauth_session
from .ingest import IngestPipeline
from .metrics import Metrics
from .retention import RetentionJanitor
from .scanner import ClamAvScanner
from cloudbrowser.downloads.service import DownloadsService

DEFAULT_DOWNLOADS_ROOT = "/data/downloads"
DEFAULT_RETENTION_DAYS = 90
DEFAULT_CLAMAV_HOST = "127.0.0.1"
DEFAULT_CLAMAV_PORT = 3310
DEFAULT_CLAMAV_TIMEOUT_S = 10.0
DEFAULT_MAX_FILE_BYTES = 1024 * 1024 * 1024  # 1 GiB single-file cap
DEFAULT_CHUNK_BYTES = 64 * 1024


class RedactedQuarantineNotifier:
    """Production quarantine notification: log only bounded, redacted fields.

    Applies ``audit.redact_event`` before emission (threat T14) and never
    raises into the ingest pipeline.
    """

    def __init__(self, *, logger=None) -> None:
        self._logger = logger or logging.getLogger("cloudbrowser.cloudfiles")

    def notify_quarantine(self, *, event: dict[str, object]) -> None:
        try:
            self._logger.warning(
                "cloudfiles quarantine event: %s",
                json_dumps_redacted(event),
            )
        except Exception:  # noqa: BLE001 - notification must never break ingest
            return


def json_dumps_redacted(event: dict[str, object]) -> str:
    """Render a redacted event deterministically and bounded."""
    import json

    return json.dumps(redact_event(event), sort_keys=True, separators=(",", ":"))


@dataclass
class CloudFilesRuntime:
    """The assembled production CloudFiles runtime object graph.

    ``app`` is the WSGI gateway (fail-closed page actions). The remaining
    fields are the wired operational components and hooks.
    ``ingest_server`` is the internal browser-download ingest receiver
    bound on ``CB_DOWNLOADS_INGEST_PORT`` (default 8086) when
    ``CB_DOWNLOADS_INGEST_SECRET`` is configured; it is served on a
    daemon thread owned by the runtime and shut down by ``close()``.
    """

    app: object
    scanner: ClamAvScanner
    janitor: RetentionJanitor
    metrics: Metrics
    erase: Callable[..., dict[str, object]]
    notifier: object
    store_root: Path
    pipeline: IngestPipeline
    store: object
    _downloads_service: DownloadsService
    ingest_server: object | None = None
    _closed: bool = False

    def purge(self, *, principal: str) -> dict[str, object]:
        """Purge expired published files and return only redacted fields."""
        cutoff = datetime.fromtimestamp(self.janitor.cutoff_timestamp(), tz=timezone.utc)
        removed = self._downloads_service.store.purge(
            principal, older_than_ts=cutoff.timestamp()
        )
        self.metrics.record_purged(len(removed))
        from .identity import hash_principal

        return {
            "purged_count": len(removed),
            "principal_hash": hash_principal(principal),
        }

    def close(self) -> None:
        """Release runtime resources. Idempotent; safe to call repeatedly."""
        server = self.ingest_server
        if server is not None:
            try:
                server.shutdown()
            except Exception:  # noqa: BLE001 - close must never raise
                pass
            try:
                server.server_close()
            except Exception:  # noqa: BLE001 - close must never raise
                pass
            self.ingest_server = None
        self._closed = True


def build_app(
    *,
    downloads_base_url: str,
    shared_secret: str,
    instance_id: str,
    release_version: str,
):
    """Construct the public gateway from explicit server configuration."""
    return create_cloudfiles_app(
        downloads=DownloadsClient(base_url=downloads_base_url, shared_secret=shared_secret),
        resolve_identity=lambda context: resolve_tinyauth_session(dict(context)),
        server_identity={"instance_id": instance_id, "release_version": release_version},
    )


def create_cloudfiles_runtime(
    *,
    downloads_base_url: str,
    shared_secret: str,
    instance_id: str,
    release_version: str,
    store_root: str | Path = DEFAULT_DOWNLOADS_ROOT,
    dev_store: bool = False,
    scanner_host: str = DEFAULT_CLAMAV_HOST,
    scanner_port: int = DEFAULT_CLAMAV_PORT,
    scanner_timeout_s: float = DEFAULT_CLAMAV_TIMEOUT_S,
    scanner_max_bytes: int = DEFAULT_MAX_FILE_BYTES,
    scanner_chunk_bytes: int = DEFAULT_CHUNK_BYTES,
    retention_days: int = DEFAULT_RETENTION_DAYS,
    notifier_logger=None,
    scanner=None,
    notifier=None,
    clock=None,
    ingest_secret: str | None = None,
    ingest_port: int = 8086,
) -> CloudFilesRuntime:
    """Assemble the production CloudFiles runtime object graph.

    The gateway ``app`` is identical to ``build_app``; operational components
    are constructed with fail-closed safe defaults. The erasure hook is bound
    to ``store_root`` so no caller can point it at another location.
    """

    if retention_days <= 0:
        raise ValueError("retention_days must be positive")
    root = Path(store_root)
    if dev_store and root == Path(DEFAULT_DOWNLOADS_ROOT):
        # Explicit opt-in for local development and test runs: the default
        # production root (/data/downloads) is not writable outside the
        # container, so the caller pins a private scratch store under the
        # working directory. Production entrypoints never set dev_store, and
        # an explicit store_root always wins over the dev fallback.
        root = Path.cwd() / ".cloudfiles-data"
    if not root.is_absolute():
        root = root.resolve()

    metrics = Metrics()
    downloads_service = DownloadsService(store_root=root)
    janitor = RetentionJanitor(retention_days=retention_days, clock=clock)
    if notifier is None:
        quarantine_notifier = RedactedQuarantineNotifier(logger=notifier_logger)
    elif callable(notifier) and not hasattr(notifier, "notify_quarantine"):
        class _CallableNotifier:
            def __init__(self, callback):
                self._callback = callback

            def notify_quarantine(self, *, event):
                self._callback(event)

        quarantine_notifier = _CallableNotifier(notifier)
    else:
        quarantine_notifier = notifier
    # The durable root is explicit and the staging area is kept beside it.
    staging_root = root / ".staging"
    pipeline = IngestPipeline(
        downloads=DownloadsStoreAdapter(downloads_service),
        scanner=scanner or ClamAvScanner(
            host=scanner_host,
            port=scanner_port,
            timeout_s=scanner_timeout_s,
            max_bytes=scanner_max_bytes,
            chunk_bytes=scanner_chunk_bytes,
        ),
        temp_root=staging_root,
        max_bytes=scanner_max_bytes,
        chunk_bytes=scanner_chunk_bytes,
        notifier=quarantine_notifier,  # type: ignore[arg-type]
        metrics=metrics,
    )

    def erase(*, principal: str, request_id: str = "ops-erasure") -> dict[str, object]:
        result = _erase_principal(principal=principal, store_root=root, request_id=request_id)
        metrics.record_erasure()
        return result

    runtime = CloudFilesRuntime(
        app=build_app(
            downloads_base_url=downloads_base_url,
            shared_secret=shared_secret,
            instance_id=instance_id,
            release_version=release_version,
        ),
        scanner=pipeline.scanner,
        janitor=janitor,
        metrics=metrics,
        erase=erase,
        notifier=quarantine_notifier,
        store_root=root,
        pipeline=pipeline,
        store=downloads_service.store,
        _downloads_service=downloads_service,
    )
    _bind_ingest_server(
        runtime,
        instance_id=instance_id,
        ingest_secret=ingest_secret,
        ingest_port=ingest_port,
    )
    return runtime


def _bind_ingest_server(
    runtime: CloudFilesRuntime,
    *,
    instance_id: str,
    ingest_secret: str | None,
    ingest_port: int,
) -> None:
    """Bind and serve the internal ingest receiver when configured.

    The receiver is internal-only (never exposed at the edge): the browser
    service reaches it over the compose network on
    ``CB_DOWNLOADS_INGEST_PORT`` (default 8086). It is started only when
    ``ingest_secret`` is set, so deployments without the transport keep the
    exact prior surface. The serve thread is a daemon owned by the runtime
    and shut down by ``close()``.
    """

    secret = ingest_secret
    if not secret:
        return
    if not 0 <= ingest_port <= 65535:
        raise ValueError("ingest_port must be between 0 (ephemeral) and 65535")
    from .ingest_api import create_ingest_server
    from cloudbrowser.downloads.contracts import ServerIdentity

    server = create_ingest_server(
        runtime.pipeline,
        server_identity=ServerIdentity(component="cloudfiles", instance_id=instance_id),
        trusted_secret=secret.encode("utf-8"),
        address=("0.0.0.0", ingest_port),
    )
    thread = threading.Thread(
        target=server.serve_forever,
        name="cloudfiles-ingest-receiver",
        daemon=True,
    )
    thread.start()
    runtime.ingest_server = server


__all__ = [
    "CloudFilesRuntime",
    "DEFAULT_CHUNK_BYTES",
    "DEFAULT_CLAMAV_HOST",
    "DEFAULT_CLAMAV_PORT",
    "DEFAULT_CLAMAV_TIMEOUT_S",
    "DEFAULT_DOWNLOADS_ROOT",
    "DEFAULT_MAX_FILE_BYTES",
    "DEFAULT_RETENTION_DAYS",
    "RedactedQuarantineNotifier",
    "build_app",
    "create_cloudfiles_runtime",
]
