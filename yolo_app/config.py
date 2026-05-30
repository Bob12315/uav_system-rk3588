from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(slots=True)
class AppConfig:
    model_path: str
    source: str
    conf_thres: float
    iou_thres: float
    classes: list[int]
    udp_ip: str
    udp_port: int
    selection_mode: str
    target_class: str
    max_lost_frames: int
    show: bool
    save_video: bool
    save_path: str
    line_width: int
    show_all_tracks: bool
    command_enabled: bool
    command_ip: str
    command_port: int
    window_name: str
    class_names: list[str]
    camera_width: int
    camera_height: int
    camera_fps: int
    camera_fourcc: str
    latest_frame: bool
    fullscreen: bool
    web_stream_enabled: bool
    web_stream_host: str
    web_stream_port: int
    web_stream_jpeg_quality: int
    web_stream_max_fps: float


def _str_to_bool(value: str | bool) -> bool:
    if isinstance(value, bool):
        return value
    lowered = value.lower()
    if lowered in {"1", "true", "yes", "y", "on"}:
        return True
    if lowered in {"0", "false", "no", "n", "off"}:
        return False
    raise argparse.ArgumentTypeError(f"invalid boolean value: {value}")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ground-side YOLO tracking app")
    parser.add_argument("--config", default=str(Path(__file__).with_name("config.yaml")))
    parser.add_argument("--model-path")
    parser.add_argument("--source")
    parser.add_argument("--conf-thres", type=float)
    parser.add_argument("--iou-thres", type=float)
    parser.add_argument("--classes", nargs="*", type=int)
    parser.add_argument("--udp-ip")
    parser.add_argument("--udp-port", type=int)
    parser.add_argument("--selection-mode", choices=["center", "biggest", "class"])
    parser.add_argument("--target-class")
    parser.add_argument("--max-lost-frames", type=int)
    parser.add_argument("--show", type=_str_to_bool)
    parser.add_argument("--save-video", type=_str_to_bool)
    parser.add_argument("--save-path")
    parser.add_argument("--line-width", type=int)
    parser.add_argument("--show-all-tracks", type=_str_to_bool)
    parser.add_argument("--command-enabled", type=_str_to_bool)
    parser.add_argument("--command-ip")
    parser.add_argument("--command-port", type=int)
    parser.add_argument("--window-name")
    parser.add_argument("--class-names", nargs="*")
    parser.add_argument("--camera-width", type=int)
    parser.add_argument("--camera-height", type=int)
    parser.add_argument("--camera-fps", type=int)
    parser.add_argument("--camera-fourcc")
    parser.add_argument("--latest-frame", type=_str_to_bool)
    parser.add_argument("--fullscreen", type=_str_to_bool)
    return parser


def _load_yaml_config(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError("config yaml must be a mapping")
    return data


def _expand_user_path(value: Any) -> str:
    text = str(value)
    if text.startswith("~"):
        return str(Path(text).expanduser())
    return text


def load_config() -> AppConfig:
    parser = build_arg_parser()
    args = parser.parse_args()
    yaml_config = _load_yaml_config(args.config)
    display_config = yaml_config.get("display", {})
    web_stream_config = yaml_config.get("web_stream", {})
    if not isinstance(display_config, dict) or not isinstance(web_stream_config, dict):
        raise ValueError("display and web_stream config must be mappings")

    merged = dict(yaml_config)
    for key, value in vars(args).items():
        if key == "config":
            continue
        if value is not None:
            merged[key.replace("-", "_")] = value

    return AppConfig(
        model_path=_expand_user_path(merged["model_path"]),
        source=_expand_user_path(merged["source"]),
        conf_thres=float(merged["conf_thres"]),
        iou_thres=float(merged["iou_thres"]),
        classes=list(merged.get("classes", [])),
        udp_ip=str(merged["udp_ip"]),
        udp_port=int(merged["udp_port"]),
        selection_mode=str(merged["selection_mode"]),
        target_class=str(merged.get("target_class", "")),
        max_lost_frames=int(merged["max_lost_frames"]),
        show=bool(display_config.get("local_window_enabled", merged["show"])),
        save_video=bool(merged["save_video"]),
        save_path=_expand_user_path(merged["save_path"]),
        line_width=int(merged.get("line_width", 2)),
        show_all_tracks=bool(merged.get("show_all_tracks", True)),
        command_enabled=bool(merged.get("command_enabled", True)),
        command_ip=str(merged.get("command_ip", "0.0.0.0")),
        command_port=int(merged.get("command_port", 5006)),
        window_name=str(merged.get("window_name", "YOLO Tracking")),
        class_names=list(merged.get("class_names", ["Target", "bucket", "class_2"])),
        camera_width=int(merged.get("camera_width", 640)),
        camera_height=int(merged.get("camera_height", 480)),
        camera_fps=int(merged.get("camera_fps", 30)),
        camera_fourcc=str(merged.get("camera_fourcc", "MJPG")),
        latest_frame=bool(merged.get("latest_frame", False)),
        fullscreen=bool(display_config.get("fullscreen", merged.get("fullscreen", False))),
        web_stream_enabled=bool(web_stream_config.get("enabled", False)),
        web_stream_host=str(web_stream_config.get("host", "0.0.0.0")),
        web_stream_port=int(web_stream_config.get("port", 8081)),
        web_stream_jpeg_quality=int(web_stream_config.get("jpeg_quality", 75)),
        web_stream_max_fps=float(web_stream_config.get("max_fps", 20.0)),
    )
