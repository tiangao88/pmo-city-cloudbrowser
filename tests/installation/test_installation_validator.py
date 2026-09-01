from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]


def test_installation_validator_accepts_the_current_bundle():
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "validate-installation.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "installation validation: PASS" in result.stdout


def test_image_input_validator_accepts_all_service_images():
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "validate-image-inputs.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "image-input validation: PASS" in result.stdout
