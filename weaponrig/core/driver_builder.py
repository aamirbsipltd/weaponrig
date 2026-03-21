"""Creates Blender drivers linking bones from a WeaponConfig."""

import bpy

from ..database.schema import BoneDef, DriverDef, WeaponConfig

# Map "property.axis" strings to bpy transform type constants.
_PROPERTY_TO_TRANSFORM = {
    "location.x": "LOC_X",
    "location.y": "LOC_Y",
    "location.z": "LOC_Z",
    "rotation_euler.x": "ROT_X",
    "rotation_euler.y": "ROT_Y",
    "rotation_euler.z": "ROT_Z",
    "scale.x": "SCALE_X",
    "scale.y": "SCALE_Y",
    "scale.z": "SCALE_Z",
}

_AXIS_INDEX = {"x": 0, "y": 1, "z": 2, "w": 3}


def apply_bone_drivers(arm_obj, bone_def):
    """Add drivers for a single bone. Returns count of drivers added."""
    if not bone_def.drivers:
        return 0
    pose_bone = arm_obj.pose.bones.get(bone_def.name)
    if pose_bone is None:
        return 0
    count = 0
    for driver_def in bone_def.drivers:
        _add_driver(pose_bone, driver_def, arm_obj, bone_def.parameters)
        count += 1
    return count


def apply_drivers(
    arm_obj: bpy.types.Object, config: WeaponConfig
) -> int:
    """Add drivers to pose bones as defined in *config*.

    Must be called while armature is in OBJECT mode.

    Returns the number of drivers added.
    """
    count = 0
    for bone_def in config.bones:
        if not bone_def.drivers:
            continue

        pose_bone = arm_obj.pose.bones.get(bone_def.name)
        if pose_bone is None:
            continue

        for driver_def in bone_def.drivers:
            _add_driver(pose_bone, driver_def, arm_obj, bone_def.parameters)
            count += 1

    return count


def _add_driver(
    pose_bone: bpy.types.PoseBone,
    driver_def: DriverDef,
    arm_obj: bpy.types.Object,
    parameters: dict,
) -> None:
    """Create a single driver on *pose_bone* from *driver_def*."""
    data_path, axis_index = _parse_property_path(driver_def.driven_property)

    fcurve = pose_bone.driver_add(data_path, axis_index)
    driver = fcurve.driver
    driver.type = "SCRIPTED"

    # -- Add the source variable ----------------------------------------
    var = driver.variables.new()
    var.name = "var"
    var.type = "TRANSFORMS"
    target = var.targets[0]
    target.id = arm_obj
    target.bone_target = driver_def.driver_bone
    target.transform_type = _property_to_transform(driver_def.driver_property)
    target.transform_space = "LOCAL_SPACE"

    # -- Expression vs. cam curve mode ----------------------------------
    if driver_def.cam_curve_keyframes:
        _apply_cam_curve(fcurve, driver, driver_def, parameters)
    else:
        driver.expression = driver_def.expression or "var"


def _apply_cam_curve(
    fcurve,
    driver,
    driver_def: DriverDef,
    parameters: dict,
) -> None:
    """Replace simple expression with piecewise keyframe curve.

    Cam curve keyframes are stored as normalized percentages.
    We convert to absolute values using bone parameters.
    """
    # Use pass-through expression — the f-curve keyframes do the mapping
    driver.expression = "var"

    # Get absolute scale factors from parameters
    # For bolt rotation driven by carrier travel:
    #   X axis = carrier travel in meters (driver variable value)
    #   Y axis = bolt rotation in radians (driven property value)
    carrier_travel = parameters.get("carrier_travel_m")
    rotation_deg = parameters.get("rotation_degrees")

    # If we don't have parameters to scale, use raw percentages
    if carrier_travel is None:
        carrier_travel = 1.0
    if rotation_deg is None:
        rotation_deg = 1.0

    import math
    rotation_rad = math.radians(rotation_deg)

    # Sort keyframes by input value
    sorted_kfs = sorted(
        driver_def.cam_curve_keyframes, key=lambda kf: kf.carrier_travel_pct
    )

    # Remove any default keyframe points on the fcurve
    while fcurve.keyframe_points:
        fcurve.keyframe_points.remove(fcurve.keyframe_points[0])

    # Insert cam curve keyframes
    for kf in sorted_kfs:
        x_val = kf.carrier_travel_pct * carrier_travel
        y_val = kf.bolt_rotation_pct * rotation_rad
        point = fcurve.keyframe_points.insert(x_val, y_val)
        point.interpolation = "LINEAR"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_property_path(prop: str) -> tuple[str, int]:
    """Convert 'rotation_euler.y' -> ('rotation_euler', 1)."""
    parts = prop.rsplit(".", 1)
    if len(parts) != 2 or parts[1] not in _AXIS_INDEX:
        raise ValueError(f"Cannot parse property path: {prop!r}")
    return parts[0], _AXIS_INDEX[parts[1]]


def _property_to_transform(prop: str) -> str:
    """Convert 'location.y' -> 'LOC_Y' for bpy transform type."""
    result = _PROPERTY_TO_TRANSFORM.get(prop)
    if result is None:
        raise ValueError(f"Unknown driver property: {prop!r}")
    return result
