"""RED contracts for the remaining Phase 4/5 operational slice.

These assertions intentionally describe the missing production wiring.  Run
this file before implementing the slice and observe the failures.
"""

from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
import re

import pytest

from cloudbrowser.cloudfiles.contracts import PrincipalBinding
from cloudbrowser.downloads.service import DownloadsService
from cloudbrowser.downloads.store import DownloadStore, owner_key


ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILES = (
    ROOT / "deploy" / "coolify" / "compose.yaml",
    ROOT / "deploy" / "coolify" / "compose.coolify.yaml",
)


def _binding(principal: str = "owner-a@example.test") -> PrincipalBinding:
    return PrincipalBinding(
        principal_id=principal,
        request_id="request-operational",
        profile_id="profile-a",
        browser_id="browser-a",
        generation="generation-a",
    )


def test_runtime_owns_real_pipeline_and_operational_store() -> None:
    from cloudbrowser.cloudfiles.runtime import create_cloudfiles_runtime

    runtime = create_cloudfiles_runtime(
        downloads_base_url="http://downloads:8083",
        shared_secret="s" * 32,
        instance_id="cloudfiles-test",
        release_version="0.2.0-test",
        dev_store=True,
    )
    assert runtime.pipeline is not None
    assert runtime.store is not None
    assert runtime.purge(principal="owner-a@example.test") == {
        "purged_count": 0,
        "principal_hash": runtime.store.owner_hash("owner-a@example.test"),
    }


def test_runtime_pipeline_updates_metrics_and_quarantine_notification() -> None:
    from cloudbrowser.cloudfiles.runtime import create_cloudfiles_runtime

    class InfectedScanner:
        def scan(self, path: Path, *, request_id: str) -> str:
            return "infected"

    emitted: list[dict[str, object]] = []
    runtime = create_cloudfiles_runtime(
        downloads_base_url="http://downloads:8083",
        shared_secret="s" * 32,
        instance_id="cloudfiles-test",
        release_version="0.2.0-test",
        scanner=InfectedScanner(),
        notifier=lambda event: emitted.append(dict(event)),
        dev_store=True,
    )
    result = runtime.pipeline.ingest(
        binding=_binding(),
        source_name="bad.exe",
        source=BytesIO(b"malware-payload"),
    )
    assert result.status == "quarantined"
    assert runtime.metrics.snapshot() == {
        "ingest_count": 1,
        "bytes_ingested": len(b"malware-payload"),
        "quarantine_count": 1,
        "published_count": 0,
        "purged_count": 0,
        "erasure_count": 0,
    }
    assert emitted and emitted[0]["event_code"] == "quarantine.created"
    assert "owner-a@example.test" not in str(emitted[0])
    assert "bad.exe" not in str(emitted[0])


def test_runtime_purge_is_real_and_redacted(tmp_path: Path) -> None:
    from cloudbrowser.cloudfiles.runtime import create_cloudfiles_runtime

    store = DownloadStore(tmp_path)
    store.ingest("owner-a@example.test", "old.pdf", BytesIO(b"old"))
    old = tmp_path / owner_key("owner-a@example.test") / "entries" / "old.pdf"
    old.touch()
    old_mtime = datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp()
    import os

    os.utime(old, (old_mtime, old_mtime))
    runtime = create_cloudfiles_runtime(
        downloads_base_url="http://downloads:8083",
        shared_secret="s" * 32,
        instance_id="cloudfiles-test",
        release_version="0.2.0-test",
        store_root=tmp_path,
        clock=lambda: datetime(2026, 9, 4, tzinfo=timezone.utc),
    )
    result = runtime.purge(principal="owner-a@example.test")
    assert result["purged_count"] == 1
    assert "old.pdf" not in str(result)
    assert runtime.metrics.snapshot()["purged_count"] == 1
    assert not old.exists()


