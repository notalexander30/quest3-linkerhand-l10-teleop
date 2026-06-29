import sys
import threading
import time
from typing import Iterable, List, Optional


try:
    import can
except ImportError:  # pragma: no cover - exercised on the robot when dependency is missing
    can = None


class L10CanHand:
    """Minimal LinkerHand L10 CAN driver.

    This mirrors the L10 SDK behavior:
    - left hand uses CAN ID 0x28, right hand uses 0x27
    - position commands are split across 0x04 (joints 7..10) and 0x01 (joints 1..6)
    - five-finger normal force arrives on 0x20
    - tactile/matrix pressure can arrive on 0xb1..0xb5
    """

    HAND_IDS = {"left": 0x28, "right": 0x27}

    JOINT_POSITION_RCO = 0x01
    MAX_PRESS_RCO = 0x02
    MAX_PRESS_RCO2 = 0x03
    JOINT_POSITION2_RCO = 0x04
    JOINT_SPEED = 0x05
    JOINT_SPEED2 = 0x06
    HAND_NORMAL_FORCE = 0x20
    HAND_TANGENTIAL_FORCE = 0x21
    HAND_TANGENTIAL_FORCE_DIR = 0x22
    HAND_APPROACH_INC = 0x23
    MATRIX_TOUCH_REQUEST = 0xC6
    MATRIX_ROWS = 12
    MATRIX_COLS = 6
    TOUCH_ZONES_PER_FINGER = 3
    MATRIX_ROW_MAP = {
        0: 0,
        16: 1,
        32: 2,
        48: 3,
        64: 4,
        80: 5,
        96: 6,
        112: 7,
        128: 8,
        144: 9,
        160: 10,
        176: 11,
    }

    def __init__(
        self,
        hand_type: str = "left",
        channel: str = "can0",
        bitrate: int = 1000000,
        interface: str = "socketcan",
    ):
        if can is None:
            raise RuntimeError("python-can is required. Install it with `pip install python-can`.")

        normalized_hand_type = hand_type.lower()
        if normalized_hand_type not in self.HAND_IDS:
            raise ValueError("hand_type must be 'left' or 'right'")

        self.hand_type = normalized_hand_type
        self.can_id = self.HAND_IDS[self.hand_type]
        self.channel = channel
        self.bitrate = int(bitrate)
        self.interface = interface
        self._lock = threading.Lock()

        self._joint_status_1 = [-1] * 6
        self._joint_status_2 = [-1] * 4
        self._normal_force = [0.0] * 5
        self._tangential_force = [0.0] * 5
        self._tangential_force_dir = [255.0] * 5
        self._approach_inc = [0.0] * 5
        self._touch_pressure = [-1.0] * 5
        self._touch_matrix = [
            [[-1.0] * self.MATRIX_COLS for _ in range(self.MATRIX_ROWS)]
            for _ in range(5)
        ]
        self._last_command = [255] * 10

        self.bus = self._open_bus()
        self.running = True
        self.receive_thread = threading.Thread(target=self._receive_loop)
        self.receive_thread.daemon = True
        self.receive_thread.start()

    def _open_bus(self):
        kwargs = {
            "channel": self.channel,
            "interface": self.interface,
            "bitrate": self.bitrate,
        }
        try:
            return can.interface.Bus(**kwargs)
        except TypeError:
            kwargs["bustype"] = kwargs.pop("interface")
            return can.interface.Bus(**kwargs)

    @staticmethod
    def _byte(value) -> int:
        return max(0, min(255, int(round(float(value)))))

    def send_frame(self, frame_property: int, data: Optional[Iterable[int]] = None, sleep_s=0.002):
        payload = [self._byte(frame_property)]
        if data:
            payload.extend(self._byte(value) for value in data)
        msg = can.Message(
            arbitration_id=self.can_id,
            data=bytearray(payload),
            is_extended_id=False,
        )
        self.bus.send(msg)
        if sleep_s:
            time.sleep(sleep_s)

    def set_joint_positions(self, joint_positions: Iterable[int]):
        positions = [self._byte(value) for value in joint_positions]
        if len(positions) != 10:
            raise ValueError("L10 joint position command must contain 10 values")
        with self._lock:
            self._last_command = list(positions)
        self.send_frame(self.JOINT_POSITION2_RCO, positions[6:10], sleep_s=0.001)
        self.send_frame(self.JOINT_POSITION_RCO, positions[0:6], sleep_s=0.002)

    def set_speed(self, speed: Iterable[int]):
        values = [self._byte(value) for value in speed]
        if len(values) == 5:
            self.send_frame(self.JOINT_SPEED, values)
        elif len(values) == 10:
            self.send_frame(self.JOINT_SPEED, values[:5])
            self.send_frame(self.JOINT_SPEED2, values[5:])
        else:
            raise ValueError("L10 speed command must contain 5 or 10 values")

    def set_torque(self, torque: Iterable[int]):
        values = [self._byte(value) for value in torque]
        if len(values) == 5:
            self.send_frame(self.MAX_PRESS_RCO, values)
            self.send_frame(self.MAX_PRESS_RCO2, values)
        elif len(values) == 10:
            self.send_frame(self.MAX_PRESS_RCO, values[:5])
            self.send_frame(self.MAX_PRESS_RCO2, values[5:])
        else:
            raise ValueError("L10 torque command must contain 5 or 10 values")

    def request_pressure(self):
        self.send_frame(self.HAND_NORMAL_FORCE, [], sleep_s=0.001)
        self.send_frame(self.HAND_TANGENTIAL_FORCE, [], sleep_s=0.001)
        self.send_frame(self.HAND_TANGENTIAL_FORCE_DIR, [], sleep_s=0.001)
        self.send_frame(self.HAND_APPROACH_INC, [], sleep_s=0.001)
        for frame in (0xB1, 0xB2, 0xB3, 0xB4, 0xB5):
            self.send_frame(frame, [], sleep_s=0.001)
            self.send_frame(frame, [self.MATRIX_TOUCH_REQUEST], sleep_s=0.001)

    def get_finger_pressures(self) -> List[float]:
        """Return one pressure number per finger, using the max of all sensors on that finger."""
        with self._lock:
            pressures = []
            for finger_index, normal in enumerate(self._normal_force):
                touch_sensors = self._touch_zones_for_finger(finger_index)
                candidates = [normal]
                candidates.extend(touch_sensors)
                candidates = [value for value in candidates if value is not None and value >= 0]
                pressures.append(max(candidates) if candidates else 0.0)
            return pressures

    def get_touch_pressures(self) -> List[float]:
        """Return 15 tactile zones, ordered thumb..little, proximal..distal."""
        with self._lock:
            return [
                value
                for finger_index in range(5)
                for value in self._touch_zones_for_finger(finger_index)
            ]

    def _touch_zones_for_finger(self, finger_index: int) -> List[float]:
        matrix = self._touch_matrix[finger_index]
        flat_matrix = [value for row in matrix for value in row if value >= 0]
        if flat_matrix:
            zones = []
            rows_per_zone = self.MATRIX_ROWS // self.TOUCH_ZONES_PER_FINGER
            for zone_index in range(self.TOUCH_ZONES_PER_FINGER):
                start = zone_index * rows_per_zone
                end = start + rows_per_zone
                zone_values = [
                    value
                    for row in matrix[start:end]
                    for value in row
                    if value >= 0
                ]
                zones.append(max(zone_values) if zone_values else 0.0)
            return zones

        summary = self._touch_pressure[finger_index]
        summary = summary if summary >= 0 else 0.0
        return [summary] * self.TOUCH_ZONES_PER_FINGER

    def request_joint_status(self):
        self.send_frame(self.JOINT_POSITION_RCO, [], sleep_s=0.001)
        self.send_frame(self.JOINT_POSITION2_RCO, [], sleep_s=0.001)

    def get_joint_status(self, wait_s=0.02) -> Optional[List[int]]:
        self.request_joint_status()
        if wait_s:
            time.sleep(wait_s)
        with self._lock:
            status = self._joint_status_1 + self._joint_status_2
        if len(status) == 10 and all(0 <= value <= 255 for value in status):
            return list(status)
        return None

    def get_last_command(self) -> List[int]:
        with self._lock:
            return list(self._last_command)

    def _receive_loop(self):
        while self.running:
            try:
                msg = self.bus.recv(timeout=0.2)
            except can.CanError:
                continue
            if msg is not None:
                self._process_response(msg)

    def _process_response(self, msg):
        if msg.arbitration_id != self.can_id or not msg.data:
            return

        frame_type = int(msg.data[0])
        response_data = [int(value) for value in msg.data[1:]]

        with self._lock:
            if frame_type == self.JOINT_POSITION_RCO:
                self._joint_status_1 = response_data[:6]
            elif frame_type == self.JOINT_POSITION2_RCO:
                self._joint_status_2 = response_data[:4]
            elif frame_type == self.HAND_NORMAL_FORCE:
                self._normal_force = [float(value) for value in response_data[:5]]
            elif frame_type == self.HAND_TANGENTIAL_FORCE:
                self._tangential_force = [float(value) for value in response_data[:5]]
            elif frame_type == self.HAND_TANGENTIAL_FORCE_DIR:
                self._tangential_force_dir = [float(value) for value in response_data[:5]]
            elif frame_type == self.HAND_APPROACH_INC:
                self._approach_inc = [float(value) for value in response_data[:5]]
            elif 0xB1 <= frame_type <= 0xB5 and len(response_data) >= 2:
                finger_index = frame_type - 0xB1
                if len(response_data) == 2:
                    self._touch_pressure[finger_index] = float(response_data[1])
                elif len(response_data) == 7:
                    row_index = self.MATRIX_ROW_MAP.get(response_data[0])
                    if row_index is not None:
                        self._touch_matrix[finger_index][row_index] = [
                            float(value) for value in response_data[1:7]
                        ]

    def shutdown(self):
        self.running = False
        if self.receive_thread.is_alive():
            self.receive_thread.join(timeout=1.0)
        if self.bus:
            self.bus.shutdown()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.shutdown()


def default_socketcan_interface() -> str:
    return "socketcan" if sys.platform.startswith("linux") else "pcan"
