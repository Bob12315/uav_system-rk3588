from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from yolo_app.config import load_config


def _config() -> dict[str, object]:
    return {
        "model_path": "../data/models/model.rknn",
        "source": "/dev/video0",
        "conf_thres": 0.25,
        "iou_thres": 0.45,
        "classes": [],
        "udp_ip": "127.0.0.1",
        "udp_port": 5005,
        "selection_mode": "class",
        "target_class": "target",
        "max_lost_frames": 5,
        "show": False,
        "save_video": False,
        "save_path": "../runtime/videos/output.mp4",
        "line_width": 3,
        "show_all_tracks": True,
        "command_enabled": True,
        "command_ip": "0.0.0.0",
        "command_port": 5006,
        "window_name": "YOLO Tracking",
        "class_names": ["target"],
        "camera_width": 640,
        "camera_height": 480,
        "camera_fps": 30,
        "camera_fourcc": "MJPG",
        "latest_frame": True,
        "display": {"local_window_enabled": False, "fullscreen": False},
        "web_stream": {"enabled": True, "host": "0.0.0.0", "port": 8081},
    }


def _write_config(tmp_path: Path, data: dict[str, object]) -> Path:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    path = config_dir / "yolo.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def test_load_config_resolves_paths_relative_to_yaml(tmp_path: Path, monkeypatch) -> None:
    path = _write_config(tmp_path, _config())
    monkeypatch.setattr("sys.argv", ["yolo", "--config", str(path)])

    cfg = load_config()

    assert cfg.model_path == str(tmp_path / "data" / "models" / "model.rknn")
    assert cfg.save_path == str(tmp_path / "runtime" / "videos" / "output.mp4")
    assert cfg.latest_frame is True
    assert cfg.web_stream_enabled is True
    assert cfg.web_stream_width == 0
    assert cfg.web_stream_height == 0


def test_load_config_reads_web_stream_dimensions(tmp_path: Path, monkeypatch) -> None:
    data = _config()
    web_stream = data["web_stream"]
    assert isinstance(web_stream, dict)
    web_stream["width"] = 480
    web_stream["height"] = 360
    path = _write_config(tmp_path, data)
    monkeypatch.setattr("sys.argv", ["yolo", "--config", str(path)])

    cfg = load_config()

    assert cfg.web_stream_width == 480
    assert cfg.web_stream_height == 360


def test_load_config_rejects_quoted_false_bool(tmp_path: Path, monkeypatch) -> None:
    data = _config()
    data["save_video"] = "false"
    path = _write_config(tmp_path, data)
    monkeypatch.setattr("sys.argv", ["yolo", "--config", str(path)])

    with pytest.raises(ValueError, match="save_video must be a YAML bool"):
        load_config()


def test_cli_bool_override_is_parsed(tmp_path: Path, monkeypatch) -> None:
    data = _config()
    data["save_video"] = True
    path = _write_config(tmp_path, data)
    monkeypatch.setattr("sys.argv", ["yolo", "--config", str(path), "--save-video", "false"])

    cfg = load_config()

    assert cfg.save_video is False
