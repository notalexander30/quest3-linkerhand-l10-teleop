# Quest 3 to LinkerHand L10 Teleop

Python-only teleoperation for a LinkerHand L10 using the left Meta Quest 3 controller and CAN communication.

Default controls:

- Hold `X` on the left Quest controller to enable teleop.
- Release `X` to stop sending new hand commands.
- Press `Y` while holding `X` to toggle open/close.
- While closing, each finger stops when its pressure crosses the threshold. Other fingers keep moving, so the hand can shape itself around an object.
- Toggle open again to clear all finger pressure freezes and release.

The left L10 CAN ID is `0x28`. Right hand mode is available with `--hand-type right`, using CAN ID `0x27`.

## Install

Ubuntu robot computer:

```bash
sudo apt update
sudo apt install -y android-tools-adb can-utils python3-pip

git clone https://github.com/notalexander30/quest3-linkerhand-l10-teleop.git
cd quest3-linkerhand-l10-teleop
python3 -m pip install -e .
```

Install the Quest teleop APK from Agilex's Quest reference repo:

```bash
git clone https://github.com/agilexrobotics/questVR_ws.git ~/questVR_ws
adb install ~/questVR_ws/src/oculus_reader/APK/teleop-debug.apk
```

If the APK is not installed yet, you can pass it at run time with `--apk-path`.

## Bring Up CAN

For a typical SocketCAN USB-CAN adapter on `can0` at 1 Mbps:

```bash
sudo ip link set can0 down || true
sudo ip link set can0 type can bitrate 1000000
sudo ip link set can0 up
ip -details link show can0
```

Optional bus check:

```bash
candump can0
```

## Connect Quest 3

USB mode:

```bash
adb devices
```

Wear the Quest and accept the USB debugging prompt. `adb devices` should show one authorized device.

Wi-Fi mode:

```bash
adb tcpip 5555
adb shell ip route
adb connect <QUEST_IP>:5555
```

## Run

USB Quest connection:

```bash
quest3-l10-teleop --can-channel can0
```

Wi-Fi Quest connection:

```bash
quest3-l10-teleop --can-channel can0 --quest-ip <QUEST_IP>
```

If the APK is not installed yet:

```bash
quest3-l10-teleop \
  --can-channel can0 \
  --apk-path /home/$USER/questVR_ws/src/oculus_reader/APK/teleop-debug.apk
```

## Button Mapping

Default face buttons:

```bash
quest3-l10-teleop --teleop-button X --open-close-button Y
```

Use side grip as enable and index trigger as open/close:

```bash
quest3-l10-teleop --teleop-button LG --open-close-button LTr
```

Use analog grip/trigger values instead:

```bash
quest3-l10-teleop --teleop-button leftGrip --open-close-button leftTrig --button-threshold 0.55
```

## Tuning

Pressure threshold:

```bash
quest3-l10-teleop --pressure-threshold 170
```

Open/close poses:

```bash
quest3-l10-teleop \
  --open-position 255,205,255,255,255,255,180,179,181,41 \
  --closed-position 116,208,0,0,0,0,255,255,255,0
```

Optional speed/torque:

```bash
quest3-l10-teleop --speed 120,120,120,120,120 --torque 180,180,180,180,180
```

## Direct Script

After `pip install -e .`, the preferred command is `quest3-l10-teleop`. You can also run the wrapper directly:

```bash
PYTHONPATH=src/quest3_linkerhand_l10_teleop/src \
python3 src/quest3_linkerhand_l10_teleop/scripts/quest3_l10_teleop.py --can-channel can0
```
