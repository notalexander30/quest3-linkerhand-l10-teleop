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
        hand._touch_pressure = [-1.0] * 5
        hand._touch_matrix = [
            [[-1.0] * hand.MATRIX_COLS for _ in range(hand.MATRIX_ROWS)]
            for _ in range(5)
        ]
        return hand

    def test_tracks_three_touch_pressure_zones_per_finger_from_matrix(self):
        hand = self.make_hand_without_bus()

        hand._process_response(FakeMessage(0x28, [0xB2, 0, 1, 2, 3, 4, 5, 6]))
        hand._process_response(FakeMessage(0x28, [0xB2, 64, 10, 11, 12, 13, 14, 15]))
        hand._process_response(FakeMessage(0x28, [0xB2, 128, 21, 22, 23, 24, 25, 26]))

        touch_pressures = hand.get_touch_pressures()
        self.assertEqual(len(touch_pressures), 15)
        self.assertEqual(touch_pressures[3:6], [6.0, 15.0, 26.0])
        self.assertEqual(hand.get_finger_pressures()[1], 26.0)

    def test_any_matrix_zone_can_cross_shared_pressure_threshold(self):
        hand = self.make_hand_without_bus()

        hand._process_response(FakeMessage(0x28, [0xB4, 128, 2, 3, 99, 4, 5, 6]))

        self.assertEqual(hand.get_finger_pressures()[3], 99.0)

    def test_summary_touch_fills_three_zones_when_matrix_is_unavailable(self):
        hand = self.make_hand_without_bus()

        hand._process_response(FakeMessage(0x28, [0xB1, 0, 42]))

        self.assertEqual(hand.get_touch_pressures()[0:3], [42.0, 42.0, 42.0])


if __name__ == "__main__":
    unittest.main()
