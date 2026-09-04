"""Phase 3 gateway configuration and service wiring."""

from __future__ import annotations

from .api import create_cloudfiles_app
from .downloads_client import DownloadsClient
from .identity_adapter import resolve_tinyauth_session


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


__all__ = ["build_app"]
