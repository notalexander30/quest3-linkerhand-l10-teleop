# Quest 3 to LinkerHand L10 Teleop

Python-only teleoperation for a LinkerHand L10 using the Meta Quest 3 left controller and CAN communication.

## Default Controls

Use the left Quest controller:

- Hold the left grip/side trigger, `leftGrip`, to enable teleop.
- Release `leftGrip` to stop sending new hand commands.
- Squeeze the left index/top trigger, `leftTrig`, to close the hand proportionally.
- Release `leftTrig` to open the hand proportionally.
- Press `Y` once to enter pickup/pinch mode. Press `Y` again to return to normal bend-only mode.
- Pressure sensing still runs while closing. Matrix touch data is exposed as a flat 15-sensor list using the same pressure threshold. When any sensor on a finger reaches it, that finger freezes while the other fingers keep moving.
- Thumb pitch joint index `0` moves at 75% of the normal software step speed by default. In pickup mode, squeezing `leftTrig` closes the pitch joints while keeping side/abduction joints fixed.

Default poses:

- Open pose: `255,255,255,255,255,255,255,255,255,255`
- Normal close pose: `0,255,0,0,0,0,255,255,255,255`
- Pickup/pinch open pose: `255,0,255,255,255,255,255,255,255,255`
- Pickup/pinch close pose: `0,0,0,0,0,0,255,255,255,255`

The close poses avoid side/rotation motions by keeping those joints at `255`.

Pressure sensor order:

- `1..3`: thumb
- `4..6`: index
- `7..9`: middle
- `10..12`: ring
- `13..15`: little

The left L10 CAN ID is `0x28`. Right hand mode is available with `--hand-type right`, using CAN ID `0x27`.

## Cable Setup

LinkerHand L10:

- LinkerHand L10 CAN cable to USB-to-CAN adapter.
- USB-to-CAN adapter to the Ubuntu computer.
- Hand power supply connected as required by your LinkerHand hardware.
- CAN interface should normally appear as `can0`.

Quest 3:

- Quest 3 to computer using a USB-C data/signal cable.
- The cable must support data, not only charging.
- Keep the Quest awake and controllers awake.
- Accept the USB debugging popup inside the headset.

## New Computer Setup

```bash
sudo apt update
sudo apt install -y git python3-pip python3-venv android-tools-adb can-utils

git clone https://github.com/notalexander30/quest3-linkerhand-l10-teleop.git
cd quest3-linkerhand-l10-teleop

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

Install the Quest teleop APK once:

```bash
git clone https://github.com/agilexrobotics/questVR_ws.git ~/questVR_ws
adb install ~/questVR_ws/src/oculus_reader/APK/teleop-debug.apk
```

If the APK is already installed, skip that install step.

## Already-Cloned Computer Startup

```bash
cd ~/quest3-linkerhand-l10-teleop
source .venv/bin/activate
```

If `.venv` does not exist yet:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

## Terminal 1: Main Teleop

Bring up CAN:

```bash
sudo ip link set can0 down || true
sudo ip link set can0 type can bitrate 1000000
sudo ip link set can0 up
ip -details link show can0
```

Expected CAN output should include:

```text
can0
state ERROR-ACTIVE
bitrate 1000000
```

Start teleop:

```bash
quest3-l10-teleop --can-channel can0
```

Expected startup output:

```text
Starting Quest3 -> left LinkerHand L10 teleop on can0
Hold leftGrip to enable teleop; use leftTrig as the analog open/close trigger.
Press Y to toggle pickup mode; press it again for normal bend-only grip mode.
Sent startup open pose: [255, 255, 255, 255, 255, 255, 255, 255, 255, 255]
```

## Terminal 2: Quest Debug

Use this terminal only if the main program says `Waiting for Quest button data`.

Check Quest connection:

```bash
adb devices
```

Good output:

```text
List of devices attached
XXXXXXXX    device
```

Check APK installed:

```bash
adb shell pm list packages | grep oculus.teleop
```

Expected:

```text
package:com.rail.oculus.teleop
```

Restart the Quest APK:

```bash
adb shell am force-stop com.rail.oculus.teleop
adb shell am start -n com.rail.oculus.teleop/com.rail.oculus.teleop.MainActivity
```

Check controller data:

```bash
adb logcat -c
adb logcat | grep wE9ryARX
```

Put on the Quest, keep it awake, and press controller buttons. Lines should appear when the APK is streaming data.

## Useful Run Options

Change pressure threshold:

```bash
quest3-l10-teleop --can-channel can0 --pressure-threshold 170
```

Use right hand:

```bash
quest3-l10-teleop --can-channel can0 --hand-type right
```

Use a different teleop enable trigger:

```bash
quest3-l10-teleop --can-channel can0 --teleop-button LG --button-threshold 0.55
```

Use a different analog close trigger:

```bash
quest3-l10-teleop --can-channel can0 --close-axis rightTrig
```

Use a different pickup mode button:

```bash
quest3-l10-teleop --can-channel can0 --pickup-mode-button X
```

Override poses:

```bash
quest3-l10-teleop \
  --can-channel can0 \
  --open-position 255,255,255,255,255,255,255,255,255,255 \
  --closed-position 0,255,0,0,0,0,255,255,255,255 \
  --pickup-open-position 255,0,255,255,255,255,255,255,255,255 \
  --pickup-position 0,0,0,0,0,0,255,255,255,255
```

Optional speed/torque:

```bash
quest3-l10-teleop --can-channel can0 --speed 120,120,120,120,120
quest3-l10-teleop --can-channel can0 --torque 180,180,180,180,180
quest3-l10-teleop --can-channel can0 --thumb-pitch-speed-scale 0.75
quest3-l10-teleop --can-channel can0 --pose-deadband 2
```

Disable startup open command:

```bash
quest3-l10-teleop --can-channel can0 --no-open-on-start
```

## Common Problems

`externally managed environment`

Use the virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

`Waiting for Quest button data`

Check:

```bash
adb devices
adb shell pm list packages | grep oculus.teleop
adb shell am start -n com.rail.oculus.teleop/com.rail.oculus.teleop.MainActivity
adb logcat | grep wE9ryARX
```

`adb devices` says `no permissions`

```bash
adb kill-server

sudo tee /etc/udev/rules.d/51-android-quest.rules >/dev/null <<'EOF'
SUBSYSTEM=="usb", ATTR{idVendor}=="2833", MODE="0666", GROUP="plugdev", TAG+="uaccess"
SUBSYSTEM=="usb", ATTR{idVendor}=="18d1", MODE="0666", GROUP="plugdev", TAG+="uaccess"
EOF

sudo chmod a+r /etc/udev/rules.d/51-android-quest.rules
sudo udevadm control --reload-rules
sudo udevadm trigger
sudo usermod -aG plugdev $USER
```

Then unplug and replug the Quest USB-C cable and accept USB debugging.

CAN does not work:

```bash
ip -details link show can0
sudo ip link set can0 down || true
sudo ip link set can0 type can bitrate 1000000
sudo ip link set can0 up
candump can0
```

## Direct Script

After `pip install -e .`, the preferred command is `quest3-l10-teleop`. You can also run the wrapper directly:

```bash
PYTHONPATH=src/quest3_linkerhand_l10_teleop/src \
python3 src/quest3_linkerhand_l10_teleop/scripts/quest3_l10_teleop.py --can-channel can0
```
