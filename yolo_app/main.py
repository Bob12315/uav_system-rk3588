from __future__ import annotations

import os
import sys
import time

# Some conda-packaged OpenCV builds use the Qt backend but do not bundle fonts.
# Point Qt to a common system font directory before importing cv2 to suppress warnings.
os.environ.setdefault("QT_QPA_FONTDIR", "/usr/share/fonts/truetype/dejavu")

import cv2

from annotator import Annotator
from command_receiver import CommandReceiver
from config import load_config
from mjpeg_stream import MjpegStream
from target_manager import TargetManager, build_scene_detections
from tracker_runner import TrackerRunner
from udp_publisher import UdpPublisher
from utils import ensure_parent_dir
from video_source import VideoSource


def build_video_writer(save_path: str, fps: float, width: int, height: int) -> cv2.VideoWriter:
    ensure_parent_dir(save_path)
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    return cv2.VideoWriter(save_path, fourcc, fps if fps > 0 else 30.0, (width, height))


def main() -> int:
    cfg = load_config()
    video_source = VideoSource(
        cfg.source,
        camera_width=cfg.camera_width,
        camera_height=cfg.camera_height,
        camera_fps=cfg.camera_fps,
        camera_fourcc=cfg.camera_fourcc,
        latest_frame=cfg.latest_frame,
    )
    tracker = TrackerRunner(cfg)
    target_manager = TargetManager(cfg)
    udp_publisher = UdpPublisher(cfg.udp_ip, cfg.udp_port)
    command_receiver = CommandReceiver(cfg.command_ip, cfg.command_port, enabled=cfg.command_enabled)
    annotator = Annotator(cfg)
    writer = None
    web_stream = (
        MjpegStream(
            cfg.web_stream_host,
            cfg.web_stream_port,
            cfg.web_stream_jpeg_quality,
            cfg.web_stream_max_fps,
        )
        if cfg.web_stream_enabled
        else None
    )
    frame_count = 0
    start_time = time.perf_counter()

    if cfg.show:
        cv2.namedWindow(cfg.window_name, cv2.WINDOW_NORMAL)
        if cfg.fullscreen:
            cv2.setWindowProperty(cfg.window_name, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
    if web_stream is not None:
        web_stream.start()

    try:
        while True:
            packet = video_source.read()
            if packet is None:
                break

            frame = packet.frame
            image_height, image_width = frame.shape[:2]

            tracks = tracker.run(frame)
            frame_count += 1
            fps = frame_count / max(time.perf_counter() - start_time, 1e-9)
            latency_ms = max(0.0, (time.time() - packet.timestamp) * 1000.0)
            commands = command_receiver.poll()
            for command in commands:
                target_manager.apply_command(command, tracks)

            current_target = target_manager.update(
                tracks=tracks,
                image_width=image_width,
                image_height=image_height,
                frame_id=packet.frame_id,
                timestamp=packet.timestamp,
            )
            scene = build_scene_detections(
                tracks=tracks,
                image_width=image_width,
                image_height=image_height,
                frame_id=packet.frame_id,
                timestamp=packet.timestamp,
            )
            udp_publisher.publish(current_target, scene)

            if cfg.show or cfg.save_video or web_stream is not None:
                annotated = annotator.annotate(
                    frame=frame,
                    tracks=tracks,
                    current_target=current_target,
                    locked_track_id=target_manager.locked_track_id,
                    fps=fps,
                    latency_ms=latency_ms,
                )
                if cfg.show:
                    cv2.imshow(cfg.window_name, annotated)
                    key = cv2.waitKey(1) & 0xFF
                    if key in {27, ord("q")}:
                        break
                if web_stream is not None:
                    web_stream.publish(annotated)
                if cfg.save_video:
                    if writer is None:
                        fps = video_source.cap.get(cv2.CAP_PROP_FPS)
                        writer = build_video_writer(cfg.save_path, fps, image_width, image_height)
                    writer.write(annotated)
            if frame_count == 1 or frame_count % 60 == 0:
                print(
                    f"frame={frame_count} fps={fps:.1f} pipeline_ms={latency_ms:.1f} tracks={len(tracks)}",
                    flush=True,
                )
    except KeyboardInterrupt:
        pass
    finally:
        video_source.release()
        tracker.release()
        udp_publisher.close()
        command_receiver.close()
        if web_stream is not None:
            web_stream.close()
        if writer is not None:
            writer.release()
        cv2.destroyAllWindows()

    elapsed = max(time.perf_counter() - start_time, 1e-9)
    print(f"finished frames={frame_count} average_fps={frame_count / elapsed:.1f}", flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
