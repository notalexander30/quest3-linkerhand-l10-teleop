import unittest

from quest3_linkerhand_l10_teleop.teleop_core import (
    build_joint_steps,
    button_is_pressed,
    button_value,
    freeze_fingers_from_pressure,
    interpolate_pose,
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
        self.assertEqual(button_value(buttons, "X"), 1.0)
        self.assertEqual(button_value(buttons, "leftTrig"), 0.7)

    def test_freezes_only_contacted_finger(self):
        current = [255] * 10
        measured = [240, 255, 120, 230, 230, 230, 255, 255, 255, 255]
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
        self.assertEqual(next_pose[6], 255)
        self.assertEqual(next_pose[3], 255)

    def test_move_pose_respects_frozen_finger(self):
        current = [255] * 10
        closed = [0, 255, 0, 0, 0, 0, 255, 255, 255, 255]
        moved = move_pose_toward(current, closed, [False, True, False, False, False], step=8)
        self.assertEqual(moved[2], 255)
        self.assertEqual(moved[6], 255)
        self.assertEqual(moved[3], 247)

    def test_thumb_pitch_step_can_be_eighty_percent_speed(self):
        current = [255] * 10
        target = [0] * 10
        steps = build_joint_steps(8)
        moved = move_pose_toward(current, target, [False] * 5, step=steps)

        self.assertEqual(moved[0], 247)
        self.assertAlmostEqual(moved[1], 248.6)
        self.assertEqual(moved[2], 247)

    def test_interpolate_pose_uses_trigger_amount(self):
        open_pose = [255] * 10
        closed = [0, 255, 0, 0, 0, 0, 255, 255, 255, 255]
        halfway = interpolate_pose(open_pose, closed, 0.5)
        self.assertEqual(pose_to_bytes(halfway), [128, 255, 128, 128, 128, 128, 255, 255, 255, 255])

    def test_pose_to_bytes_clamps(self):
        self.assertEqual(pose_to_bytes([-10, 10.4, 300]), [0, 10, 255])


if __name__ == "__main__":
    unittest.main()
