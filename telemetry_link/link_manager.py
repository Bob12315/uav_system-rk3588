from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

try:
    from .command_queue import CommandQueue
    from .command_sender import CommandSender
    from .config import EndpointConfig, TelemetryConfig
    from .frames import BODY_NED, LOCAL_NED
    from .mavlink_client import MavlinkClient
    from .models import ActionCommand, ActionType, ControlCommand, ControlType, DroneState, GimbalRateCommand, GimbalState, LinkStatus
    from .state_cache import StateCache
    from .telemetry_receiver import TelemetryReceiver
except ImportError:  # pragma: no cover - supports direct script execution
    from command_queue import CommandQueue
    from command_sender import CommandSender
    from config import EndpointConfig, TelemetryConfig
    from frames import BODY_NED, LOCAL_NED
    from mavlink_client import MavlinkClient
    from models import ActionCommand, ActionType, ControlCommand, ControlType, DroneState, GimbalRateCommand, GimbalState, LinkStatus
    from state_cache import StateCache
    from telemetry_receiver import TelemetryReceiver


@dataclass(slots=True)
class SourceRuntime:
    name: str
    endpoint: EndpointConfig
    cfg: TelemetryConfig
    state_cache: StateCache
    command_queue: CommandQueue
    client: MavlinkClient
    stop_event: threading.Event
    worker_stop_event: threading.Event
    receiver: TelemetryReceiver | None = None
    sender: CommandSender | None = None
    monitor_thread: threading.Thread | None = None
    worker_lock: threading.Lock | None = None

    def __post_init__(self) -> None:
        if self.worker_lock is None:
            self.worker_lock = threading.Lock()

    def start(self, logger: logging.Logger) -> None:
        if self.monitor_thread is not None and self.monitor_thread.is_alive():
            return
        self.monitor_thread = threading.Thread(
            name=f"LinkMonitor-{self.name}",
            target=self._run_loop,
            args=(logger,),
            daemon=True,
        )
        self.monitor_thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self._stop_workers(close_client=True)
        if self.monitor_thread is not None:
            self.monitor_thread.join(timeout=1.0)

    def _connect_and_start_workers(self, logger: logging.Logger) -> None:
        while not self.stop_event.is_set():
            try:
                self.state_cache.mark_reconnecting()
                logger.info("source=%s Attempting to reconnect...", self.name)
                self.client.connect()
                self.client.wait_heartbeat(timeout=max(5.0, self.cfg.heartbeat_timeout_sec + 2.0))
                logger.info(
                    "source=%s link ready connection_type=%s endpoint=%s sitl_mode=%s target_system=%s target_component=%s",
                    self.name,
                    self.endpoint.connection_type,
                    self.client.connection_string,
                    self.client.is_sitl,
                    self.client.target_system,
                    self.client.target_component,
                )
                now = time.time()
                self.state_cache.mark_connected(
                    target_system=self.client.target_system,
                    target_component=self.client.target_component,
                    transport=self.endpoint.connection_type,
                    now=now,
                )
                self.worker_stop_event = threading.Event()
                self.receiver = TelemetryReceiver(
                    self.client,
                    self.state_cache,
                    self.cfg,
                    self.worker_stop_event,
                )
                self.sender = CommandSender(
                    self.client,
                    self.command_queue,
                    self.state_cache,
                    self.cfg,
                    self.worker_stop_event,
                )
                self.receiver.start()
                self.sender.start()
                if self.cfg.request_message_intervals:
                    self._request_default_message_intervals()
                logger.info("source=%s Reconnected successfully", self.name)
                return
            except Exception as exc:
                logger.warning("source=%s reconnect failed: %s", self.name, exc)
                self.client.close()
                if self.stop_event.wait(self.cfg.reconnect_interval_sec):
                    return

    def _stop_workers(self, close_client: bool) -> None:
        with self.worker_lock:
            self.worker_stop_event.set()
            if self.receiver is not None:
                self.receiver.join(timeout=1.0)
                self.receiver = None
            if self.sender is not None:
                self.sender.join(timeout=1.0)
                self.sender = None
            self.command_queue.clear_control()
            self.command_queue.clear_gimbal_rate()
            self.command_queue.clear_actions()
            if close_client:
                self.client.close()

    def _run_loop(self, logger: logging.Logger) -> None:
        self._connect_and_start_workers(logger)
        self._monitor_loop(logger)

    def _monitor_loop(self, logger: logging.Logger) -> None:
        while not self.stop_event.is_set():
            state = self.state_cache.get_latest_drone_state_validated(time.time())
            link = self.state_cache.get_link_status()
            if (not state.connected or state.stale) and not link.reconnecting:
                self.state_cache.mark_reconnecting()
                self._stop_workers(close_client=True)
                if self.stop_event.wait(self.cfg.reconnect_interval_sec):
                    break
                self._connect_and_start_workers(logger)
                continue
            if self.stop_event.wait(0.2):
                break

    def _request_default_message_intervals(self) -> None:
        for message_name, rate_hz in self.cfg.message_interval_hz.items():
            self.command_queue.put_action(
                ActionCommand(
                    action_type=ActionType.REQUEST_MESSAGE_INTERVAL,
                    params={"message_name": message_name, "rate_hz": rate_hz},
                    priority=20,
                    retries_left=1,
                    retry_interval_sec=self.cfg.action_retry_interval_sec,
                    created_at=time.time(),
                )
            )


