"""Bounded ingest pipeline for the public CloudFiles gateway.

Implements threat T12 (excessive payload) at the ingest layer. The function
copies a source stream into bounded chunks and aborts as soon as the
configured limit is exceeded.
"""

from __future__ import annotations

from io import BytesIO
from typing import BinaryIO, Iterable

from .contracts import TooLarge


_CHUNK_BYTES = 64 * 1024


def bounded_copy(
    *,
    src: BinaryIO | BytesIO | bytes,
    max_bytes: int,
    chunk_bytes: int = _CHUNK_BYTES,
) -> Iterable[bytes]:
    """Yield chunks of `src` until EOF or `max_bytes` is exceeded.

    Raises TooLarge as soon as the cumulative read crosses the cap.
    """

    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    if chunk_bytes <= 0:
        raise ValueError("chunk_bytes must be positive")

    total = 0
    if isinstance(src, (bytes, bytearray)):
        buffer = bytes(src)
        while total < len(buffer):
            end = min(total + chunk_bytes, len(buffer))
            chunk = buffer[total:end]
            total += len(chunk)
            if total > max_bytes:
                raise TooLarge("stream exceeds the bounded cap")
            yield chunk
        return

    while True:
        chunk = src.read(chunk_bytes)
        if not chunk:
            return
        total += len(chunk)
        if total > max_bytes:
            raise TooLarge("stream exceeds the bounded cap")
        yield chunk


__all__ = ["bounded_copy", "TooLarge"]
