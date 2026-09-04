"""Bounded CloudFiles operational metrics."""

from __future__ import annotations


class Metrics:
    def __init__(self) -> None:
        self._ingest_count = 0
        self._bytes_ingested = 0

    def record_ingest(self, *, principal: str, filename: str, size: int) -> None:
        if size < 0:
            raise ValueError("size must be non-negative")
        self._ingest_count += 1
        self._bytes_ingested += size

    def snapshot(self) -> dict[str, int]:
        return {
            "ingest_count": self._ingest_count,
            "bytes_ingested": self._bytes_ingested,
        }


__all__ = ["Metrics"]
