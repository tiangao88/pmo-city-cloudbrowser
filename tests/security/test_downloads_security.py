"""Additional security contracts for the public downloads boundary."""

from __future__ import annotations

from pathlib import Path

import pytest

from cloudbrowser.downloads.api import create_downloads_server
from cloudbrowser.downloads.contracts import PrincipalIdentity, ServerIdentity
from cloudbrowser.downloads.service import DownloadsService
from cloudbrowser.downloads.store import owner_key


def test_server_uses_injected_identity_resolver_not_remote_email(tmp_path: Path) -> None:
    (tmp_path / owner_key("owner-a@example.test") / "entries").mkdir(parents=True)
    (tmp_path / owner_key("owner-a@example.test") / "entries" / "a.txt").write_bytes(b"A")
    (tmp_path / owner_key("owner-b@example.test") / "entries").mkdir(parents=True)
    (tmp_path / owner_key("owner-b@example.test") / "entries" / "b.txt").write_bytes(b"B")
    service = DownloadsService(store_root=tmp_path)
    calls: list[str] = []

    def resolve(context):
        calls.append(context.headers.get("remote-email", ""))
        return PrincipalIdentity(
            request_id="req-1",
            principal_id="owner-a@example.test",
            profile_id="profile",
            browser_id="browser",
            generation="generation",
        )

    server = create_downloads_server(
        service,
        server_identity=ServerIdentity("downloads", "instance"),
        trusted_secret=b"x" * 32,
        address=("127.0.0.1", 0),
        identity_resolver=resolve,
    )
    import threading
    import urllib.request

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_address[1]}/api/files",
            headers={
                "X-CB-Trusted-Secret": "x" * 32,
                "Remote-Email": "owner-b@example.test",
            },
        )
        with urllib.request.urlopen(request, timeout=2) as response:
            body = response.read()
        assert b"a.txt" in body
        assert b"b.txt" not in body
        assert calls == ["owner-b@example.test"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_file_response_rejects_newline_in_filename(tmp_path: Path) -> None:
    service = DownloadsService(store_root=tmp_path)
    with pytest.raises(Exception):
        service.read_file(
            PrincipalIdentity("req-1", "owner", "profile", "browser", "generation"),
            "a\r\nb.txt",
        )
