from __future__ import annotations

from dataclasses import dataclass

try:
    from .config import AppConfig
    from .models import CommandMessage, CurrentTarget, DetectionObject, SceneDetections, Track
    from .utils import normalize_error
except ImportError:
    from config import AppConfig
    from models import CommandMessage, CurrentTarget, DetectionObject, SceneDetections, Track
    from utils import normalize_error


@dataclass(slots=True)
class TargetManagerState:
    locked_track_id: int | None = None
    lost_count: int = 0
    tracking_state: str = "searching"


class TargetManager:
    def __init__(self, cfg: AppConfig) -> None:
        self.cfg = cfg
        self.state = TargetManagerState()

    @property
    def locked_track_id(self) -> int | None:
        return self.state.locked_track_id

    def apply_command(self, command: CommandMessage, tracks: list[Track]) -> None:
        if command.action == "lock_target":
            if command.track_id is None:
                return
            for track in tracks:
                if track.track_id == command.track_id:
                    self._lock_track(track.track_id)
                    return
        elif command.action == "unlock_target":
            self._unlock("searching", reset_lost_count=True)
        elif command.action == "switch_next":
            self._switch_by_offset(tracks, offset=1)
        elif command.action == "switch_prev":
            self._switch_by_offset(tracks, offset=-1)

    def update(
        self,
        tracks: list[Track],
        image_width: int,
        image_height: int,
        frame_id: int,
        timestamp: float,
    ) -> CurrentTarget:
        if self.state.locked_track_id is None:
            candidate = self._auto_select(tracks, image_width, image_height)
            if candidate is not None:
                self._lock_track(candidate.track_id)

        locked_track = self._find_track(tracks, self.state.locked_track_id)
        if locked_track is not None:
            self.state.lost_count = 0
            self.state.tracking_state = "locked"
            return self._build_target(
                track=locked_track,
                tracking_state="locked",
                image_width=image_width,
                image_height=image_height,
                frame_id=frame_id,
                timestamp=timestamp,
            )

        if self.state.locked_track_id is not None:
            self.state.lost_count += 1
            self.state.tracking_state = "lost"
            if self.state.lost_count >= self.cfg.max_lost_frames:
                self._unlock("lost")

        return CurrentTarget(
            timestamp=timestamp,
            frame_id=frame_id,
            target_valid=False,
            tracking_state=self.state.tracking_state,
            track_id=-1,
            class_id=-1,
            class_name="",
            confidence=0.0,
            cx=0.0,
            cy=0.0,
            w=0.0,
            h=0.0,
            ex=0.0,
            ey=0.0,
            image_width=image_width,
            image_height=image_height,
            target_size=0.0,
            lost_count=self.state.lost_count,
        )

    def _lock_track(self, track_id: int) -> None:
        self.state.locked_track_id = track_id
        self.state.lost_count = 0
        self.state.tracking_state = "locked"

    def _unlock(self, tracking_state: str, reset_lost_count: bool = False) -> None:
        self.state.locked_track_id = None
        if reset_lost_count:
            self.state.lost_count = 0
        self.state.tracking_state = tracking_state

    def _find_track(self, tracks: list[Track], track_id: int | None) -> Track | None:
        if track_id is None:
            return None
        for track in tracks:
            if track.track_id == track_id:
                return track
        return None

    def _switch_by_offset(self, tracks: list[Track], offset: int) -> None:
        visible = sorted(tracks, key=lambda track: track.cx)
        if not visible:
            self._unlock("searching", reset_lost_count=True)
            return
        if self.state.locked_track_id is None:
            selected = visible[0 if offset >= 0 else -1]
            self._lock_track(selected.track_id)
            return

        current_index = 0
        for idx, track in enumerate(visible):
            if track.track_id == self.state.locked_track_id:
                current_index = idx
                break
        next_index = (current_index + offset) % len(visible)
        self._lock_track(visible[next_index].track_id)

    def _auto_select(self, tracks: list[Track], image_width: int, image_height: int) -> Track | None:
        if not tracks:
            return None
        mode = self.cfg.selection_mode
        if mode == "biggest":
            return max(self._filter_target_class(tracks), key=lambda track: track.area, default=None)
        if mode == "class":
            filtered = self._filter_target_class(tracks)
            if filtered:
                return min(filtered, key=lambda track: self._center_distance_sq(track, image_width, image_height))
            return None
        candidates = self._filter_target_class(tracks) or tracks
        return min(candidates, key=lambda track: self._center_distance_sq(track, image_width, image_height))

    def _filter_target_class(self, tracks: list[Track]) -> list[Track]:
        if not self.cfg.target_class:
            return tracks
        target_name = self.cfg.target_class.lower()
        return [track for track in tracks if track.class_name.lower() == target_name]

    def _center_distance_sq(self, track: Track, image_width: int, image_height: int) -> float:
        dx = track.cx - image_width / 2.0
        dy = track.cy - image_height / 2.0
        return dx * dx + dy * dy

    def _build_target(
        self,
        track: Track,
        tracking_state: str,
        image_width: int,
        image_height: int,
        frame_id: int,
        timestamp: float,
    ) -> CurrentTarget:
        return CurrentTarget(
            timestamp=timestamp,
            frame_id=frame_id,
            target_valid=True,
            tracking_state=tracking_state,
            track_id=track.track_id,
            class_id=track.class_id,
            class_name=track.class_name,
            confidence=track.confidence,
            cx=track.cx,
            cy=track.cy,
            w=track.w,
            h=track.h,
            ex=normalize_error(track.cx, image_width),
            ey=normalize_error(track.cy, image_height),
            image_width=image_width,
            image_height=image_height,
            target_size=self._target_size(track, image_width, image_height),
            lost_count=self.state.lost_count,
        )

    def _target_size(self, track: Track, image_width: int, image_height: int) -> float:
        width = max(1, int(image_width))
        height = max(1, int(image_height))
        return max(track.w / width, track.h / height)


def build_scene_detections(
    tracks: list[Track],
    image_width: int,
    image_height: int,
    frame_id: int,
    timestamp: float,
) -> SceneDetections:
    return SceneDetections(
        timestamp=float(timestamp),
        frame_id=int(frame_id),
        image_width=int(image_width),
        image_height=int(image_height),
        detections=[
            DetectionObject.from_track(track, image_width, image_height)
            for track in tracks
        ],
    )
