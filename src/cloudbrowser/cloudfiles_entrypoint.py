"""CloudFiles gateway service entrypoint.

Configuration is explicit and server-owned. The edge proxy is responsible for
TinyAuth authentication and must provide the validated session context used by
the identity boundary.

The production runtime is assembled by ``create_cloudfiles_runtime`` so the
operational Phase 4 components (scanner, retention janitor, metrics, erasure
hook, redacted quarantine notifier) are wired with fail-closed safe defaults
at startup; lifecycle cleanup runs on every exit path.
"""

from __future__ import annotations

import os
from wsgiref.simple_server import make_server

from cloudbrowser.cloudfiles.runtime import create_cloudfiles_runtime
from cloudbrowser.identity_links import build_identity_link_client

_EDGE_AUTH_TRAEFIK_FORWARDAUTH = "traefik-forwardauth"


def _required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"{name} is required")
    return value


def _port() -> int:
    try:
        value = int(os.environ.get("CB_PORT", "8085"))
    except ValueError as exc:
        raise SystemExit("CB_PORT must be an integer") from exc
    if not 1 <= value <= 65535:
        raise SystemExit("CB_PORT must be between 1 and 65535")
    return value


def _edge_auth_mode() -> str | None:
    """Validate and return the configured edge authentication mode."""
    mode = os.environ.get("CB_EDGE_AUTH")
    if mode is None or mode == "":
        return None
    if mode != _EDGE_AUTH_TRAEFIK_FORWARDAUTH:
        raise SystemExit("CB_EDGE_AUTH must be 'traefik-forwardauth' when set")
    return mode


def main() -> None:
    edge_mode = _edge_auth_mode()
    runtime = create_cloudfiles_runtime(
        downloads_base_url=_required("CB_DOWNLOADS_BASE_URL"),
        shared_secret=_required("CB_DOWNLOADS_SHARED_SECRET"),
        instance_id=_required("CB_INSTANCE_ID"),
        release_version=_required("CB_RELEASE_VERSION"),
        scanner_host=os.environ.get("CB_CLAMAV_HOST", "127.0.0.1"),
    )
    app = runtime.app
    if edge_mode == _EDGE_AUTH_TRAEFIK_FORWARDAUTH:
        identity_client = build_identity_link_client()
        from cloudbrowser.cloudfiles.identity_adapter import edge_session_middleware

        app = edge_session_middleware(app, identity_client=identity_client)
    server = make_server("0.0.0.0", _port(), app)  # type: ignore[arg-type]
    try:
        server.serve_forever()
    finally:
        server.server_close()
        runtime.close()


if __name__ == "__main__":
    main()