def test_downloads_http_runtime_uses_single_explicit_durable_store(tmp_path: Path, monkeypatch) -> None:
    import cloudbrowser.service_runtime as service_runtime

    captured: dict[str, object] = {}

    class FakeServer:
        def serve_forever(self):
            return None

        def server_close(self):
            return None

    def create_server(service, **kwargs):
        captured["service"] = service
        return FakeServer()

    monkeypatch.setattr("cloudbrowser.downloads.api.create_downloads_server", create_server)
    for key, value in {
        "CB_INSTANCE_ID": "downloads-test",
        "CB_RELEASE_VERSION": "0.2.0-test",
        "CB_PORT": "8093",
        "CB_PRINCIPAL_ID": "owner@example.test",
        "CB_BROWSER_ID": "browser-a",
        "CB_BINDING_GENERATION": "generation-a",
        "CB_DOWNLOADS_SHARED_SECRET": "s" * 32,
        "CB_DOWNLOADS_ROOT": str(tmp_path),
    }.items():
        monkeypatch.setenv(key, value)
    service_runtime.run_service("downloads")
    service = captured["service"]
    assert service.store_root == tmp_path.resolve()
    assert service.store_root == service.store.root


@pytest.mark.parametrize("compose_path", COMPOSE_FILES)
def test_compose_wires_clamav_sidecar_to_cloudfiles_and_shared_network(compose_path: Path) -> None:
    text = compose_path.read_text(encoding="utf-8")
    assert re.search(r"(?m)^  clamav:\n", text)
    assert "image: clamav/clamav:" in text
    assert "cloudfiles:" in text
    assert "CLAMAV_HOST: clamav" in text
    cloudfiles = text.split("  cloudfiles:", 1)[1].split("\n  identity-link:", 1)[0]
    assert "CB_CLAMAV_HOST: clamav" in cloudfiles
    assert "clamav:" in cloudfiles
    assert "service_healthy" in cloudfiles
    assert "healthcheck:" in text.split("  clamav:", 1)[1].split("\n  cloudfiles:", 1)[0]


def test_backup_restore_helpers_round_trip_the_downloads_volume(tmp_path: Path) -> None:
    from cloudbrowser.cloudfiles.backup import backup_store, restore_store

    source = tmp_path / "source"
    backup = tmp_path / "backup.tar"
    restored = tmp_path / "restored"
    DownloadStore(source).ingest("owner-a@example.test", "report.pdf", BytesIO(b"payload"))
    manifest = backup_store(source, backup, instance_id="cloudfiles-test")
    assert manifest["instance_id"] == "cloudfiles-test"
    assert manifest["file_count"] == 2  # report.pdf + per-owner .index.json
    restored_manifest = restore_store(backup, restored, instance_id="cloudfiles-test")
    assert restored_manifest["sha256"] == manifest["sha256"]
    assert DownloadStore(restored).read("owner-a@example.test", "report.pdf") == b"payload"


def test_backup_restore_preserves_sha256_index_metadata(tmp_path: Path) -> None:
    from cloudbrowser.cloudfiles.backup import backup_store, restore_store

    source = tmp_path / "source"
    backup = tmp_path / "backup.tar"
    restored = tmp_path / "restored"
    store = DownloadStore(source)
    store.ingest("owner-a@example.test", "report.pdf", BytesIO(b"payload"))
    before = store.list_entries("owner-a@example.test")[0]
    assert before.sha256 is not None

    backup_store(source, backup, instance_id="cloudfiles-test")
    restore_store(backup, restored, instance_id="cloudfiles-test")

    restored_store = DownloadStore(restored)
    entries = restored_store.list_entries("owner-a@example.test")
    assert len(entries) == 1
    assert entries[0].sha256 == before.sha256


def test_backup_restore_reject_wrong_instance_and_path_escape(tmp_path: Path) -> None:
    from cloudbrowser.cloudfiles.backup import backup_store, restore_store

    source = tmp_path / "source"
    backup = tmp_path / "backup.tar"
    DownloadStore(source).ingest("owner-a@example.test", "report.pdf", BytesIO(b"payload"))
    backup_store(source, backup, instance_id="cloudfiles-test")
    with pytest.raises(ValueError, match="instance"):
        restore_store(backup, tmp_path / "restored", instance_id="other-instance")
    with pytest.raises(ValueError, match="destination"):
        restore_store(backup, tmp_path / "../escape", instance_id="cloudfiles-test")


def test_eu_residency_qualification_is_explicit_and_fail_closed() -> None:
    from cloudbrowser.cloudfiles.residency import assert_eu_residency

    assert assert_eu_residency(host_region="eu-west-1", volume_region="eu-west-1")
    with pytest.raises(ValueError, match="EU"):
        assert_eu_residency(host_region="us-east-1", volume_region="eu-west-1")
    with pytest.raises(ValueError, match="EU"):
        assert_eu_residency(host_region="eu-west-1", volume_region="us-east-1")
