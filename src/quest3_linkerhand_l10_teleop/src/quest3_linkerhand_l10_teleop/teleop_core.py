from typing import Dict, Iterable, List, Sequence


FINGER_NAMES = ["thumb", "index", "middle", "ring", "little"]
FINGER_JOINTS = [
    [0, 1, 9],
    [2, 6],
    [3, 7],
    [4, 8],
    [5],
]


def clamp_byte(value) -> int:
    return max(0, min(255, int(round(float(value)))))


def button_is_pressed(buttons: Dict, name: str, analog_threshold: float = 0.55) -> bool:
    return button_value(buttons, name) >= analog_threshold


def button_value(buttons: Dict, name: str) -> float:
    value = buttons.get(name)
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return max(0.0, min(1.0, float(value)))
    if isinstance(value, (tuple, list)) and value:
        return max(0.0, min(1.0, float(value[0])))
    return 0.0


def interpolate_pose(open_pose: Sequence[float], closed_pose: Sequence[float], close_amount: float) -> List[float]:
    close_amount = max(0.0, min(1.0, float(close_amount)))
    return [
        float(open_value) + (float(closed_value) - float(open_value)) * close_amount
        for open_value, closed_value in zip(open_pose, closed_pose)
    ]


def move_scalar_toward(current: float, target: float, step: float) -> float:
    if abs(target - current) <= step:
        return target
    if target > current:
        return current + step
    return current - step


def move_pose_toward(
    current: Sequence[float],
    target: Sequence[float],
    frozen_fingers: Sequence[bool],
    step: float,
) -> List[float]:
    frozen_joints = set()
    for frozen, joints in zip(frozen_fingers, FINGER_JOINTS):
        if frozen:
            frozen_joints.update(joints)

    next_pose = []
    for index, (current_value, target_value) in enumerate(zip(current, target)):
        if index in frozen_joints:
            next_pose.append(float(current_value))
        else:
            next_pose.append(move_scalar_toward(float(current_value), float(target_value), float(step)))
    return next_pose


def freeze_fingers_from_pressure(
    current: Sequence[float],
    frozen_fingers: Sequence[bool],
    pressures: Iterable[float],
    pressure_threshold: float,
    measured_position: Sequence[float] = None,
):
    next_position = list(float(value) for value in current)
    next_frozen = list(bool(value) for value in frozen_fingers)
    measured_position = measured_position if measured_position and len(measured_position) == 10 else None

    for finger_index, pressure in enumerate(pressures):
        if finger_index >= len(FINGER_JOINTS):
            break
        if next_frozen[finger_index] or float(pressure) < float(pressure_threshold):
            continue
        next_frozen[finger_index] = True
        if measured_position:
            for joint_index in FINGER_JOINTS[finger_index]:
                next_position[joint_index] = float(measured_position[joint_index])
    return next_position, next_frozen


def pose_to_bytes(pose: Sequence[float]) -> List[int]:
    return [clamp_byte(value) for value in pose]
