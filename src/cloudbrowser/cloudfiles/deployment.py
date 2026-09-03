"""Deployment-time validators for the public CloudFiles gateway.

Threat T6 requires that the public CloudFiles host terminates at the
gateway, never at the downloads container. This module parses the
deploy-time compose files and asserts the routing rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


_HOST_LABEL = re.compile(r"Host\(`([^`]+)`\)")


@dataclass(frozen=True)
class PublicHost:
    """A public host declared in a deployment file."""

    host: str
    target_service: str


def public_hosts(*, compose_path: Path) -> list[PublicHost]:
    """Return the public hosts declared in a compose file.

    Parses a minimal subset of compose YAML: `services` and `labels` that
    look like `traefik.http.routers.<name>.rule=Host(...)`. This is enough
    for the boundary validator; full YAML parsing is out of scope.
    """

    text = compose_path.read_text(encoding="utf-8")
    return _parse(text)


def _parse(text: str) -> list[PublicHost]:
    hosts: list[PublicHost] = []
    current_service: str | None = None
    in_services = False
    in_labels = False
    for raw in text.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if line.startswith("services:"):
            in_services = True
            current_service = None
            in_labels = False
            continue
        if not in_services:
            continue
        if line.startswith("  ") and not line.startswith("    "):
            # Top-level service name
            name = stripped.rstrip(":").strip()
            if name:
                current_service = name
                in_labels = False
            continue
        if line.startswith("    ") and not line.startswith("      "):
            sub = stripped.rstrip(":").strip()
            if sub == "labels":
                in_labels = True
            else:
                in_labels = False
            continue
        if in_labels and current_service is not None and ":" in stripped:
            key, _, value = stripped.partition(":")
            value = value.strip()
            if value.startswith('"') or value.startswith("'"):
                value = value.strip('"\'')
            else:
                value = value
            if "rule" in key and value.startswith("Host("):
                m = _HOST_LABEL.search(value)
                if m:
                    hosts.append(PublicHost(host=m.group(1), target_service=current_service))
    return hosts


def validate_public_routing(*, compose_path: Path) -> None:
    """Raise if any public host targets the downloads container."""

    for host in public_hosts(compose_path=compose_path):
        if host.target_service == "downloads":
            raise ValueError(
                f"public host {host.host!r} targets the downloads container; "
                "CloudFiles requires the gateway to be the public target"
            )


__all__ = [
    "PublicHost",
    "public_hosts",
    "validate_public_routing",
]
