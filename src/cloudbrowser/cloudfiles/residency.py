"""Deployment residency qualification checks for CloudFiles durable data."""

from __future__ import annotations


_EU_REGION_PREFIXES = ("eu-", "europe-")


def _is_eu(region: object) -> bool:
    return isinstance(region, str) and region.lower().startswith(_EU_REGION_PREFIXES)


def assert_eu_residency(*, host_region: str, volume_region: str) -> bool:
    """Require both compute and durable volume regions to be EU regions."""
    if not _is_eu(host_region) or not _is_eu(volume_region) or host_region.lower() != volume_region.lower():
        raise ValueError("CloudFiles EU residency requires matching EU host and volume regions")
    return True


__all__ = ["assert_eu_residency"]
