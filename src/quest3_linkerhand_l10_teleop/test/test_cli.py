import importlib
import sys
import types
import unittest


def fake_module(name, **attrs):
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    return module


class FakeReader:
    def __init__(self, buttons):
        self.buttons = buttons

    def get_transformations_and_buttons(self):
        return {}, self.buttons


class FakeHand:
    def __init__(self):
        self.commands = []

    def request_pressure(self):
        pass

    def get_finger_pressures(self):
        return [0.0] * 5

    def get_joint_status(self, wait_s=0.01):
        return None

    def set_joint_positions(self, command):
        self.commands.append(command)


class CliTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.modules["quest3_linkerhand_l10_teleop.l10_can"] = fake_module(
            "quest3_linkerhand_l10_teleop.l10_can",
            L10CanHand=object,
            default_socketcan_interface=lambda: "socketcan",
        )
        sys.modules["quest3_linkerhand_l10_teleop.oculus_reader"] = fake_module(
            "quest3_linkerhand_l10_teleop.oculus_reader",
            OculusReader=object,
        )
        cls.cli = importlib.import_module("quest3_linkerhand_l10_teleop.cli")

    def setUp(self):
        self.original_monotonic = self.cli.time.monotonic
        self.now = 10.0
        self.cli.time.monotonic = lambda: self.now

    def tearDown(self):
        self.cli.time.monotonic = self.original_monotonic

    def make_teleop(self, buttons):
        args = self.cli.build_parser().parse_args([])
        teleop = self.cli.Quest3L10Teleop(args)
        teleop.reader = FakeReader(buttons)
        teleop.hand = FakeHand()
        return teleop

    def test_default_pickup_is_y_for_one_second(self):
        args = self.cli.build_parser().parse_args([])
        teleop = self.make_teleop({})

        self.assertEqual(args.pickup_mode_button, "Y")
        self.assertEqual(args.pickup_mode_duration_s, 1.0)
        self.assertEqual(args.thumb_pitch_speed_scale, 0.8)
        self.assertEqual(args.pickup_thumb_pitch_speed_scale, 1.0)
        self.assertAlmostEqual(teleop.normal_joint_steps[1], 6.4)
        self.assertAlmostEqual(teleop.pickup_joint_steps[1], 8.0)

    def test_pickup_mode_expires_back_to_normal(self):
        teleop = self.make_teleop({"leftGrip": (1.0,), "leftTrig": (0.0,), "Y": True})

        teleop.step()
        self.assertEqual(teleop.last_mode, "pickup")
        self.assertEqual(teleop.pickup_mode_until, 11.0)

        self.now = 11.1
        teleop.reader.buttons = {"leftGrip": (1.0,), "leftTrig": (0.0,), "Y": False}
        teleop.step()
        self.assertEqual(teleop.last_mode, "normal")


if __name__ == "__main__":
    unittest.main()
