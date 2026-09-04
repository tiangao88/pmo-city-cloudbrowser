"""Bounded HTML template rendering for CloudFiles listings."""

from __future__ import annotations

from html import escape
from typing import Iterable, Mapping
from urllib.parse import quote


def render_listing(entries: Iterable[Mapping[str, object]]) -> bytes:
    """Render a metadata-only listing with escaped text and safe links."""

    rows: list[str] = []
    for entry in entries:
        name = str(entry.get("name", ""))
        raw_size = entry.get("size", 0)
        try:
            size = int(raw_size)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            size = 0
        href = escape(quote(name, safe=""), quote=True)
        label = escape(name)
        rows.append(f'<li><a href="/file/{href}">{label}</a> ({size} bytes)</li>')

    body = (
        '<!doctype html><html><head><meta charset="utf-8">'
        '<title>CloudFiles</title></head><body><h1>CloudFiles</h1><ul>'
        + "".join(rows)
        + "</ul></body></html>"
    )
    return body.encode("utf-8")


__all__ = ["render_listing"]
