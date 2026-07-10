from pathlib import Path


def test_healthcheck_discovers_environments_and_configured_model():
    script = (
        Path(__file__).resolve().parents[2]
        / "scripts"
        / "healthcheck"
        / "check_rk3588.sh"
    ).read_text(encoding="utf-8")

    assert '${APP_PYTHON:-}' in script
    assert '${YOLO_PYTHON:-}' in script
    assert script.index('miniconda3/envs/${environment_name}') < script.index(
        'anaconda3/envs/${environment_name}'
    )
    assert "command -v python3 || command -v python" in script
    assert 'model_path="$(printf' in script
    assert "data/models/cuadc-fp16.rknn" not in script
