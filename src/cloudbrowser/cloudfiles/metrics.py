"""Bounded CloudFiles operational metrics."""

from __future__ import annotations


class Metrics:
    def __init__(self) -> None:
        self._ingest_count = 0
        self._bytes_ingested = 0
        self._quarantine_count = 0
        self._published_count = 0
        self._purged_count = 0
        self._erasure_count = 0
        self._operational_events = False

    def record_ingest(self, *, principal: str, filename: str, size: int) -> None:
        if size < 0:
            raise ValueError("size must be non-negative")
        self._ingest_count += 1
        self._bytes_ingested += size

    def record_published(self) -> None:
        self._published_count += 1
        self._operational_events = True

    def record_quarantine(self) -> None:
        self._quarantine_count += 1
        self._operational_events = True

    def record_purged(self, count: int) -> None:
        if count < 0:
            raise ValueError("count must be non-negative")
        self._purged_count += count
        self._operational_events = True

    def record_erasure(self) -> None:
        self._erasure_count += 1
        self._operational_events = True

    def snapshot(self) -> dict[str, int]:
        snapshot = {
            "ingest_count": self._ingest_count,
            "bytes_ingested": self._bytes_ingested,
        }
        if self._operational_events:
            snapshot.update(
                {
                    "quarantine_count": self._quarantine_count,
                    "published_count": self._published_count,
                    "purged_count": self._purged_count,
                    "erasure_count": self._erasure_count,
                }
            )
        return snapshot


__all__ = ["Metrics"]
