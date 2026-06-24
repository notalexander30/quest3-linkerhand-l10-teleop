import os
import sys
import threading

import numpy as np
from ppadb.client import Client as AdbClient

from .buttons_parser import parse_buttons
from .fps_counter import FPSCounter


def eprint(*args, **kwargs):
    red = "\033[1;31m"
    reset = "\033[0;0m"
    sys.stderr.write(red)
    print(*args, file=sys.stderr, **kwargs)
    sys.stderr.write(reset)


class OculusReader:
    """Read Quest controller poses and buttons from the teleop APK logcat stream."""

    def __init__(
        self,
        ip_address=None,
        port=5555,
        apk_name="com.rail.oculus.teleop",
        apk_path=None,
        print_fps=False,
        run=True,
    ):
        self.running = False
        self.last_transforms = {}
        self.last_buttons = {}
        self._lock = threading.Lock()
        self.tag = "wE9ryARX"
        self.ip_address = ip_address or None
        self.port = port
        self.apk_name = apk_name
        self.apk_path = apk_path or None
        self.print_fps = print_fps
        self.thread = None
        if self.print_fps:
            self.fps_counter = FPSCounter()
        self.device = self.get_device()
        self.install(verbose=False)
        if run:
            self.run()

    def __del__(self):
        self.stop()

    def run(self):
        self.running = True
        self.device.shell(
            'am start -n "com.rail.oculus.teleop/com.rail.oculus.teleop.MainActivity" '
            "-a android.intent.action.MAIN -c android.intent.category.LAUNCHER"
        )
        self.thread = threading.Thread(
            target=self.device.shell,
            args=("logcat -T 0", self.read_logcat_by_line),
        )
        self.thread.daemon = True
        self.thread.start()

    def stop(self):
        self.running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1.0)

    def get_network_device(self, client, retry=0):
        try:
            client.remote_connect(self.ip_address, self.port)
        except RuntimeError:
            os.system("adb devices")
            client.remote_connect(self.ip_address, self.port)
        device = client.device(f"{self.ip_address}:{self.port}")

        if device is None:
            if retry == 1:
                os.system(f"adb tcpip {self.port}")
            if retry == 2:
                raise RuntimeError(
                    "Quest device not found over Wi-Fi. Verify adb connect "
                    f"{self.ip_address}:{self.port} and adb shell ip route."
                )
            return self.get_network_device(client=client, retry=retry + 1)
        return device

    def get_usb_device(self, client):
        try:
            devices = client.devices()
        except RuntimeError:
            os.system("adb devices")
            devices = client.devices()
        for device in devices:
            if device.serial.count(".") < 3:
                return device
        raise RuntimeError(
            "Quest device not found over USB. Run `adb devices` and accept the "
            "USB debugging prompt inside the headset."
        )

    def get_device(self):
        client = AdbClient(host="127.0.0.1", port=5037)
        if self.ip_address:
            return self.get_network_device(client)
        return self.get_usb_device(client)

    def install(self, verbose=True, reinstall=False):
        try:
            installed = self.device.is_installed(self.apk_name)
            if installed and not reinstall:
                if verbose:
                    print("Quest teleop APK is already installed.")
                return

            apk_path = self.apk_path
            if not apk_path:
                apk_path = os.path.join(
                    os.path.dirname(os.path.realpath(__file__)),
                    "APK",
                    "teleop-debug.apk",
                )

            if not os.path.exists(apk_path):
                raise RuntimeError(
                    "Quest teleop APK is not installed and no APK file was found. "
                    "Install the Agilex/Rail teleop-debug.apk manually or pass "
                    "`--apk-path /absolute/path/to/teleop-debug.apk`."
                )

            success = self.device.install(apk_path, test=True, reinstall=reinstall)
            installed = self.device.is_installed(self.apk_name)
            if installed and success:
                print("Quest teleop APK installed successfully.")
            else:
                raise RuntimeError("Quest teleop APK install failed.")
        except RuntimeError:
            eprint("Device is visible but could not be accessed or prepared.")
            eprint("Run `adb devices` and accept the USB debugging prompt in Quest.")
            raise

    def uninstall(self, verbose=True):
        installed = self.device.is_installed(self.apk_name)
        if installed:
            self.device.uninstall(self.apk_name)
        elif verbose:
            print("Quest teleop APK is not installed.")

    @staticmethod
    def process_data(string):
        try:
            transforms_string, buttons_string = string.split("&")
        except ValueError:
            return None, None
        split_transform_strings = transforms_string.split("|")
        transforms = {}
        for pair_string in split_transform_strings:
            transform = np.empty((4, 4))
            pair = pair_string.split(":")
            if len(pair) != 2:
                continue
            left_right_char = pair[0]
            values = pair[1].split(" ")
            c = 0
            r = 0
            count = 0
            for value in values:
                if not value:
                    continue
                transform[r][c] = float(value)
                c += 1
                if c >= 4:
                    c = 0
                    r += 1
                count += 1
            if count == 16:
                transforms[left_right_char] = transform
        buttons = parse_buttons(buttons_string)
        return transforms, buttons

    def extract_data(self, line):
        if self.tag not in line:
            return ""
        try:
            return line.split(self.tag + ": ")[1]
        except ValueError:
            return ""

    def get_transformations_and_buttons(self):
        with self._lock:
            return self.last_transforms, self.last_buttons

    def read_logcat_by_line(self, connection):
        file_obj = connection.socket.makefile()
        while self.running:
            try:
                line = file_obj.readline().strip()
                data = self.extract_data(line)
                if data:
                    transforms, buttons = OculusReader.process_data(data)
                    with self._lock:
                        self.last_transforms, self.last_buttons = transforms, buttons
                    if self.print_fps:
                        self.fps_counter.get_and_print_fps()
            except UnicodeDecodeError:
                pass
        file_obj.close()
        connection.close()
