"""Deployment naming primitives for isolated CloudBrowser installations."""

from __future__ import annotations

from dataclasses import dataclass
import re


_INSTANCE_ID = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_RESOURCE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


@dataclass(frozen=True)
class InstanceNamespace:
    """Derive every persistent resource name from one explicit instance ID."""

    instance_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.instance_id, str) or not _INSTANCE_ID.fullmatch(self.instance_id):
            raise ValueError("instance_id must be lowercase DNS-safe text")
        if len(self.instance_id) > 63:
            raise ValueError("instance_id is too long")

    @property
    def network(self) -> str:
        return f"{self.instance_id}-network"

    @property
    def secret_namespace(self) -> str:
        return f"{self.instance_id}-secrets"

    @property
    def compose_project(self) -> str:
        return self.instance_id

    def volume(self, resource: str) -> str:
        if not isinstance(resource, str) or not _RESOURCE.fullmatch(resource):
            raise ValueError("resource must be lowercase DNS-safe text")
        return f"{self.instance_id}-{resource}"
