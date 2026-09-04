"""Retention selection for the CloudFiles durable store."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable, Mapping


class RetentionJanitor:
    def __init__(self, *, retention_days: int = 90, clock=None) -> None:
        if retention_days <= 0:
            raise ValueError("retention_days must be positive")
        self.retention_days = retention_days
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def expired_entries(self, entries: Iterable[Mapping[str, object]]) -> list[str]:
        cutoff = self.clock() - timedelta(days=self.retention_days)
        selected: list[str] = []
        for entry in entries:
            mtime = entry.get("mtime")
            if isinstance(mtime, (int, float)):
                moment = datetime.fromtimestamp(mtime, tz=timezone.utc)
            elif isinstance(mtime, datetime):
                moment = mtime if mtime.tzinfo else mtime.replace(tzinfo=timezone.utc)
            else:
                continue
            if moment < cutoff and isinstance(entry.get("name"), str):
                selected.append(entry["name"])
        return selected

    def cutoff_timestamp(self) -> float:
        """Return the retention cutoff as a Unix timestamp (for store purges)."""
        return self.clock().timestamp() - timedelta(days=self.retention_days).total_seconds()


def purge_summary(removed: Iterable[str]) -> dict[str, int]:
    """Reduce a purge result to a bounded, redacted count (threat T14)."""

    return {"purged_count": len(tuple(removed))}


__all__ = ["RetentionJanitor", "purge_summary"]
