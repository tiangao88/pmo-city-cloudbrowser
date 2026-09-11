"""Cold-copy correctness only; no production state or live databases."""
import importlib.util
from pathlib import Path
import sqlite3

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("cold_restore", ROOT / "experiments/novnc/cold_restore.py")
restore = importlib.util.module_from_spec(spec)
spec.loader.exec_module(restore)


def test_fresh_restore_preserves_cold_sqlite_modes_and_source(tmp_path):
    source = tmp_path / "source"
    source.mkdir(mode=0o700)
    database = source / "fixture.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("create table fixture(value text)")
        connection.execute("insert into fixture values ('synthetic-before')")
    connection.close()
    database.chmod(0o600)
    backup, destination = tmp_path / "backup", tmp_path / "restored"
    before = restore.cold_copy(source, backup)
    (source / "candidate-only").write_text("synthetic")
    with sqlite3.connect(database) as connection:
        connection.execute("update fixture set value='synthetic-after'")
    connection.close()
    assert restore.cold_copy(backup, destination) == before
    with sqlite3.connect(destination / database.name) as connection:
        assert connection.execute("pragma integrity_check").fetchone() == ("ok",)
        assert connection.execute("select value from fixture").fetchone() == ("synthetic-before",)
    connection.close()
    assert (source / "candidate-only").exists()
    assert not (destination / "candidate-only").exists()
    assert restore.manifest(backup) == before


def test_refuses_existing_or_nested_destination(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    with pytest.raises(FileExistsError):
        restore.cold_copy(source, source)
    with pytest.raises(ValueError):
        restore.cold_copy(source, source / "nested")


def test_copies_links_without_reading_their_targets(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "link").symlink_to(tmp_path / "absent-target")
    destination = tmp_path / "restored"
    restore.cold_copy(source, destination)
    assert (destination / "link").is_symlink()
    assert (destination / "link").readlink() == tmp_path / "absent-target"


def test_copy_corruption_is_detected(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    (source / "fixture").write_text("synthetic-original")
    copytree = restore.shutil.copytree
    def corrupt(source, destination, **kwargs):
        copytree(source, destination, **kwargs)
        (destination / "fixture").write_text("synthetic-corruption")
    monkeypatch.setattr(restore.shutil, "copytree", corrupt)
    with pytest.raises(RuntimeError, match="verification failed"):
        restore.cold_copy(source, tmp_path / "restored")
