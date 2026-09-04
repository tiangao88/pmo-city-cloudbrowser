"""Quarantine decisions for scanner results."""

from __future__ import annotations


def scan_verdict(result: str) -> str:
    """Map an exact clean result to publication; everything else quarantines."""
    return "published" if result == "clean" else "quarantined"


__all__ = ["scan_verdict"]
