"""Runtime field binding — pure GPS sampling and binding candidate.

Deterministic sampling layer: Schema v3 profile + DroneState snapshots →
GPS quality filtering → duplicate detection → 5 s window → ≥20 samples →
median origin → horizontal spread → RuntimeFieldBindingCandidate.

No hardware access, no global state, no RuntimeContext writes.
All time values are supplied by the caller.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Tuple

from .field_profile import (
    FieldProfile,
    GpsQualityThresholds,
    RuntimeOriginSampling,
    validate_field_profile,
)
from .field_reference import (
    HeadingSource,
    OriginSource,
    gps_enu_deltas,
)
from .runtime_field_geometry import (
    RuntimeFieldGeometry,
    RuntimeFieldGeometryError,
    RuntimeFieldPoint,
    build_runtime_field_geometry,
)


# ---------------------------------------------------------------------------
# exceptions
# ---------------------------------------------------------------------------


class RuntimeFieldBindingError(ValueError):
    """Invalid sampling state, GPS observation, or binding candidate."""


# ---------------------------------------------------------------------------
# data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RuntimeGpsSample:
    """A single accepted GPS sample."""

    source_time_s: float
    observed_at_s: float
    lat: float
    lon: float
    fix_type: int
    satellites: int
    eph: float
    epv: float


@dataclass(frozen=True, slots=True)
class RuntimeFieldSamplingStatus:
    """Snapshot of the sampler's current state."""

    state: str
    profile_id: str

    started_at_s: Optional[float]
    elapsed_s: float
    sample_window_s: float
    min_samples: int

    accepted_samples: int
    rejected_samples: int
    duplicate_samples: int

    window_complete: bool
    can_finalize: bool

    last_source_time_s: Optional[float]
    last_rejection_reason: Optional[str]


@dataclass(frozen=True, slots=True)
class RuntimeFieldBindingCandidate:
    """An immutable, not-yet-applied field binding candidate.

    Has not been written into FieldReference — not confirmed, not frozen.
    """

    profile_id: str

    origin_source: str
    heading_source: str
    field_reference_mode: str

    origin_lat: float
    origin_lon: float

    forward_marker_lat: float
    forward_marker_lon: float

    field_heading_yaw_rad: float
    field_heading_deg: float
    baseline_m: float

    sample_count: int
    rejected_sample_count: int
    duplicate_sample_count: int

    started_at_s: float
    completed_at_s: float
    sample_duration_s: float
    horizontal_spread_m: float

    gps_fix_type: int
    gps_satellites: int
    gps_eph: float
    gps_epv: float

    geometry: RuntimeFieldGeometry
    warnings: Tuple[str, ...]


# ---------------------------------------------------------------------------
# sampler
# ---------------------------------------------------------------------------


