from __future__ import annotations

import argparse
import json
import sys

import cv2


def build_pipeline(port: int) -> str:
    # This is a control/perception input: displaying the newest frame is more
    # useful than preserving every delayed RTP packet.  Keep the jitter buffer
    # bounded and let the downstream appsink discard stale decoded frames.
    return (
        f"udpsrc port={port} "
        "! application/x-rtp,media=video,encoding-name=H264,payload=96 "
        "! rtpjitterbuffer latency=0 drop-on-latency=true "
        "! rtph264depay "
        "! queue leaky=downstream max-size-buffers=1 max-size-bytes=0 max-size-time=0 "
        "! avdec_h264 "
        "! videoconvert "
        "! video/x-raw,format=BGR "
        "! appsink drop=true sync=false max-buffers=1"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Low-latency UDP H264 bridge helper")
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()

    cap = cv2.VideoCapture(build_pipeline(args.port), cv2.CAP_GSTREAMER)
    if not cap.isOpened():
        print(json.dumps({"error": f"failed to open UDP GStreamer pipeline on port {args.port}"}), flush=True)
        return 1

    ok, frame = cap.read()
    if not ok or frame is None:
        print(json.dumps({"error": f"failed to read first frame from UDP port {args.port}"}), flush=True)
        cap.release()
        return 1

    height, width = frame.shape[:2]
    channels = frame.shape[2] if frame.ndim == 3 else 1
    print(json.dumps({"width": width, "height": height, "channels": channels}), flush=True)
    sys.stdout.buffer.write(frame.tobytes())
    sys.stdout.buffer.flush()

    while True:
        ok, frame = cap.read()
        if not ok or frame is None:
            break
        sys.stdout.buffer.write(frame.tobytes())
        sys.stdout.buffer.flush()

    cap.release()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
