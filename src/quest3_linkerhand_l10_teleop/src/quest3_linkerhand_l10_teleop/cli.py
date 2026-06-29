#!/usr/bin/env python3
import argparse
import logging
import signal
import sys
import time
import traceback
from typing import Iterable, List, Optional

from .l10_can import L10CanHand, default_socketcan_interface
from .oculus_reader import OculusReader
from .teleop_core import (
    FINGER_NAMES,
    build_joint_steps,
    button_is_pressed,
    button_value,
    freeze_fingers_from_pressure,
    interpolate_pose,
    move_pose_toward,
    pose_to_bytes,
)


DEFAULT_OPEN = [255, 255, 255, 255, 255, 255, 255, 255, 255, 255]
DEFAULT_CLOSED = [0, 255, 0, 0, 0, 0, 255, 255, 255, 255]
DEFAULT_PICKUP_OPEN = [255, 0, 255, 255, 255, 255, 255, 255, 255, 255]
DEFAULT_PICKUP = [0, 0, 0, 0, 0, 0, 255, 255, 255, 255]


def parse_byte_list(raw: Optional[str], expected_lengths: Iterable[int], name: str) -> Optional[List[int]]:
    if raw in (None, ""):
        return None
    values = [int(float(part.strip())) for part in raw.split(",") if part.strip()]
    if len(values) not in expected_lengths:
        allowed = " or ".join(str(length) for length in expected_lengths)
        raise argparse.ArgumentTypeError(f"{name} must contain {allowed} comma-separated values")
    for value in values:
        if not 0 <= value <= 255:
            raise argparse.ArgumentTypeError(f"{name} values must be in the 0..255 range")
    return values


def parse_pose(raw: Optional[str], default: List[int], name: str) -> List[float]:
    values = parse_byte_list(raw, [10], name)
    if values is None:
        values = default
    return [float(value) for value in values]


