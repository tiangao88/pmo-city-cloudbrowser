"""Bounded parsing of TinyAuth forward-auth attributes.

The edge headers are authentication evidence, not an identity database. The
only authoritative keys are the OIDC ``Remote-Sub`` (when present) or the
namespaced TinyAuth-local ``Remote-User`` fallback. ``Remote-Email`` is kept
only as non-authoritative metadata and is never returned as a lookup key.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping
import re

_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@:+-]{0,255}$")
_EMAIL_ALLOWED = frozenset("abcdefghijklmnopqrstuvwxyz0123456789._@+-")
_HEADER_NAMES = ("remote-sub", "remote-email", "remote-user", "remote-name", "remote-groups")
IDENTITY_HEADER_NAMES = frozenset(_HEADER_NAMES)
REQUIRED_GROUP = "PMOC_Users"
MAX_GROUP_HEADER_BYTES = 4096
MAX_GROUPS = 32


@dataclass(frozen=True)
class EdgeIdentity:
    """Validated attributes copied by an authenticated edge."""

    email: str | None = None
    sub: str | None = None
    user: str | None = None
    name: str | None = None
    groups: tuple[str, ...] = ()

    @property
    def principal_subject(self) -> str | None:
        """Compatibility view containing only an authoritative edge key.

        This is not the PMO principal ID. In particular, it never falls back
        to email; callers needing authorization must use the identity-link
        resolver.
        """
        return self.sub or self.user

    @property
    def lookup_candidates(self) -> tuple[tuple[str, str], ...]:
        """Return only authoritative lookup candidates in precedence order."""
        if self.sub:
            return (("sub", self.sub),)
        if self.user:
            return (("user", self.user),)
        return ()

    def __repr__(self) -> str:
        return (
            f"EdgeIdentity(sub={'<present>' if self.sub else None}, "
            f"email={'<present>' if self.email else None}, "
            f"user={'<present>' if self.user else None}, groups={len(self.groups)})"
        )


def _present(headers: Mapping[str, object], name: str) -> bool:
    lowered = name.lower()
    return any(str(key).lower() == lowered for key in headers)


def _take(headers: Mapping[str, object], name: str) -> str | None:
    """Return one case-insensitive header, rejecting duplicate spellings."""
    lowered = name.lower()
    values = [value for key, value in headers.items() if str(key).lower() == lowered]
    if len(values) != 1 or not isinstance(values[0], str):
        return None
    return values[0]


def _scalar_value(headers: Mapping[str, object], name: str) -> str | None:
    """Return a bounded scalar header, accepting only the trusted tail value."""
    raw = _take(headers, name)
    if raw is None:
        return None
    value = raw.rsplit(",", 1)[-1].strip()
    if not value or len(value) > 256:
        return None
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        return None
    return value


def _bounded_text(value: str) -> bool:
    return bool(value) and len(value) <= 256 and all(
        ord(char) >= 0x20 and ord(char) != 0x7F for char in value
    )


def _groups_value(headers: Mapping[str, object]) -> tuple[str, ...]:
    raw = _take(headers, "remote-groups")
    if raw is None or len(raw.encode("utf-8", errors="ignore")) > MAX_GROUP_HEADER_BYTES:
        return ()
    groups: list[str] = []
    for token in raw.split(","):
        token = token.strip()
        if _bounded_text(token) and _TOKEN.fullmatch(token):
            groups.append(token)
            if len(groups) == MAX_GROUPS:
                break
    return tuple(groups)


def _valid_email(value: str) -> bool:
    if len(value) > 254 or value.count("@") != 1:
        return False
    local, _, domain = value.partition("@")
    if not local or not domain or not local[0].isalnum():
        return False
    if "." not in domain or domain.startswith(("-", ".")) or domain.endswith(("-", ".")):
        return False
    if ".." in local or ".." in domain:
        return False
    return all(char in _EMAIL_ALLOWED for char in value.lower())


def parse_edge_identity(headers: Mapping[str, object]) -> EdgeIdentity | None:
    """Parse edge attributes, returning ``None`` on malformed authority."""
    sub_present = _present(headers, "remote-sub")
    user_present = _present(headers, "remote-user")
    email_present = _present(headers, "remote-email")
    name_present = _present(headers, "remote-name")

    sub = _scalar_value(headers, "remote-sub")
    email = _scalar_value(headers, "remote-email")
    user = _scalar_value(headers, "remote-user")
    name = _scalar_value(headers, "remote-name")
    groups = _groups_value(headers)

    # A present authoritative header that cannot be parsed must not silently
    # turn into the other identity mode.
    if sub_present and (sub is None or not _TOKEN.fullmatch(sub)):
        return None
    if user_present and (user is None or not _TOKEN.fullmatch(user)):
        return None
    if email_present and (email is None or not _valid_email(email)):
        return None
    if name_present and (name is None or not _bounded_text(name)):
        return None
    if email is not None:
        email = email.lower()
    if sub is None and user is None and email is None:
        return None
    return EdgeIdentity(email=email, sub=sub, user=user, name=name, groups=groups)


class PrincipalMapError(ValueError):
    """Static principal maps are no longer a supported authority."""


class PrincipalMap:
    """Reject construction of the superseded static map."""

    def __init__(self, **kwargs) -> None:
        raise PrincipalMapError("static principal maps are not supported")

    @classmethod
    def from_file(cls, path):
        raise PrincipalMapError("static principal maps are not supported")

    def resolve(self, identity: EdgeIdentity) -> str | None:
        """Return one mapped PMO user ID for compatibility-only tests.

        This class is retained solely to make the obsolete static-map contract
        fail closed in tests; production code uses IdentityLinkClient.
        """
        if not isinstance(identity, EdgeIdentity) or REQUIRED_GROUP not in identity.groups:
            return None
        return None


def build_principal_map():
    raise PrincipalMapError("static principal maps are not supported")


__all__ = [
    "EdgeIdentity",
    "IDENTITY_HEADER_NAMES",
    "MAX_GROUPS",
    "MAX_GROUP_HEADER_BYTES",
    "PrincipalMap",
    "PrincipalMapError",
    "REQUIRED_GROUP",
    "parse_edge_identity",
]
