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


def test_p1_dependency_profiles_have_one_canonical_entry_point():
    for legacy_name in (
        "requirements-app.txt",
        "requirements-dev.txt",
        "requirements-yolo.txt",
    ):
        assert not (ROOT / legacy_name).exists()

    environment_profiles = {
        "environment-app.yml": "requirements/app.txt",
        "environment-dev.yml": "requirements/dev.txt",
        "environment-rk3588-yolo.yml": "requirements/rk3588-yolo.txt",
    }
    for environment_name, profile_path in environment_profiles.items():
        content = (ROOT / environment_name).read_text(encoding="utf-8")
        assert content.count(f"- -r {profile_path}") == 1


def test_p1_installers_do_not_repeat_environment_pip_profiles():
    for installer_name in ("install_app_env.sh", "install_yolo_env.sh"):
        content = (
            ROOT / "scripts" / "install" / installer_name
        ).read_text(encoding="utf-8")
        assert "conda env create" in content
        assert "conda env update" in content
        assert "python -m pip install -r" not in content


def test_p1_static_architecture_boundaries_hold():
    result = subprocess.run(
        [sys.executable, "scripts/validate_architecture_boundaries.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
