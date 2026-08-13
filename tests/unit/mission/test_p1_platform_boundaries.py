from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[3]


def test_p1_dependency_profiles_and_environment_definitions_are_present():
    for name in ("core", "telemetry", "web", "app", "dev", "rk3588-yolo"):
        assert (ROOT / "requirements" / f"{name}.txt").is_file()
    assert (ROOT / "environment-app.yml").is_file()
    assert (ROOT / "environment-dev.yml").is_file()
    assert (ROOT / "environment-rk3588-yolo.yml").is_file()


def test_p1_static_architecture_boundaries_hold():
    result = subprocess.run(
        [sys.executable, "scripts/validate_architecture_boundaries.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