class RuntimeFieldBindingSampler:
    """Deterministic GPS sampling state machine.

    Builds a binding candidate from a Schema v3 profile and a sequence
    of drone-state snapshots.  All time values are caller-supplied.
    """

    def __init__(self, profile: FieldProfile) -> None:
        if not isinstance(profile, FieldProfile):
            raise RuntimeFieldBindingError("profile must be a FieldProfile instance")
        if profile.schema_version != 3:
            raise RuntimeFieldBindingError(
                f"only schema v3 supported, got v{profile.schema_version}"
            )
        diag = validate_field_profile(profile)
        if not diag.ok:
            raise RuntimeFieldBindingError(
                f"profile validation failed: {'; '.join(diag.errors)}"
            )

        self._profile: FieldProfile = profile
        self._gq: GpsQualityThresholds = profile.gps_quality
        self._ros: RuntimeOriginSampling = profile.runtime_origin_sampling

        self._state: str = "idle"
        self._started_at_s: Optional[float] = None
        self._completed_at_s: Optional[float] = None

        self._accepted: list[RuntimeGpsSample] = []
        self._rejected: int = 0
        self._duplicate: int = 0
        self._seen_source_times: set[float] = set()
        self._max_seen_source_time_s: Optional[float] = None
        self._last_rejection_reason: Optional[str] = None

        self._candidate: Optional[RuntimeFieldBindingCandidate] = None

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    def start(self, *, started_at_s: float) -> RuntimeFieldSamplingStatus:
        """Begin a new sampling session."""
        if not _is_finite_number(started_at_s):
            raise RuntimeFieldBindingError(
                f"started_at_s must be a finite number, got {started_at_s!r}"
            )
        if self._state == "sampling":
            raise RuntimeFieldBindingError(
                "cannot start a new session while sampling is in progress; call reset() first"
            )

        self._state = "sampling"
        self._started_at_s = float(started_at_s)
        self._completed_at_s = None
        self._accepted = []
        self._rejected = 0
        self._duplicate = 0
        self._seen_source_times = set()
        self._max_seen_source_time_s = None
        self._last_rejection_reason = None
        self._candidate = None

        return self.status(now_s=started_at_s)

    def reset(self) -> RuntimeFieldSamplingStatus:
        """Reset to idle regardless of current state."""
        self._state = "idle"
        self._started_at_s = None
        self._completed_at_s = None
        self._accepted = []
        self._rejected = 0
        self._duplicate = 0
        self._seen_source_times = set()
        self._max_seen_source_time_s = None
        self._last_rejection_reason = None
        self._candidate = None
        return self.status()

    def status(
        self, *, now_s: Optional[float] = None
    ) -> RuntimeFieldSamplingStatus:
        """Return the current sampling status."""
        profile_id = self._profile.profile_id
        window_s = self._ros.sample_window_s
        min_samples = self._ros.min_samples

        if self._state == "idle":
            return RuntimeFieldSamplingStatus(
                state="idle", profile_id=profile_id,
                started_at_s=None, elapsed_s=0.0,
                sample_window_s=window_s, min_samples=min_samples,
                accepted_samples=0, rejected_samples=0, duplicate_samples=0,
                window_complete=False, can_finalize=False,
                last_source_time_s=None, last_rejection_reason=None,
            )

        if self._state == "sampling":
            if now_s is None:
                raise RuntimeFieldBindingError("now_s is required when sampling")
            if not _is_finite_number(now_s):
                raise RuntimeFieldBindingError(f"now_s must be finite, got {now_s!r}")
            started = self._started_at_s
            assert started is not None
            if now_s < started:
                raise RuntimeFieldBindingError(
                    f"now_s ({now_s}) < started_at_s ({started})"
                )
            elapsed = now_s - started
            window_complete = elapsed >= window_s
            can_finalize = (
                window_complete and self._accepted_n >= min_samples
            )
            return RuntimeFieldSamplingStatus(
                state="sampling", profile_id=profile_id,
                started_at_s=started, elapsed_s=elapsed,
                sample_window_s=window_s, min_samples=min_samples,
                accepted_samples=self._accepted_n,
                rejected_samples=self._rejected,
                duplicate_samples=self._duplicate,
                window_complete=window_complete,
                can_finalize=can_finalize,
                last_source_time_s=self._max_seen_source_time_s,
                last_rejection_reason=self._last_rejection_reason,
            )

        # ready or failed
        started = self._started_at_s
        completed = self._completed_at_s
        if started is None or completed is None:
            elapsed = 0.0
        elif now_s is None:
            elapsed = completed - started
        else:
            if not _is_finite_number(now_s):
                raise RuntimeFieldBindingError(
                    f"now_s must be a finite number, got {now_s!r}"
                )
            if now_s < started:
                raise RuntimeFieldBindingError(
                    f"now_s ({now_s}) < started_at_s ({started})"
                )
            effective = max(completed, float(now_s))
            elapsed = max(0.0, effective - started)
        window_complete = elapsed >= window_s

        return RuntimeFieldSamplingStatus(
            state=self._state, profile_id=profile_id,
            started_at_s=started, elapsed_s=elapsed,
            sample_window_s=window_s, min_samples=min_samples,
            accepted_samples=self._accepted_n,
            rejected_samples=self._rejected,
            duplicate_samples=self._duplicate,
            window_complete=window_complete, can_finalize=False,
            last_source_time_s=self._max_seen_source_time_s,
            last_rejection_reason=self._last_rejection_reason,
        )

    # ------------------------------------------------------------------
    # observation
    # ------------------------------------------------------------------

    def observe_snapshot(
        self,
        snapshot: Mapping[str, Any],
        *,
        observed_at_s: float,
    ) -> RuntimeFieldSamplingStatus:
        """Ingest one drone-state snapshot during sampling."""

        if self._state != "sampling":
            raise RuntimeFieldBindingError(
                f"cannot observe in state {self._state!r}"
            )

        if not _is_finite_number(observed_at_s):
            raise RuntimeFieldBindingError(
                f"observed_at_s must be a finite number, got {observed_at_s!r}"
            )
        started = self._started_at_s
        assert started is not None
        if observed_at_s < started:
            raise RuntimeFieldBindingError(
                f"observed_at_s ({observed_at_s}) < started_at_s ({started})"
            )

        # Window check — reject snapshots that arrive after the window closes
        window_s = self._ros.sample_window_s
        if observed_at_s > started + window_s:
            return self.status(now_s=observed_at_s)

        # Defend against non-Mapping snapshot
        if not isinstance(snapshot, Mapping):
            self._rejected += 1
            self._last_rejection_reason = (
                "snapshot must be a mapping"
            )
            return self.status(now_s=observed_at_s)

        # Extract source time
        src_time = snapshot.get("last_global_position_time")
        if src_time is None:
            self._rejected += 1
            self._last_rejection_reason = "missing last_global_position_time"
            return self.status(now_s=observed_at_s)
        if not _is_finite_number(src_time) or float(src_time) <= 0.0:
            self._rejected += 1
            self._last_rejection_reason = (
                f"last_global_position_time must be a finite positive number, "
                f"got {src_time!r}"
            )
            return self.status(now_s=observed_at_s)

        src_time_f = float(src_time)

        # Duplicate check
        if src_time_f in self._seen_source_times:
            self._duplicate += 1
            return self.status(now_s=observed_at_s)

        # Non-monotonic check
        if self._max_seen_source_time_s is not None and src_time_f < self._max_seen_source_time_s:
            self._rejected += 1
            self._last_rejection_reason = (
                "last_global_position_time is not monotonic"
            )
            self._seen_source_times.add(src_time_f)
            return self.status(now_s=observed_at_s)

        # Mark source time as seen and advance max_seen BEFORE payload/quality
        # checks so repeated reads of the same bad GPS message are counted as
        # duplicates instead of repeatedly increasing rejected_samples, and so
        # that a later message with an older timestamp is correctly rejected as
        # non-monotonic.
        self._seen_source_times.add(src_time_f)
        self._max_seen_source_time_s = src_time_f

        # global_position_valid
        if snapshot.get("global_position_valid") is not True:
            self._rejected += 1
            self._last_rejection_reason = "global_position_valid is not True"
            return self.status(now_s=observed_at_s)

        # Lat/lon validation
        lat = snapshot.get("lat")
        lon = snapshot.get("lon")
        if not _is_finite_number(lat):
            self._rejected += 1
            self._last_rejection_reason = f"lat must be a finite number, got {lat!r}"
            return self.status(now_s=observed_at_s)
        if not _is_finite_number(lon):
            self._rejected += 1
            self._last_rejection_reason = f"lon must be a finite number, got {lon!r}"
            return self.status(now_s=observed_at_s)
        lat_f = float(lat)
        lon_f = float(lon)
        if lat_f < -90.0 or lat_f > 90.0:
            self._rejected += 1
            self._last_rejection_reason = f"lat {lat_f} out of range [-90, 90]"
            return self.status(now_s=observed_at_s)
        if lon_f < -180.0 or lon_f > 180.0:
            self._rejected += 1
            self._last_rejection_reason = f"lon {lon_f} out of range [-180, 180]"
            return self.status(now_s=observed_at_s)
        if abs(math.cos(math.radians(lat_f))) < 1e-9:
            self._rejected += 1
            self._last_rejection_reason = "latitude too close to pole"
            return self.status(now_s=observed_at_s)

        # GPS quality checks
        gps_ok = True
        rejections: list[str] = []

        # fix_type — strict int
        fix = snapshot.get("gps_fix_type")
        if not _is_strict_int(fix):
            gps_ok = False
            rejections.append(f"gps_fix_type must be a strict integer, got {fix!r}")
        else:
            fix_i = int(fix)
            if fix_i < self._gq.min_fix_type:
                gps_ok = False
                rejections.append(
                    f"gps_fix_type {fix_i} < min_fix_type {self._gq.min_fix_type}"
                )

        # satellites — strict int
        sats = snapshot.get("satellites_visible")
        if not _is_strict_int(sats):
            gps_ok = False
            rejections.append(
                f"satellites_visible must be a strict integer, got {sats!r}"
            )
        else:
            sats_i = int(sats)
            if sats_i < self._gq.min_satellites:
                gps_ok = False
                rejections.append(
                    f"satellites_visible {sats_i} < min_satellites {self._gq.min_satellites}"
                )

        # eph — finite number, >= 0, <= max_eph
        eph = snapshot.get("gps_eph")
        if not _is_finite_number(eph):
            gps_ok = False
            rejections.append(f"gps_eph must be a finite number, got {eph!r}")
        else:
            eph_f = float(eph)
            if eph_f < 0.0:
                gps_ok = False
                rejections.append(f"gps_eph {eph_f} < 0")
            elif eph_f > self._gq.max_eph:
                gps_ok = False
                rejections.append(
                    f"gps_eph {eph_f} > max_eph {self._gq.max_eph}"
                )

        # epv — finite number, >= 0, <= max_epv
        epv = snapshot.get("gps_epv")
        if not _is_finite_number(epv):
            gps_ok = False
            rejections.append(f"gps_epv must be a finite number, got {epv!r}")
        else:
            epv_f = float(epv)
            if epv_f < 0.0:
                gps_ok = False
                rejections.append(f"gps_epv {epv_f} < 0")
            elif epv_f > self._gq.max_epv:
                gps_ok = False
                rejections.append(
                    f"gps_epv {epv_f} > max_epv {self._gq.max_epv}"
                )

        if not gps_ok:
            self._rejected += 1
            self._last_rejection_reason = "; ".join(rejections)
            return self.status(now_s=observed_at_s)

        # Accept
        sample = RuntimeGpsSample(
            source_time_s=src_time_f,
            observed_at_s=observed_at_s,
            lat=lat_f,
            lon=lon_f,
            fix_type=int(fix),
            satellites=int(sats),
            eph=float(eph),
            epv=float(epv),
        )
        self._accepted.append(sample)
        # Do NOT clear last_rejection_reason
        return self.status(now_s=observed_at_s)

    # ------------------------------------------------------------------
    # finalize
    # ------------------------------------------------------------------

    def finalize(
        self, *, completed_at_s: float
    ) -> RuntimeFieldBindingCandidate:
        """Produce a binding candidate from the completed sampling session."""

        if self._state == "ready":
            assert self._candidate is not None
            return self._candidate

        if self._state != "sampling":
            raise RuntimeFieldBindingError(
                f"cannot finalize in state {self._state!r}"
            )

        if not _is_finite_number(completed_at_s):
            raise RuntimeFieldBindingError(
                f"completed_at_s must be a finite number, got {completed_at_s!r}"
            )
        started = self._started_at_s
        assert started is not None
        if completed_at_s < started:
            raise RuntimeFieldBindingError(
                f"completed_at_s ({completed_at_s}) < started_at_s ({started})"
            )

        elapsed = completed_at_s - started
        if elapsed < self._ros.sample_window_s:
            raise RuntimeFieldBindingError(
                f"sampling window not yet complete: elapsed {elapsed:.2f}s "
                f"< {self._ros.sample_window_s}s"
            )

        n = self._accepted_n
        if n < self._ros.min_samples:
            self._state = "failed"
            self._completed_at_s = completed_at_s
            raise RuntimeFieldBindingError(
                f"accepted samples {n} < required {self._ros.min_samples}"
            )

        # Median origin
        origin_lat = statistics.median(s.lat for s in self._accepted)
        origin_lon = statistics.median(s.lon for s in self._accepted)

        # Horizontal spread
        radii: list[float] = []
        for s in self._accepted:
            dn, de = gps_enu_deltas(origin_lat, origin_lon, s.lat, s.lon)
            radii.append(math.hypot(dn, de))
        spread = max(radii) if radii else 0.0

        if spread > self._ros.max_horizontal_spread_m:
            self._state = "failed"
            self._completed_at_s = completed_at_s
            raise RuntimeFieldBindingError(
                f"horizontal spread {spread:.3f}m exceeds "
                f"max_horizontal_spread_m {self._ros.max_horizontal_spread_m}m"
            )

        # Build runtime geometry
        try:
            geometry = build_runtime_field_geometry(
                self._profile,
                origin_lat=origin_lat,
                origin_lon=origin_lon,
            )
        except RuntimeFieldGeometryError as exc:
            self._state = "failed"
            self._completed_at_s = completed_at_s
            raise RuntimeFieldBindingError(str(exc)) from exc

        # Conservative GPS quality
        gps_fix_type = min(s.fix_type for s in self._accepted)
        gps_satellites = min(s.satellites for s in self._accepted)
        gps_eph = max(s.eph for s in self._accepted)
        gps_epv = max(s.epv for s in self._accepted)

        candidate = RuntimeFieldBindingCandidate(
            profile_id=self._profile.profile_id,
            origin_source=OriginSource.RUNTIME_CURRENT_GPS.value,
            heading_source=HeadingSource.RUNTIME_FORWARD_MARKER.value,
            field_reference_mode="runtime_origin_forward_marker",
            origin_lat=origin_lat,
            origin_lon=origin_lon,
            forward_marker_lat=self._profile.forward_marker.lat,  # type: ignore[union-attr]
            forward_marker_lon=self._profile.forward_marker.lon,  # type: ignore[union-attr]
            field_heading_yaw_rad=geometry.field_heading_yaw_rad,
            field_heading_deg=geometry.field_heading_deg,
            baseline_m=geometry.baseline_m,
            sample_count=n,
            rejected_sample_count=self._rejected,
            duplicate_sample_count=self._duplicate,
            started_at_s=started,
            completed_at_s=completed_at_s,
            sample_duration_s=elapsed,
            horizontal_spread_m=spread,
            gps_fix_type=gps_fix_type,
            gps_satellites=gps_satellites,
            gps_eph=gps_eph,
            gps_epv=gps_epv,
            geometry=geometry,
            warnings=geometry.warnings,
        )

        self._state = "ready"
        self._completed_at_s = completed_at_s
        self._candidate = candidate
        return candidate

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    @property
    def _accepted_n(self) -> int:
        return len(self._accepted)


