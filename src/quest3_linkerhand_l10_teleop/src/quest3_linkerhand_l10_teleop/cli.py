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
    button_is_pressed,
    button_value,
    freeze_fingers_from_pressure,
    interpolate_pose,
    move_pose_toward,
    pose_to_bytes,
)


DEFAULT_OPEN = [255, 255, 255, 255, 255, 255, 255, 255, 255, 255]
DEFAULT_CLOSED = [80, 255, 80, 80, 80, 80, 255, 255, 255, 255]
DEFAULT_FIST = [0, 255, 0, 0, 0, 0, 255, 255, 255, 255]


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
        self.fist_pose = parse_pose(args.fist_position, DEFAULT_FIST, "--fist-position")
        self.current_pose = list(self.open_pose)
        self.frozen_fingers = [False] * 5
        self.prev_enabled = False
        self.prev_mimic_pressed = False
        self.mimic_enabled = False
        self.mimic_started_at = 0.0
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
            "Press %s to toggle mimic open-close; hold %s for full-fist mode.",
            self.args.mimic_button,
            self.args.fist_mode_button,
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
        trigger_close_amount = button_value(buttons, self.args.close_axis)
        fist_mode = button_is_pressed(buttons, self.args.fist_mode_button, self.args.button_threshold)
        mimic_pressed = button_is_pressed(buttons, self.args.mimic_button, self.args.button_threshold)
        now = time.monotonic()

        if not enabled:
            if self.prev_enabled:
                logging.info("Teleop disabled; holding last LinkerHand command.")
            self.prev_enabled = False
            self.prev_mimic_pressed = mimic_pressed
            self.mimic_enabled = False
            return

        if not self.prev_enabled:
            logging.info("Teleop enabled.")
        self.prev_enabled = True

        if mimic_pressed and not self.prev_mimic_pressed:
            self.mimic_enabled = not self.mimic_enabled
            self.mimic_started_at = now
            self.frozen_fingers = [False] * 5
            logging.info("Mimic open-close %s; pressure freezes cleared.", "enabled" if self.mimic_enabled else "disabled")
        self.prev_mimic_pressed = mimic_pressed

        close_amount = self.mimic_close_amount(now) if self.mimic_enabled else trigger_close_amount
        mode = "fist" if fist_mode else "normal"
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

        close_pose = self.fist_pose if fist_mode else self.closed_pose
        target = interpolate_pose(self.open_pose, close_pose, close_amount)

        self.current_pose = move_pose_toward(
            self.current_pose,
            target,
            self.frozen_fingers,
            self.args.step_per_cycle,
        )
        self.last_close_amount = close_amount
        self.send_if_changed(self.current_pose)

    def mimic_close_amount(self, now):
        period = max(self.args.mimic_period_s, 0.5)
        phase = ((now - self.mimic_started_at) % period) / period
        if phase < 0.5:
            return phase * 2.0
        return (1.0 - phase) * 2.0

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
        measured = self.hand.get_joint_status(wait_s=0.01) if crossing else None
        next_pose, next_frozen = freeze_fingers_from_pressure(
            self.current_pose,
            self.frozen_fingers,
            self.latest_pressures,
            self.args.pressure_threshold,
            measured_position=measured,
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
    parser.add_argument("--mimic-button", default="X", help="Press this button to toggle automatic open-close mimic mode.")
    parser.add_argument("--fist-mode-button", default="Y", help="Hold this button for full-fist close mode.")
    parser.add_argument("--button-threshold", type=float, default=0.15)
    parser.add_argument("--pressure-threshold", type=float, default=70.0)
    parser.add_argument("--command-rate-hz", type=float, default=30.0)
    parser.add_argument("--force-poll-hz", type=float, default=25.0)
    parser.add_argument("--step-per-cycle", type=float, default=8.0)
    parser.add_argument("--trigger-deadband", type=float, default=0.03)
    parser.add_argument("--mimic-period-s", type=float, default=3.0)
    parser.add_argument("--open-position", default="", help="10 comma-separated 0..255 joint values.")
    parser.add_argument("--closed-position", default="", help="10 comma-separated 0..255 joint values.")
    parser.add_argument("--fist-position", default="", help="10 comma-separated full-fist joint values.")
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
