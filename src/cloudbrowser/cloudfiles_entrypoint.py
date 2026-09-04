"""CloudFiles gateway service entrypoint.

Configuration is explicit and server-owned. The edge proxy is responsible for
TinyAuth authentication and must provide the validated session context used by
the identity boundary.
"""

from __future__ import annotations

import os
from wsgiref.simple_server import make_server

from cloudbrowser.cloudfiles.runtime import build_app


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


def main() -> None:
    app = build_app(
        downloads_base_url=_required("CB_DOWNLOADS_BASE_URL"),
        shared_secret=_required("CB_DOWNLOADS_SHARED_SECRET"),
        instance_id=_required("CB_INSTANCE_ID"),
        release_version=_required("CB_RELEASE_VERSION"),
    )
    server = make_server("0.0.0.0", _port(), app)  # type: ignore[arg-type]
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
