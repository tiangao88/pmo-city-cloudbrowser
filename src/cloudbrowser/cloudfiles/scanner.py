"""Scanner ports used by the Phase-2 ingest pipeline."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


class Scanner(Protocol):
    """Scan a staged file and return a bounded verdict."""

    def scan(self, path: Path, *, request_id: str) -> str:
        """Return ``clean`` or a non-clean verdict."""


class CleanScanner:
    """Explicit development scanner for tests and local wiring only."""

    def scan(self, path: Path, *, request_id: str) -> str:
        if not path.is_file():
            raise FileNotFoundError(path)
        return "clean"


__all__ = ["CleanScanner", "Scanner"]
