"""CloudFiles contracts and value objects.

Boundary invariants from
`specs/proposals/v0.2/92-cloudfiles-route-response-matrix.md` and the public
contract `specs/contracts/cloudfiles/v1/README.md`.
"""

from __future__ import annotations

from dataclasses import dataclass
import re


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class CloudFilesError(Exception):
    """Base class for all CloudFiles errors."""


class OwnerBindingUnavailable(CloudFilesError):
    """The server cannot derive a principal binding for this request."""


class Unauthorized(CloudFilesError):
    """The request lacks a valid TinyAuth session."""


class InvalidName(CloudFilesError):
    """The supplied name is not a safe flat filename."""


class NotFound(CloudFilesError):
    """The owner has no such retrievable file."""


class OwnerMismatch(CloudFilesError):
    """The supplied path attempts to escape the server-bound owner area."""


class TooLarge(CloudFilesError):
    """The request or payload exceeds a configured limit."""


class DependencyUnavailable(CloudFilesError):
    """An internal dependency (storage, scanner, identity) is unreachable."""


class Forbidden(CloudFilesError):
    """The authenticated subject cannot complete the request."""


# ---------------------------------------------------------------------------
# Identity / binding
# ---------------------------------------------------------------------------


_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_PRINCIPAL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@:+-]{0,255}$")


@dataclass(frozen=True)
class PrincipalBinding:
    """Server-derived principal and browser binding for one request.

    The binding is constructed by the identity resolver from the TinyAuth
    session and an internal lookup; it is never derived from client-supplied
    headers or query strings.
    """

    principal_id: str
    profile_id: str = "profile-unassigned"
    browser_id: str = "browser-unassigned"
    generation: str = "generation-0"
    request_id: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.principal_id, str) or not _PRINCIPAL.fullmatch(self.principal_id):
            raise ValueError("principal_id must be bounded non-empty text")
        for key, value in (
            ("profile_id", self.profile_id),
            ("browser_id", self.browser_id),
            ("generation", self.generation),
            ("request_id", self.request_id),
        ):
            if not isinstance(value, str) or not _TOKEN.fullmatch(value or "profile-unassigned"):
                raise ValueError(f"{key} must be bounded non-empty text")


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FileEntry:
    """Safe metadata exposed through the public listing."""

    name: str
    size: int
    mtime: int

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("name must be non-empty text")
        if not isinstance(self.size, int) or self.size < 0:
            raise ValueError("size must be a non-negative integer")
        if not isinstance(self.mtime, int) or self.mtime < 0:
            raise ValueError("mtime must be a non-negative integer")


@dataclass(frozen=True)
class IngestRequest:
    """A bounded ingest request from the browser slot."""

    binding: PrincipalBinding
    source_name: str
    size: int
    content: bytes = b""
