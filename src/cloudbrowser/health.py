"""Small dependency-free health endpoint shared by service images."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from typing import Any


def health_payload(*, component: str, instance_id: str, release_version: str) -> dict[str, str]:
    """Return bounded non-sensitive health metadata."""
    values = {
        "status": "ok",
        "component": component,
        "instance_id": instance_id,
        "release_version": release_version,
    }
    if any(not isinstance(value, str) or not value for value in values.values()):
        raise ValueError("health metadata must be non-empty text")
    return values


def create_health_server(
    *,
    component: str,
    instance_id: str,
    release_version: str,
    address: tuple[str, int] = ("127.0.0.1", 8080),
) -> ThreadingHTTPServer:
    """Create a server exposing only GET /health and GET /ready."""
    payload = health_payload(
        component=component,
        instance_id=instance_id,
        release_version=release_version,
    )

    class HealthHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib HTTP handler contract
            if self.path not in ("/health", "/ready"):
                self.send_error(404)
                return
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            # Health probes must never write request data or environment values.
            return

    return ThreadingHTTPServer(address, HealthHandler)


def serve_health(
    *, component: str, instance_id: str, release_version: str, port: int = 8080
) -> None:
    server = create_health_server(
        component=component,
        instance_id=instance_id,
        release_version=release_version,
        address=("0.0.0.0", port),
    )
    try:
        server.serve_forever()
    finally:
        server.server_close()
