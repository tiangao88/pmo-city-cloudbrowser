from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OPERATIONS = ROOT / "deploy" / "coolify" / "operations"


def test_backup_rollback_and_health_operations_require_explicit_scope():
    common = (OPERATIONS / "common.py").read_text(encoding="utf-8")
    assert "--instance-id" in common
    assert "InstanceNamespace" in common
    assert "required=True" in common
    for name in ("backup_state.py", "rollback_state.py", "health_check.py"):
        path = OPERATIONS / name
        assert path.is_file(), f"missing operation: {name}"
        text = path.read_text(encoding="utf-8")
        assert "parser" in text or "ArgumentParser" in text


def test_operations_do_not_fall_back_to_another_installation():
    for path in OPERATIONS.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "CB_INSTANCE_ID or" not in text
        assert "default=" not in text or "instance-id" not in text
