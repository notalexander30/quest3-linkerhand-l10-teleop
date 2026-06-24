import unittest

from quest3_linkerhand_l10_teleop.teleop_core import (
    button_is_pressed,
    freeze_fingers_from_pressure,
    move_pose_toward,
    pose_to_bytes,
)


class TeleopCoreTest(unittest.TestCase):
    def test_button_bool_and_analog(self):
        buttons = {"X": True, "Y": False, "leftTrig": (0.7,), "leftGrip": (0.1,)}
        self.assertTrue(button_is_pressed(buttons, "X"))
        self.assertFalse(button_is_pressed(buttons, "Y"))
        self.assertTrue(button_is_pressed(buttons, "leftTrig", 0.55))
        self.assertFalse(button_is_pressed(buttons, "leftGrip", 0.55))

    def test_freezes_only_contacted_finger(self):
        current = [255, 205, 255, 255, 255, 255, 180, 179, 181, 41]
        measured = [240, 200, 120, 230, 230, 230, 170, 179, 181, 40]
        frozen = [False] * 5
        pressures = [10, 190, 20, 30, 40]

        next_pose, next_frozen = freeze_fingers_from_pressure(
            current,
            frozen,
            pressures,
            pressure_threshold=180,
            measured_position=measured,
        )

        self.assertEqual(next_frozen, [False, True, False, False, False])
        self.assertEqual(next_pose[2], 120)
        self.assertEqual(next_pose[6], 170)
        self.assertEqual(next_pose[3], 255)

    def test_move_pose_respects_frozen_finger(self):
        current = [255, 205, 255, 255, 255, 255, 180, 179, 181, 41]
        closed = [116, 208, 0, 0, 0, 0, 255, 255, 255, 0]
        moved = move_pose_toward(current, closed, [False, True, False, False, False], step=8)
        self.assertEqual(moved[2], 255)
        self.assertEqual(moved[6], 180)
        self.assertEqual(moved[3], 247)

    def test_pose_to_bytes_clamps(self):
        self.assertEqual(pose_to_bytes([-10, 10.4, 300]), [0, 10, 255])


if __name__ == "__main__":
    unittest.main()