class Quest3L10Teleop:
    def __init__(self, args):
        self.args = args
        self.hand_type = args.hand_type.lower()

        self.open_pose = parse_pose(args.open_position, DEFAULT_OPEN, "--open-position")
        self.closed_pose = parse_pose(args.closed_position, DEFAULT_CLOSED, "--closed-position")
        self.pickup_open_pose = parse_pose(
            args.pickup_open_position,
            DEFAULT_PICKUP_OPEN,
            "--pickup-open-position",
        )
        self.pickup_pose = parse_pose(args.pickup_position, DEFAULT_PICKUP, "--pickup-position")
        self.current_pose = list(self.open_pose)
        self.joint_steps = build_joint_steps(
            args.step_per_cycle,
            thumb_pitch_scale=args.thumb_pitch_speed_scale,
        )
        self.pickup_mode_enabled = False
        self.prev_pickup_button_pressed = False
        self.frozen_fingers = [False] * 5
        self.prev_enabled = False
        self.last_close_amount = 0.0
        self.last_mode = "normal"
        self.last_sent = None
        self.latest_pressures = [0.0] * 5
        self.last_force_poll = 0.0
        self.last_waiting_log = 0.0
        self.running = True
        self.reader = None
        self.hand = None

    def start(self):
        logging.info(
            "Starting Quest3 -> %s LinkerHand L10 teleop on %s (%s @ %d)",
            self.hand_type,
            self.args.can_channel,
            self.args.can_interface,
            self.args.bitrate,
        )
        logging.info(
            "Hold %s to enable teleop; use %s as the analog open/close trigger.",
            self.args.teleop_button,
            self.args.close_axis,
        )
        logging.info(
            "Press %s to toggle pickup mode; press it again for normal bend-only grip mode.",
            self.args.pickup_mode_button,
        )

        self.hand = L10CanHand(
            hand_type=self.hand_type,
            channel=self.args.can_channel,
            bitrate=self.args.bitrate,
            interface=self.args.can_interface,
        )

        speed = parse_byte_list(self.args.speed, [5, 10], "--speed")
        torque = parse_byte_list(self.args.torque, [5, 10], "--torque")
        if speed:
            self.hand.set_speed(speed)
        if torque:
            self.hand.set_torque(torque)

        if self.args.open_on_start:
            self.hand.set_joint_positions(pose_to_bytes(self.open_pose))
            self.last_sent = pose_to_bytes(self.open_pose)
            logging.info("Sent startup open pose: %s", self.last_sent)
        else:
            measured = self.hand.get_joint_status(wait_s=0.03)
            if measured:
                self.current_pose = [float(value) for value in measured]
                logging.info("Initialized from current L10 joint status: %s", measured)

        self.reader = OculusReader(
            ip_address=self.args.quest_ip or None,
            apk_path=self.args.apk_path or None,
            print_fps=self.args.print_quest_fps,
        )

    def run(self):
        self.start()
        period_s = 1.0 / max(self.args.command_rate_hz, 1.0)
        while self.running:
            started = time.monotonic()
            try:
                self.step()
            except Exception as exc:
                logging.error("Teleop step failed: %s\n%s", exc, traceback.format_exc())
            elapsed = time.monotonic() - started
            if elapsed < period_s:
                time.sleep(period_s - elapsed)

    def stop(self):
        self.running = False
        logging.info("Shutting down Quest3 L10 teleop.")
        if self.reader:
            self.reader.stop()
        if self.hand:
            self.hand.shutdown()

    def step(self):
        _, buttons = self.reader.get_transformations_and_buttons()
        if not buttons:
            now = time.monotonic()
            if now - self.last_waiting_log >= 2.0:
                logging.warning("Waiting for Quest button data...")
                self.last_waiting_log = now
            return

        enabled = button_is_pressed(buttons, self.args.teleop_button, self.args.button_threshold)
        close_amount = button_value(buttons, self.args.close_axis)
        pickup_button_pressed = button_is_pressed(
            buttons,
            self.args.pickup_mode_button,
            self.args.button_threshold,
        )
        if pickup_button_pressed and not self.prev_pickup_button_pressed:
            self.pickup_mode_enabled = not self.pickup_mode_enabled
            logging.info(
                "%s grip mode selected.",
                "Pickup" if self.pickup_mode_enabled else "Normal",
            )
        self.prev_pickup_button_pressed = pickup_button_pressed

        mode = "pickup" if self.pickup_mode_enabled else "normal"

        if not enabled:
            if self.prev_enabled:
                logging.info("Teleop disabled; holding last LinkerHand command.")
            self.prev_enabled = False
            return

        if not self.prev_enabled:
            logging.info("Teleop enabled.")
        self.prev_enabled = True

        if mode != self.last_mode:
            self.frozen_fingers = [False] * 5
            logging.info("%s grip mode selected; pressure freezes cleared.", mode.capitalize())
            self.last_mode = mode

        is_opening = close_amount < (self.last_close_amount - self.args.trigger_deadband)
        if close_amount <= self.args.trigger_deadband or is_opening:
            if any(self.frozen_fingers):
                logging.info("Opening trigger detected; pressure freezes cleared.")
            self.frozen_fingers = [False] * 5

        if close_amount > self.args.trigger_deadband:
            self.poll_pressures_if_due()
            self.apply_pressure_freeze()

        open_pose = self.pickup_open_pose if self.pickup_mode_enabled else self.open_pose
        close_pose = self.pickup_pose if self.pickup_mode_enabled else self.closed_pose
        target = interpolate_pose(open_pose, close_pose, close_amount)

        self.current_pose = move_pose_toward(
            self.current_pose,
            target,
            self.frozen_fingers,
            self.joint_steps,
        )
        self.last_close_amount = close_amount
        self.send_if_changed(self.current_pose)

    def poll_pressures_if_due(self):
        now = time.monotonic()
        min_period = 1.0 / max(self.args.force_poll_hz, 1.0)
        if now - self.last_force_poll < min_period:
            return
        self.hand.request_pressure()
        self.latest_pressures = self.hand.get_finger_pressures()
        self.last_force_poll = now
        logging.debug("L10 finger pressures: %s", self.latest_pressures)

    def apply_pressure_freeze(self):
        crossing = [
            index
            for index, pressure in enumerate(self.latest_pressures)
            if not self.frozen_fingers[index] and pressure >= self.args.pressure_threshold
        ]
        next_pose, next_frozen = freeze_fingers_from_pressure(
            self.current_pose,
            self.frozen_fingers,
            self.latest_pressures,
            self.args.pressure_threshold,
        )
        for index in crossing:
            logging.info(
                "Freezing %s at pressure %.1f >= %.1f",
                FINGER_NAMES[index],
                self.latest_pressures[index],
                self.args.pressure_threshold,
            )
        self.current_pose = next_pose
        self.frozen_fingers = next_frozen

    def send_if_changed(self, pose):
        command = pose_to_bytes(pose)
        if command == self.last_sent:
            return
        if self.last_sent and self.args.pose_deadband > 0:
            max_delta = max(abs(next_value - last_value) for next_value, last_value in zip(command, self.last_sent))
            if max_delta < self.args.pose_deadband:
                return
        self.hand.set_joint_positions(command)
        self.last_sent = command


