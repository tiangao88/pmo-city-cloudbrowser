"""Internal PMO identity-link service bootstrap."""

from __future__ import annotations

import os

from cloudbrowser.identity_link_service import IdentityLinkStore, create_identity_link_server


def _required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"{name} is required")
    return value


def main() -> None:
    server = create_identity_link_server(
        IdentityLinkStore(os.environ.get("CB_IDENTITY_LINK_DB", "/data/identity-links.sqlite3")),
        shared_secret=_required("CB_IDENTITY_LINK_SHARED_SECRET"),
        oidc_issuer=_required("CB_OIDC_ISSUER"),
        tinyauth_realm=_required("CB_TINYAUTH_REALM"),
        address=("0.0.0.0", int(os.environ.get("CB_PORT", "8091"))),
    )
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
