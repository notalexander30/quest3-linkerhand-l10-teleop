import threading
import unittest

from quest3_linkerhand_l10_teleop.l10_can import L10CanHand


class FakeMessage:
    def __init__(self, arbitration_id, data):
        self.arbitration_id = arbitration_id
        self.data = bytearray(data)


class L10CanHandTest(unittest.TestCase):
    def make_hand_without_bus(self):
        hand = L10CanHand.__new__(L10CanHand)
        hand.can_id = 0x28
        hand._lock = threading.Lock()
        hand._normal_force = [0.0] * 5
        hand._touch_pressure = [[-1.0] * hand.TOUCH_SENSOR_COUNT_PER_FINGER for _ in range(5)]
        return hand

    def test_tracks_three_touch_pressure_sensors_per_finger(self):
        hand = self.make_hand_without_bus()

        hand._process_response(FakeMessage(0x28, [0xB2, 0, 11, 12, 13]))

        touch_pressures = hand.get_touch_pressures()
        self.assertEqual(len(touch_pressures), 15)
        self.assertEqual(touch_pressures[3:6], [11.0, 12.0, 13.0])
        self.assertEqual(hand.get_finger_pressures()[1], 13.0)

    def test_any_touch_sensor_can_cross_shared_pressure_threshold(self):
        hand = self.make_hand_without_bus()

        hand._process_response(FakeMessage(0x28, [0xB4, 0, 2, 99, 3]))

        self.assertEqual(hand.get_finger_pressures()[3], 99.0)


if __name__ == "__main__":
    unittest.main()