def build_parser():
    parser = argparse.ArgumentParser(
        description="Control a LinkerHand L10 with the Meta Quest 3 left controller."
    )
    parser.add_argument("--can-channel", default="can0", help="SocketCAN channel, usually can0.")
    parser.add_argument("--bitrate", type=int, default=1000000, help="CAN bitrate.")
    parser.add_argument(
        "--can-interface",
        default=default_socketcan_interface(),
        help="python-can interface name. Linux default is socketcan.",
    )
    parser.add_argument("--hand-type", choices=["left", "right"], default="left")
    parser.add_argument("--quest-ip", default="", help="Quest IP for Wi-Fi ADB mode. Omit for USB.")
    parser.add_argument("--apk-path", default="", help="Path to teleop-debug.apk if not already installed.")
    parser.add_argument("--teleop-button", default="leftGrip", help="Hold this Quest input to enable teleop.")
    parser.add_argument("--close-axis", default="leftTrig", help="Analog Quest input used for open/close.")
    parser.add_argument("--pickup-mode-button", default="Y", help="Press this button to toggle pickup/pinch mode.")
    parser.add_argument("--button-threshold", type=float, default=0.15)
    parser.add_argument("--pressure-threshold", type=float, default=10)
    parser.add_argument("--command-rate-hz", type=float, default=30.0)
    parser.add_argument("--force-poll-hz", type=float, default=25.0)
    parser.add_argument("--step-per-cycle", type=float, default=8.0)
    parser.add_argument("--thumb-pitch-speed-scale", type=float, default=0.75)
    parser.add_argument("--trigger-deadband", type=float, default=0.03)
    parser.add_argument("--pose-deadband", type=float, default=2.0)
    parser.add_argument("--open-position", default="", help="10 comma-separated 0..255 joint values.")
    parser.add_argument("--closed-position", default="", help="10 comma-separated 0..255 joint values.")
    parser.add_argument("--pickup-open-position", default="", help="10 comma-separated pickup open joint values.")
    parser.add_argument("--pickup-position", default="", help="10 comma-separated pickup/pinch joint values.")
    parser.add_argument("--speed", default="", help="Optional 5 or 10 comma-separated speed values.")
    parser.add_argument("--torque", default="", help="Optional 5 or 10 comma-separated torque values.")
    parser.add_argument("--no-open-on-start", dest="open_on_start", action="store_false")
    parser.set_defaults(open_on_start=True)
    parser.add_argument("--print-quest-fps", action="store_true")
    parser.add_argument("--debug", action="store_true")
    return parser


def configure_logging(debug=False):
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format="%(asctime)s %(levelname)s: %(message)s",
    )


def main(argv=None):
    args = build_parser().parse_args(argv)
    configure_logging(args.debug)
    teleop = Quest3L10Teleop(args)

    def handle_signal(signum, frame):
        teleop.stop()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    try:
        teleop.run()
    finally:
        teleop.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
