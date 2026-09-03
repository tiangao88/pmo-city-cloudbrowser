"""Filename validation and response-header safety for CloudFiles.

Boundary invariants from threat model T4 (path traversal, unsafe filenames)
and T5 (header injection).
"""

from __future__ import annotations

import re
from urllib.parse import unquote

from .contracts import InvalidName


_NAME_MAX = 255
_PRINTABLE_ASCII = re.compile(r"^[\x20-\x7e]+$")
_FORBIDDEN_ASCII = set("\x00\x01\x02\x03\x04\x05\x06\x07\x08\x0b\x0c\x0e\x0f"
                        "\x10\x11\x12\x13\x14\x15\x16\x17\x18\x19\x1a\x1b\x1c"
                        "\x1d\x1e\x1f\x7f")
_DISALLOW_QUOTE = '"'


def validate_name(raw: object) -> str | None:
    """Validate a flat, printable, non-hidden filename.

    Returns the canonical name (after one strict decode pass) or `None` if
    the name is unsafe. The function never raises on user input; it returns
    `None` so callers can decide whether to raise `InvalidName`.

    A name is unsafe when it is empty, contains path separators or
    control characters, contains NUL, decodes to a different value, has
    a hidden prefix, or contains an unprintable character.
    """

    if not isinstance(raw, str) or not raw:
        return None
    if len(raw) > _NAME_MAX * 3:
        return None
    try:
        name = unquote(raw, errors="strict")
    except (UnicodeDecodeError, ValueError):
        return None
    if "%" in name:
        return None
    if not name or len(name) > _NAME_MAX:
        return None
    if name in {".", ".."} or name.startswith("."):
        return None
    if any(c in name for c in ("/", "\\", "\x00")):
        return None
    if any(ord(c) < 0x20 or ord(c) == 0x7F for c in name):
        return None
    return name


def require_name(raw: object) -> str:
    """Same as `validate_name` but raises `InvalidName` for unsafe input."""

    name = validate_name(raw)
    if name is None:
        raise InvalidName("download name is unsafe")
    return name


def allocate_duplicate(base: str, existing: set[str]) -> str:
    """Allocate a suffixed duplicate name that does not already exist.

    `file.pdf` → `file (1).pdf` → `file (2).pdf` → ... up to a bounded limit.
    """

    if base not in existing:
        return base
    if "." in base:
        stem, _, ext = base.rpartition(".")
        prefix = stem + " ("
    else:
        prefix = base + " ("
        ext = ""
    for n in range(1, 1000):
        candidate = f"{prefix}{n}){('.' + ext) if ext else ''}"
        if candidate not in existing:
            return candidate
    raise InvalidName("unable to allocate a duplicate name")


def safe_content_disposition(filename: str) -> str:
    """Return a safe Content-Disposition header value.

    Rejects CRLF and unprintable characters. Quotes inside the filename are
    escaped so the resulting header can be parsed by intermediate proxies.
    """

    name = validate_name(filename)
    if name is None:
        raise InvalidName("filename is unsafe for Content-Disposition")
    if not _PRINTABLE_ASCII.fullmatch(name):
        raise InvalidName("filename contains non-printable characters")
    escaped = name.replace(_DISALLOW_QUOTE, "")
    return f'attachment; filename="{escaped}"'


__all__ = [
    "validate_name",
    "require_name",
    "allocate_duplicate",
    "safe_content_disposition",
    "InvalidName",
]
