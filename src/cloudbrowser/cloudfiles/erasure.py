"""GDPR erasure facade for the CloudFiles durable store.

Erasure operates on the production durable layout (``cloudbrowser.downloads``
store: hashed owner roots plus the prior raw-principal roots) so no reference
to a principal survives under the store root (threat T10), and emits a
redacted audit event (threat T14).
"""

from __future__ import annotations

from pathlib import Path

from cloudbrowser.downloads.store import DownloadStore

from .audit import record_erasure
from .identity import hash_principal


def erase_principal(
    *,
    principal: str,
    store_root: Path,
    request_id: str = "ops-erasure",
) -> dict[str, object]:
    """Erase every durable reference to `principal` under `store_root`."""

    DownloadStore(Path(store_root)).erase(principal)
    return record_erasure(principal_hash=hash_principal(principal), request_id=request_id)


__all__ = ["erase_principal"]