class LinkManager:
    """
    Multi-source link manager.

    - Maintains separate runtimes for `real` and `sitl`.
    - Exposes only one active source outward.
    - Sends control commands only to the active source.
    """

    def __init__(self, cfg: TelemetryConfig) -> None:
        self.cfg = cfg
        self.logger = logging.getLogger(self.__class__.__name__)
        self.active_source = cfg.active_source
        self.active_lock = threading.Lock()
        self.runtimes: dict[str, SourceRuntime] = {}
        self._start_thread: threading.Thread | None = None

        enabled_sources = (
            ["real", "sitl"] if cfg.data_source == "dual"
            else [cfg.data_source]
        )
        for source_name in enabled_sources:
            endpoint = cfg.real if source_name == "real" else cfg.sitl
            self.runtimes[source_name] = SourceRuntime(
                name=source_name,
                endpoint=endpoint,
                cfg=cfg,
                state_cache=StateCache(cfg.heartbeat_timeout_sec, cfg.rx_timeout_sec),
                command_queue=CommandQueue(),
                client=MavlinkClient(endpoint),
                stop_event=threading.Event(),
                worker_stop_event=threading.Event(),
            )

    def start(self) -> None:
        for runtime in self.runtimes.values():
            runtime.start(self.logger)

    def start_background(self) -> threading.Thread:
        if self._start_thread is not None and self._start_thread.is_alive():
            return self._start_thread
        self._start_thread = threading.Thread(
            name="LinkManagerStart",
            target=self.start,
            daemon=True,
        )
        self._start_thread.start()
        return self._start_thread

    def stop(self) -> None:
        for runtime in self.runtimes.values():
            runtime.stop()
        if self._start_thread is not None and self._start_thread.is_alive():
            self._start_thread.join(timeout=1.0)

    def get_active_source(self) -> str:
        with self.active_lock:
            return self.active_source

    def switch_active_source(self, source_name: str) -> bool:
        if source_name not in self.runtimes:
            self.logger.warning("switch_source failed: source=%s is not enabled by data_source=%s", source_name, self.cfg.data_source)
            return False
        previous_source = self.get_active_source()
        with self.active_lock:
            self.active_source = source_name
        self._clear_continuous_commands()
        self.logger.info("switched active_source=%s previous_source=%s", source_name, previous_source)
        return True

    def _clear_continuous_commands(self) -> None:
        for runtime in self.runtimes.values():
            runtime.command_queue.clear_control()
            runtime.command_queue.clear_gimbal_rate()

    def _active_runtime(self) -> SourceRuntime:
        source_name = self.get_active_source()
        return self.runtimes[source_name]

    def get_latest_drone_state(self) -> DroneState:
        runtime = self._active_runtime()
        return runtime.state_cache.get_latest_drone_state_validated(time.time())

    def get_latest_gimbal_state(self) -> GimbalState:
        runtime = self._active_runtime()
        return runtime.state_cache.get_latest_gimbal_state_validated(time.time())

    def get_latest_state(self) -> DroneState:
        return self.get_latest_drone_state()

    def get_latest_state_raw(self) -> DroneState:
        return self._active_runtime().state_cache.get_latest_drone_state_raw()

    def get_link_status(self) -> LinkStatus:
        return self._active_runtime().state_cache.get_link_status()

    def get_source_state(self, source_name: str) -> DroneState:
        runtime = self.runtimes[source_name]
        return runtime.state_cache.get_latest_drone_state_validated(time.time())

    def get_source_gimbal_state(self, source_name: str) -> GimbalState:
        runtime = self.runtimes[source_name]
        return runtime.state_cache.get_latest_gimbal_state_validated(time.time())

    def get_source_link_status(self, source_name: str) -> LinkStatus:
        return self.runtimes[source_name].state_cache.get_link_status()

    def is_connected(self) -> bool:
        link = self.get_link_status()
        now = time.time()
        heartbeat_expired = link.last_heartbeat_time > 0 and (now - link.last_heartbeat_time) > link.heartbeat_timeout_sec
        rx_expired = link.last_rx_time > 0 and (now - link.last_rx_time) > link.rx_timeout_sec
        return link.connected and not link.reconnecting and not heartbeat_expired and not rx_expired

    def submit_control_command(self, command: ControlCommand) -> None:
        self._active_runtime().command_queue.put_control(command)

    def submit_action_command(self, command: ActionCommand) -> None:
        self._active_runtime().command_queue.put_action(command)

    def clear_continuous_commands(self) -> None:
        runtime = self._active_runtime()
        runtime.command_queue.clear_control()
        runtime.command_queue.clear_gimbal_rate()

    def set_mode(self, mode: str, priority: int = 5) -> None:
        self.submit_action_command(
            ActionCommand(
                action_type=ActionType.SET_MODE,
                params={"mode": mode},
                priority=priority,
                retries_left=self.cfg.action_cmd_retries,
                retry_interval_sec=self.cfg.action_retry_interval_sec,
                created_at=time.time(),
            )
        )

    def arm(self, priority: int = 1) -> None:
        self.submit_action_command(
            ActionCommand(
                action_type=ActionType.ARM,
                priority=priority,
                retries_left=self.cfg.action_cmd_retries,
                retry_interval_sec=self.cfg.action_retry_interval_sec,
                created_at=time.time(),
            )
        )

    def disarm(self, priority: int = 1) -> None:
        self.submit_action_command(
            ActionCommand(
                action_type=ActionType.DISARM,
                priority=priority,
                retries_left=self.cfg.action_cmd_retries,
                retry_interval_sec=self.cfg.action_retry_interval_sec,
                created_at=time.time(),
            )
        )

    def takeoff(self, altitude_m: float, priority: int = 2) -> None:
        self.submit_action_command(
            ActionCommand(
                action_type=ActionType.TAKEOFF,
                params={"altitude_m": float(altitude_m)},
                priority=priority,
                retries_left=self.cfg.action_cmd_retries,
                retry_interval_sec=self.cfg.action_retry_interval_sec,
                created_at=time.time(),
            )
        )

    def land(self, priority: int = 2) -> None:
        self.submit_action_command(
            ActionCommand(
                action_type=ActionType.LAND,
                priority=priority,
                retries_left=self.cfg.action_cmd_retries,
                retry_interval_sec=self.cfg.action_retry_interval_sec,
                created_at=time.time(),
            )
        )

    def condition_yaw(
        self,
        yaw_deg: float,
        yaw_speed_deg_s: float = 20.0,
        direction: int = 0,
        relative: bool = False,
        priority: int = 4,
    ) -> None:
        self.submit_action_command(
            ActionCommand(
                action_type=ActionType.CONDITION_YAW,
                params={
                    "yaw_deg": float(yaw_deg),
                    "yaw_speed_deg_s": float(yaw_speed_deg_s),
                    "direction": int(direction),
                    "relative": bool(relative),
                },
                priority=priority,
                retries_left=self.cfg.action_cmd_retries,
                retry_interval_sec=self.cfg.action_retry_interval_sec,
                created_at=time.time(),
            )
        )

    def change_speed(self, speed_mps: float, speed_type: int = 1, priority: int = 4) -> None:
        self.submit_action_command(
            ActionCommand(
                action_type=ActionType.CHANGE_SPEED,
                params={"speed_mps": float(speed_mps), "speed_type": int(speed_type)},
                priority=priority,
                retries_left=self.cfg.action_cmd_retries,
                retry_interval_sec=self.cfg.action_retry_interval_sec,
                created_at=time.time(),
            )
        )

    def set_home_current(self, priority: int = 4) -> None:
        self.submit_action_command(
            ActionCommand(
                action_type=ActionType.SET_HOME,
                params={"current": True, "lat": 0.0, "lon": 0.0, "alt": 0.0},
                priority=priority,
                retries_left=self.cfg.action_cmd_retries,
                retry_interval_sec=self.cfg.action_retry_interval_sec,
                created_at=time.time(),
            )
        )

    def set_home_location(self, lat: float, lon: float, alt: float, priority: int = 4) -> None:
        self.submit_action_command(
            ActionCommand(
                action_type=ActionType.SET_HOME,
                params={"current": False, "lat": float(lat), "lon": float(lon), "alt": float(alt)},
                priority=priority,
                retries_left=self.cfg.action_cmd_retries,
                retry_interval_sec=self.cfg.action_retry_interval_sec,
                created_at=time.time(),
            )
        )

    def global_goto(
        self,
        lat: float,
        lon: float,
        alt: float,
        frame: int,
        priority: int = 4,
    ) -> None:
        self.submit_action_command(
            ActionCommand(
                action_type=ActionType.GLOBAL_GOTO,
                params={"lat": float(lat), "lon": float(lon), "alt": float(alt), "frame": int(frame)},
                priority=priority,
                retries_left=self.cfg.action_cmd_retries,
                retry_interval_sec=self.cfg.action_retry_interval_sec,
                created_at=time.time(),
            )
        )

    def local_position(
        self,
        x: float,
        y: float,
        z: float,
        frame: int,
        yaw: float | None = None,
        priority: int = 4,
    ) -> None:
        params = {"x": float(x), "y": float(y), "z": float(z), "frame": int(frame)}
        if yaw is not None:
            params["yaw"] = float(yaw)
        self.submit_action_command(
            ActionCommand(
                action_type=ActionType.LOCAL_POSITION,
                params=params,
                priority=priority,
                retries_left=self.cfg.action_cmd_retries,
                retry_interval_sec=self.cfg.action_retry_interval_sec,
                created_at=time.time(),
            )
        )

    def reposition(
        self,
        lat: float,
        lon: float,
        alt: float,
        ground_speed_mps: float = -1.0,
        yaw_deg: float | None = None,
        priority: int = 4,
    ) -> None:
        self.submit_action_command(
            ActionCommand(
                action_type=ActionType.REPOSITION,
                params={
                    "lat": float(lat),
                    "lon": float(lon),
                    "alt": float(alt),
                    "ground_speed_mps": float(ground_speed_mps),
                    "yaw_deg": yaw_deg,
                },
                priority=priority,
                retries_left=self.cfg.action_cmd_retries,
                retry_interval_sec=self.cfg.action_retry_interval_sec,
                created_at=time.time(),
            )
        )

    def set_roi_location(self, lat: float, lon: float, alt: float, priority: int = 4) -> None:
        self.submit_action_command(
            ActionCommand(
                action_type=ActionType.SET_ROI_LOCATION,
                params={"lat": float(lat), "lon": float(lon), "alt": float(alt)},
                priority=priority,
                retries_left=self.cfg.action_cmd_retries,
                retry_interval_sec=self.cfg.action_retry_interval_sec,
                created_at=time.time(),
            )
        )

    def roi_none(self, gimbal_device_id: int = 0, priority: int = 4) -> None:
        self.submit_action_command(
            ActionCommand(
                action_type=ActionType.ROI_NONE,
                params={"gimbal_device_id": int(gimbal_device_id)},
                priority=priority,
                retries_left=self.cfg.action_cmd_retries,
                retry_interval_sec=self.cfg.action_retry_interval_sec,
                created_at=time.time(),
            )
        )

    def gimbal_manager_configure(
        self,
        gimbal_device_id: int = 0,
        primary_sysid: int | None = None,
        primary_compid: int | None = None,
        priority: int = 4,
    ) -> None:
        self.submit_action_command(
            ActionCommand(
                action_type=ActionType.GIMBAL_MANAGER_CONFIGURE,
                params={
                    "gimbal_device_id": int(gimbal_device_id),
                    "primary_sysid": primary_sysid,
                    "primary_compid": primary_compid,
                },
                priority=priority,
                retries_left=self.cfg.action_cmd_retries,
                retry_interval_sec=self.cfg.action_retry_interval_sec,
                created_at=time.time(),
            )
        )

    def set_servo(self, channel: int, pwm: int, priority: int = 3) -> None:
        self.logger.info(
            "link_manager.set_servo channel=%s pwm=%s priority=%s",
            int(channel),
            int(pwm),
            int(priority),
        )
        self.submit_action_command(
            ActionCommand(
                action_type=ActionType.SET_SERVO,
                params={"channel": int(channel), "pwm": int(pwm)},
                priority=priority,
                retries_left=self.cfg.action_cmd_retries,
                retry_interval_sec=self.cfg.action_retry_interval_sec,
                created_at=time.time(),
            )
        )

    def set_relay(self, relay_id: int, state: bool, priority: int = 3) -> None:
        self.submit_action_command(
            ActionCommand(
                action_type=ActionType.SET_RELAY,
                params={"relay_id": int(relay_id), "state": bool(state)},
                priority=priority,
                retries_left=self.cfg.action_cmd_retries,
                retry_interval_sec=self.cfg.action_retry_interval_sec,
                created_at=time.time(),
            )
        )

    def release_payload(self, payload_id: int, priority: int = 3) -> None:
        raise NotImplementedError(
            "release_payload is disabled; use set_servo_output_pwm(...) "
            "or set_servo(...) for MAV_CMD_DO_SET_SERVO payload release"
        )

    def request_message_interval(self, message_name: str, rate_hz: float, priority: int = 6) -> None:
        self.submit_action_command(
            ActionCommand(
                action_type=ActionType.REQUEST_MESSAGE_INTERVAL,
                params={"message_name": str(message_name), "rate_hz": float(rate_hz)},
                priority=priority,
                retries_left=self.cfg.action_cmd_retries,
                retry_interval_sec=self.cfg.action_retry_interval_sec,
                created_at=time.time(),
            )
        )

    def send_gimbal_angle(
        self,
        pitch: float,
        yaw: float,
        roll: float = 0.0,
        mount_mode: int | None = None,
        priority: int = 5,
    ) -> None:
        self.submit_action_command(
            ActionCommand(
                action_type=ActionType.GIMBAL_ANGLE,
                params={
                    "pitch": float(pitch),
                    "yaw": float(yaw),
                    "roll": float(roll),
                    "mount_mode": int(self.cfg.gimbal_mount_mode if mount_mode is None else mount_mode),
                },
                priority=priority,
                retries_left=self.cfg.action_cmd_retries,
                retry_interval_sec=self.cfg.action_retry_interval_sec,
                created_at=time.time(),
            )
        )

    def send_gimbal_rate(
        self,
        yaw_rate: float,
        pitch_rate: float,
        yaw_lock: bool = False,
        gimbal_device_id: int = 0,
    ) -> None:
        self._active_runtime().command_queue.put_gimbal_rate(
            GimbalRateCommand(
                yaw_rate=float(yaw_rate),
                pitch_rate=float(pitch_rate),
                yaw_lock=bool(yaw_lock),
                gimbal_device_id=int(gimbal_device_id),
                created_at=time.time(),
            )
        )

    def send_velocity_command(self, vx: float, vy: float, vz: float, frame: int = 1) -> None:
        self.submit_control_command(
            ControlCommand(
                command_type=ControlType.VELOCITY,
                vx=vx,
                vy=vy,
                vz=vz,
                timestamp=time.time(),
                frame=frame,
            )
        )

    def send_yaw_rate_command(self, yaw_rate: float, frame: int = 1) -> None:
        self.submit_control_command(
            ControlCommand(
                command_type=ControlType.YAW_RATE,
                yaw_rate=yaw_rate,
                timestamp=time.time(),
                frame=frame,
            )
        )

    def stop_control(self, frame: int = 1) -> None:
        self.submit_control_command(
            ControlCommand(
                command_type=ControlType.STOP,
                vx=0.0,
                vy=0.0,
                vz=0.0,
                yaw_rate=0.0,
                timestamp=time.time(),
                frame=frame,
            )
        )

    def stop_body_velocity(self) -> None:
        """Stop BODY_NED velocity control by sending zero body-frame velocity."""
        self.stop_control(frame=BODY_NED)

    # ------------------------------------------------------------------
    # semantic wrappers (added T1 — zero behavioural change)
    # ------------------------------------------------------------------

    def goto_local_ned(
        self,
        x_north_m: float,
        y_east_m: float,
        z_down_m: float,
        yaw_rad: float | None = None,
        priority: int = 4,
    ) -> None:
        """Position target in LOCAL_NED frame.

        x_north_m  – metres North
        y_east_m   – metres East
        z_down_m   – metres Down (positive = down)
        yaw_rad    – optional target yaw in radians
        priority   – lower value = higher priority
        """
        self.local_position(
            x=x_north_m,
            y=y_east_m,
            z=z_down_m,
            frame=LOCAL_NED,
            yaw=yaw_rad,
            priority=priority,
        )
        return

    def send_body_velocity(
        self,
        vx_forward_mps: float,
        vy_right_mps: float,
        vz_down_mps: float,
    ) -> None:
        """Velocity command in BODY_NED (body-fixed) frame.

        vx_forward_mps – forward velocity (m/s)
        vy_right_mps   – right velocity (m/s)
        vz_down_mps    – down velocity (m/s)
        """
        self.send_velocity_command(
            vx=vx_forward_mps,
            vy=vy_right_mps,
            vz=vz_down_mps,
            frame=BODY_NED,
        )
        return

    def set_servo_output_pwm(
        self,
        servo_output: int,
        pwm: int,
        priority: int = 3,
    ) -> None:
        """Set a flight-controller SERVO output PWM value.

        servo_output is a flight-controller SERVO output number,
        NOT an RC input channel.  This maps to MAV_CMD_DO_SET_SERVO.
        """
        self.set_servo(
            channel=servo_output,
            pwm=pwm,
            priority=priority,
        )
        return