# ---------------------------------------------------------------------------
# internal helpers
# ---------------------------------------------------------------------------


def validate_runtime_field_binding_candidate(
    candidate: object,
) -> tuple[str, ...]:
    """Validate a RuntimeFieldBindingCandidate.

    Shared by service and builder layers.
    Returns a tuple of error strings (empty = valid).
    Never raises ordinary exceptions.
    """
    import math as _m
    errs: list[str] = []

    if not isinstance(candidate, RuntimeFieldBindingCandidate):
        return (f"candidate must be RuntimeFieldBindingCandidate, got {type(candidate).__name__}",)

    from .field_reference import FieldReference as _FR

    c = candidate

    # ── strings & fixed values ──────────────────────────────────────
    for name in ("profile_id", "origin_source", "heading_source", "field_reference_mode"):
        v = getattr(c, name, "")
        if not isinstance(v, str) or not v.strip():
            errs.append(f"{name} must be a non-empty string, got {v!r}")

    if not errs:
        if c.origin_source != "runtime_current_gps":
            errs.append(f"origin_source must be 'runtime_current_gps', got {c.origin_source!r}")
        if c.heading_source != "runtime_forward_marker":
            errs.append(f"heading_source must be 'runtime_forward_marker', got {c.heading_source!r}")
        if c.field_reference_mode != "runtime_origin_forward_marker":
            errs.append(f"field_reference_mode must be 'runtime_origin_forward_marker', got {c.field_reference_mode!r}")

    # ── lat/lon ─────────────────────────────────────────────────────
    parsed_lat: float | None = None
    parsed_lon: float | None = None
    for name in ("origin_lat", "origin_lon", "forward_marker_lat", "forward_marker_lon"):
        v = getattr(c, name)
        if not _is_finite_number(v):
            errs.append(f"{name} must be a finite number, got {v!r}")
        else:
            fv = float(v)
            if name.endswith("_lat") and not -90.0 <= fv <= 90.0:
                errs.append(f"{name} {fv} out of range [-90, 90]")
            if name.endswith("_lon") and not -180.0 <= fv <= 180.0:
                errs.append(f"{name} {fv} out of range [-180, 180]")
            if name == "origin_lat":
                parsed_lat = fv
            if name == "origin_lon":
                parsed_lon = fv
    if parsed_lat is not None and abs(_m.cos(_m.radians(parsed_lat))) < 1e-9:
        errs.append("origin latitude too close to pole")

    # ── heading ─────────────────────────────────────────────────────
    hdg_rad = getattr(c, "field_heading_yaw_rad", None)
    hdg_deg = getattr(c, "field_heading_deg", None)
    hdg_ok = True
    if not _is_finite_number(hdg_rad):
        errs.append(f"field_heading_yaw_rad must be finite, got {hdg_rad!r}")
        hdg_ok = False
    if not _is_finite_number(hdg_deg):
        errs.append(f"field_heading_deg must be finite, got {hdg_deg!r}")
        hdg_ok = False

    if hdg_ok:
        norm = _FR._normalize_yaw(float(hdg_rad))
        if not _m.isclose(float(hdg_rad), norm, rel_tol=0.0, abs_tol=1e-12):
            errs.append("field_heading_yaw_rad must be normalized to (-pi, pi]")
        if not _m.isclose(float(hdg_deg), _m.degrees(float(hdg_rad)), rel_tol=1e-9, abs_tol=1e-9):
            errs.append(f"field_heading_deg {hdg_deg} inconsistent with yaw_rad {hdg_rad}")

    # ── baseline ────────────────────────────────────────────────────
    bl = getattr(c, "baseline_m", None)
    bl_ok = False
    if not _is_finite_number(bl) or float(bl) <= 0.0:
        errs.append(f"baseline_m must be finite > 0, got {bl!r}")
    else:
        bl_ok = True

    # ── counts ──────────────────────────────────────────────────────
    for name in ("sample_count", "rejected_sample_count", "duplicate_sample_count"):
        v = getattr(c, name)
        if not _is_strict_int(v):
            errs.append(f"{name} must be a strict integer, got {type(v).__name__} {v!r}")
        elif v < 0:
            errs.append(f"{name} must be >= 0, got {v}")
    if _is_strict_int(getattr(c, "sample_count", None)) and c.sample_count < 1:
        errs.append(f"sample_count must be >= 1, got {c.sample_count}")

    # ── timing & spread ─────────────────────────────────────────────
    started = getattr(c, "started_at_s", None)
    completed = getattr(c, "completed_at_s", None)
    duration = getattr(c, "sample_duration_s", None)
    spread = getattr(c, "horizontal_spread_m", None)
    timing_ok = True
    for name, v in (("started_at_s", started), ("completed_at_s", completed),
                     ("sample_duration_s", duration), ("horizontal_spread_m", spread)):
        if not _is_finite_number(v):
            errs.append(f"{name} must be finite, got {v!r}")
            timing_ok = False
    if timing_ok:
        if float(completed) < float(started):
            errs.append(f"completed_at_s ({completed}) < started_at_s ({started})")
        elif not _m.isclose(float(duration), float(completed) - float(started), rel_tol=1e-9, abs_tol=1e-9):
            errs.append(f"sample_duration_s ({duration}) != completed - started")
    if _is_finite_number(spread) and float(spread) < 0.0:
        errs.append(f"horizontal_spread_m must be >= 0, got {spread}")

    # ── GPS quality ─────────────────────────────────────────────────
    for name in ("gps_fix_type", "gps_satellites"):
        v = getattr(c, name)
        if not _is_strict_int(v):
            errs.append(f"{name} must be a strict integer, got {type(v).__name__} {v!r}")
        elif v < 0:
            errs.append(f"{name} must be >= 0, got {v}")
    for name in ("gps_eph", "gps_epv"):
        v = getattr(c, name)
        if not _is_finite_number(v) or float(v) < 0.0:
            errs.append(f"{name} must be finite >= 0, got {v!r}")

    # ── geometry ────────────────────────────────────────────────────
    g = getattr(c, "geometry", None)
    g_ok = False
    g_olat: float | None = None
    g_olon: float | None = None
    g_fm_lat: float | None = None
    g_fm_lon: float | None = None

    if g is None or not isinstance(g, RuntimeFieldGeometry):
        errs.append(f"geometry must be RuntimeFieldGeometry, got {type(g).__name__}")
    else:
        # profile_id
        if not isinstance(g.profile_id, str) or not g.profile_id.strip():
            errs.append(f"geometry.profile_id must be a non-empty string, got {g.profile_id!r}")
        elif g.profile_id != c.profile_id:
            errs.append(f"geometry.profile_id {g.profile_id!r} != candidate.profile_id {c.profile_id!r}")

        # scalar lat/lon validation
        for name in ("origin_lat", "origin_lon", "forward_marker_lat", "forward_marker_lon"):
            v = getattr(g, name)
            if not _is_finite_number(v):
                errs.append(f"geometry.{name} must be a finite number, got {v!r}")
            else:
                fv = float(v)
                if name.endswith("_lat") and not -90.0 <= fv <= 90.0:
                    errs.append(f"geometry.{name} {fv} out of range [-90, 90]")
                if name.endswith("_lon") and not -180.0 <= fv <= 180.0:
                    errs.append(f"geometry.{name} {fv} out of range [-180, 180]")
                if name == "origin_lat":
                    g_olat = fv
                elif name == "origin_lon":
                    g_olon = fv
                elif name == "forward_marker_lat":
                    g_fm_lat = fv
                elif name == "forward_marker_lon":
                    g_fm_lon = fv

        # heading & baseline
        for name in ("field_heading_yaw_rad", "field_heading_deg"):
            v = getattr(g, name)
            if not _is_finite_number(v):
                errs.append(f"geometry.{name} must be finite, got {v!r}")
        bl_v = getattr(g, "baseline_m")
        g_bl: float | None = None
        if not _is_finite_number(bl_v) or float(bl_v) <= 0.0:
            errs.append(f"geometry.baseline_m must be finite > 0, got {bl_v!r}")
        else:
            g_bl = float(bl_v)

        g_ok = not errs

        # cross-checks with candidate (only when both sides valid)
        if g_ok:
            if parsed_lat is not None and g_olat is not None and not _m.isclose(g_olat, parsed_lat, rel_tol=1e-12, abs_tol=1e-12):
                errs.append(f"geometry.origin_lat {g_olat} != candidate.origin_lat {parsed_lat}")
            if parsed_lon is not None and g_olon is not None and not _m.isclose(g_olon, parsed_lon, rel_tol=1e-12, abs_tol=1e-12):
                errs.append(f"geometry.origin_lon {g_olon} != candidate.origin_lon {parsed_lon}")
            if g_fm_lat is not None and _is_finite_number(c.forward_marker_lat) and not _m.isclose(g_fm_lat, float(c.forward_marker_lat), rel_tol=1e-12, abs_tol=1e-12):
                errs.append("geometry.forward_marker_lat mismatch")
            if g_fm_lon is not None and _is_finite_number(c.forward_marker_lon) and not _m.isclose(g_fm_lon, float(c.forward_marker_lon), rel_tol=1e-12, abs_tol=1e-12):
                errs.append("geometry.forward_marker_lon mismatch")
            if hdg_ok and _is_finite_number(g.field_heading_yaw_rad) and not _m.isclose(float(g.field_heading_yaw_rad), float(hdg_rad), rel_tol=1e-12, abs_tol=1e-12):
                errs.append("geometry field_heading_yaw_rad mismatch")
            if hdg_ok and _is_finite_number(g.field_heading_deg) and not _m.isclose(float(g.field_heading_deg), float(hdg_deg), rel_tol=1e-12, abs_tol=1e-12):
                errs.append("geometry field_heading_deg mismatch")
            if bl_ok and g_bl is not None and not _m.isclose(g_bl, float(bl), rel_tol=1e-12, abs_tol=1e-12):
                errs.append("geometry baseline_m mismatch")

        # home point
        home = getattr(g, "home", None)
        if not isinstance(home, RuntimeFieldPoint):
            errs.append(f"geometry.home must be RuntimeFieldPoint, got {type(home).__name__}")
        else:
            for name in ("lat", "lon"):
                v = getattr(home, name)
                if not _is_finite_number(v):
                    errs.append(f"geometry.home.{name} must be finite, got {v!r}")
            for name in ("field_x_m", "field_y_m", "altitude_m"):
                v = getattr(home, name)
                if not _is_finite_number(v):
                    errs.append(f"geometry.home.{name} must be finite, got {v!r}")
            if not errs:
                if not _m.isclose(home.field_x_m, 0.0, rel_tol=0, abs_tol=1e-12):
                    errs.append(f"geometry.home.field_x_m must be 0, got {home.field_x_m}")
                if not _m.isclose(home.field_y_m, 0.0, rel_tol=0, abs_tol=1e-12):
                    errs.append(f"geometry.home.field_y_m must be 0, got {home.field_y_m}")
                if not _m.isclose(home.altitude_m, 0.0, rel_tol=0, abs_tol=1e-12):
                    errs.append(f"geometry.home.altitude_m must be 0, got {home.altitude_m}")
                if parsed_lat is not None and not _m.isclose(home.lat, parsed_lat, rel_tol=1e-12, abs_tol=1e-12):
                    errs.append("geometry.home.lat != candidate origin")
                if parsed_lon is not None and not _m.isclose(home.lon, parsed_lon, rel_tol=1e-12, abs_tol=1e-12):
                    errs.append("geometry.home.lon != candidate origin")

        # forward marker point
        fwd = getattr(g, "forward_marker", None)
        if not isinstance(fwd, RuntimeFieldPoint):
            errs.append(f"geometry.forward_marker must be RuntimeFieldPoint, got {type(fwd).__name__}")
        else:
            for name in ("lat", "lon", "field_x_m", "field_y_m", "altitude_m"):
                v = getattr(fwd, name)
                if not _is_finite_number(v):
                    errs.append(f"geometry.forward_marker.{name} must be finite, got {v!r}")
            if not errs:
                if not _m.isclose(fwd.field_x_m, 0.0, rel_tol=0, abs_tol=1e-12):
                    errs.append(f"geometry.forward_marker.field_x_m must be 0")
                if bl_ok and g_bl is not None and not _m.isclose(fwd.field_y_m, g_bl, rel_tol=1e-12, abs_tol=1e-12):
                    errs.append(f"geometry.forward_marker.field_y_m must equal baseline_m")
                if not _m.isclose(fwd.altitude_m, 0.0, rel_tol=0, abs_tol=1e-12):
                    errs.append(f"geometry.forward_marker.altitude_m must be 0")
                if _is_finite_number(c.forward_marker_lat) and not _m.isclose(fwd.lat, float(c.forward_marker_lat), rel_tol=1e-12, abs_tol=1e-12):
                    errs.append("geometry.forward_marker.lat != candidate forward_marker_lat")
                if _is_finite_number(c.forward_marker_lon) and not _m.isclose(fwd.lon, float(c.forward_marker_lon), rel_tol=1e-12, abs_tol=1e-12):
                    errs.append("geometry.forward_marker.lon != candidate forward_marker_lon")

        # point collections — minimal structure check
        for attr in ("drop_scan_waypoints", "drop_area_corners", "recce_area_corners"):
            coll = getattr(g, attr, None)
            if not isinstance(coll, tuple):
                errs.append(f"geometry.{attr} must be a tuple, got {type(coll).__name__}")
            else:
                for j, pt in enumerate(coll):
                    if not isinstance(pt, RuntimeFieldPoint):
                        errs.append(f"geometry.{attr}[{j}] must be RuntimeFieldPoint, got {type(pt).__name__}")
                        break  # one error per collection is enough

        # geometry warnings
        gw = getattr(g, "warnings", None)
        if not isinstance(gw, tuple):
            errs.append(f"geometry.warnings must be a tuple, got {type(gw).__name__}")
        else:
            for j, item in enumerate(gw):
                if not isinstance(item, str):
                    errs.append(f"geometry.warnings[{j}] must be a string, got {type(item).__name__}")
                    break

    # ── warnings ────────────────────────────────────────────────────
    w = getattr(c, "warnings", None)
    cw_ok = False
    if not isinstance(w, tuple):
        errs.append(f"candidate.warnings must be a tuple, got {type(w).__name__}")
    else:
        cw_ok = True
        for j, item in enumerate(w):
            if not isinstance(item, str):
                errs.append(f"candidate.warnings[{j}] must be a string, got {type(item).__name__}")
                cw_ok = False
                break
    gw = getattr(getattr(c, "geometry", None), "warnings", None)
    if cw_ok and isinstance(gw, tuple):
        if w != gw:
            errs.append("candidate.warnings != geometry.warnings")

    return tuple(errs)


def _is_finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _is_strict_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)
