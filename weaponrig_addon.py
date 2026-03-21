"""WeaponRig — Guided weapon rigging assistant for FPS games. Single-file addon."""

bl_info = {
    "name": "WeaponRig",
    "author": "Aamir Farrukh",
    "version": (0, 2, 0),
    "blender": (4, 0, 0),
    "location": "View3D > Sidebar > WeaponRig",
    "description": "Guided weapon rigging assistant for FPS games",
    "category": "Rigging",
}

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import bpy
from bpy_extras.io_utils import ImportHelper
from mathutils import Vector


# ===================================================================
# CONFIG DATABASE (embedded)
# ===================================================================

WEAPON_CONFIGS = {
    "ar15_di": {
        "schema_version": "1.0",
        "operating_system": "ar15_direct_impingement",
        "display_name": "AR-15 Direct Impingement",
        "description": "Stoner gas system with rotating bolt",
        "fire_modes": ["semi", "auto", "burst_3"],
        "cyclic_rate_rpm": {"semi": None, "auto": 700, "burst_3": 900},
        "bones": [
            {
                "name": "Weapon Root",
                "parent": None,
                "presence": "required",
                "movement_type": "static",
                "description": "Lower receiver - root of all weapon bones",
                "placement": "Place at the base of the lower receiver, where the grip meets the frame",
            },
            {
                "name": "Upper Receiver",
                "parent": "Weapon Root",
                "presence": "required",
                "movement_type": "static",
                "description": "Upper receiver - static relative to lower",
                "placement": "Place at the front takedown pin, where upper meets lower receiver",
            },
            {
                "name": "Bolt Carrier",
                "parent": "Upper Receiver",
                "presence": "required",
                "movement_type": "translate",
                "axis": "Y",
                "constraints": [
                    {
                        "type": "LIMIT_LOCATION",
                        "min_x": 0.0, "max_x": 0.0, "use_min_x": True, "use_max_x": True,
                        "min_y": -0.095, "max_y": 0.0, "use_min_y": True, "use_max_y": True,
                        "min_z": 0.0, "max_z": 0.0, "use_min_z": True, "use_max_z": True,
                        "owner_space": "LOCAL",
                    }
                ],
                "parameters": {
                    "carrier_travel_m": 0.095,
                    "dwell_before_unlock_m": 0.003,
                    "carrier_mass_kg": 0.297,
                    "buffer_spring_rate_n_per_m": 3500,
                },
                "description": "Bolt carrier group slides rearward under gas pressure, compresses buffer spring, then returns forward to chamber next round",
                "placement": "Place at the rear of the bolt carrier group, centered in the upper receiver channel",
            },
            {
                "name": "Bolt",
                "parent": "Bolt Carrier",
                "presence": "required",
                "movement_type": "rotate",
                "axis": "Y",
                "constraints": [
                    {
                        "type": "LIMIT_ROTATION",
                        "min_y": 0.0,
                        "max_y": 0.361,
                        "use_limit_x": True,
                        "use_limit_y": True,
                        "use_limit_z": True,
                        "owner_space": "LOCAL",
                    }
                ],
                "drivers": [
                    {
                        "driven_property": "rotation_euler.y",
                        "driver_bone": "Bolt Carrier",
                        "driver_property": "location.y",
                        "expression": "var * -3.8",
                        "description": "Bolt rotates 20.7 degrees as carrier travels back. Cam pin rides in carrier track: dwell for first 3mm, then linear rotation over next 5.4mm, then dwell",
                        "cam_curve_keyframes": [
                            {"carrier_travel_pct": 0.0, "bolt_rotation_pct": 0.0},
                            {"carrier_travel_pct": 0.032, "bolt_rotation_pct": 0.0},
                            {"carrier_travel_pct": 0.089, "bolt_rotation_pct": 1.0},
                            {"carrier_travel_pct": 1.0, "bolt_rotation_pct": 1.0},
                        ],
                    }
                ],
                "parameters": {
                    "rotation_degrees": 20.7,
                    "lug_count": 7,
                },
                "description": "Bolt head rotates to lock/unlock from barrel extension. 7 lugs engage at 20.7 degrees rotation",
                "placement": "Place at the bolt face, centered on the bore axis",
            },
            {
                "name": "Trigger",
                "parent": "Weapon Root",
                "presence": "required",
                "movement_type": "rotate",
                "axis": "X",
                "constraints": [
                    {
                        "type": "LIMIT_ROTATION",
                        "min_x": -0.262,
                        "max_x": 0.0,
                        "use_limit_x": True,
                        "use_limit_y": True,
                        "use_limit_z": True,
                        "owner_space": "LOCAL",
                    }
                ],
                "parameters": {
                    "rotation_degrees": 15.0,
                },
                "description": "Trigger rotates ~15 degrees around the trigger pin. Releases hammer when pulled",
                "placement": "Place at the trigger pin hole center in the lower receiver",
            },
            {
                "name": "Selector",
                "parent": "Weapon Root",
                "presence": "expected",
                "movement_type": "rotate",
                "axis": "Z",
                "constraints": [
                    {
                        "type": "LIMIT_ROTATION",
                        "use_limit_x": True,
                        "use_limit_y": True,
                        "use_limit_z": True,
                        "owner_space": "LOCAL",
                    }
                ],
                "parameters": {
                    "positions": [
                        {"name": "safe", "angle_degrees": 0},
                        {"name": "semi", "angle_degrees": 90},
                        {"name": "auto", "angle_degrees": 180},
                    ],
                },
                "description": "Fire selector switch. Rotates between Safe (0), Semi (90), and Auto (180) positions",
                "placement": "Place at the selector lever pivot on the left side of the lower receiver, above the grip",
            },
            {
                "name": "Charging Handle",
                "parent": "Upper Receiver",
                "presence": "expected",
                "movement_type": "translate",
                "axis": "Y",
                "constraints": [
                    {
                        "type": "LIMIT_LOCATION",
                        "min_x": 0.0, "max_x": 0.0, "use_min_x": True, "use_max_x": True,
                        "min_y": -0.076, "max_y": 0.0, "use_min_y": True, "use_max_y": True,
                        "min_z": 0.0, "max_z": 0.0, "use_min_z": True, "use_max_z": True,
                        "owner_space": "LOCAL",
                    }
                ],
                "description": "Slides rearward 76mm to manually cycle the bolt carrier",
                "placement": "Place at the rear of the upper receiver, centered on top where the charging handle sits",
            },
            {
                "name": "Magazine",
                "parent": None,
                "presence": "required",
                "movement_type": "translate",
                "axis": "Z",
                "description": "Detachable box magazine. Unparented when released for reload animation",
                "placement": "Place at the top of the magazine, where it meets the magazine well",
            },
            {
                "name": "Magazine Release",
                "parent": "Weapon Root",
                "presence": "expected",
                "movement_type": "translate",
                "axis": "X",
                "constraints": [
                    {
                        "type": "LIMIT_LOCATION",
                        "min_x": 0.0, "max_x": 0.003, "use_min_x": True, "use_max_x": True,
                        "min_y": 0.0, "max_y": 0.0, "use_min_y": True, "use_max_y": True,
                        "min_z": 0.0, "max_z": 0.0, "use_min_z": True, "use_max_z": True,
                        "owner_space": "LOCAL",
                    }
                ],
                "description": "Button that releases magazine catch. Pressed inward ~3mm",
                "placement": "Place at the magazine release button on the right side of the lower receiver",
            },
            {
                "name": "Dust Cover",
                "parent": "Upper Receiver",
                "presence": "optional",
                "movement_type": "rotate",
                "axis": "X",
                "constraints": [
                    {
                        "type": "LIMIT_ROTATION",
                        "min_x": 0.0,
                        "max_x": 1.309,
                        "use_limit_x": True,
                        "use_limit_y": True,
                        "use_limit_z": True,
                        "owner_space": "LOCAL",
                    }
                ],
                "parameters": {
                    "rotation_degrees": 75.0,
                },
                "description": "Ejection port dust cover. Springs open ~75 degrees when bolt cycles",
                "placement": "Place at the dust cover hinge pin on the right side of the upper receiver",
            },
            {
                "name": "Forward Assist",
                "parent": "Upper Receiver",
                "presence": "optional",
                "movement_type": "translate",
                "axis": "Y",
                "constraints": [
                    {
                        "type": "LIMIT_LOCATION",
                        "min_x": 0.0, "max_x": 0.0, "use_min_x": True, "use_max_x": True,
                        "min_y": -0.006, "max_y": 0.0, "use_min_y": True, "use_max_y": True,
                        "min_z": 0.0, "max_z": 0.0, "use_min_z": True, "use_max_z": True,
                        "owner_space": "LOCAL",
                    }
                ],
                "description": "Pushes bolt carrier forward to ensure full lockup",
                "placement": "Place at the forward assist button on the right side of the upper receiver",
            },
            {
                "name": "Bolt Catch",
                "parent": "Weapon Root",
                "presence": "optional",
                "movement_type": "rotate",
                "axis": "X",
                "constraints": [
                    {
                        "type": "LIMIT_ROTATION",
                        "min_x": 0.0,
                        "max_x": 0.175,
                        "use_limit_x": True,
                        "use_limit_y": True,
                        "use_limit_z": True,
                        "owner_space": "LOCAL",
                    }
                ],
                "description": "Holds bolt carrier open after last round. Magazine follower pushes it up",
                "placement": "Place at the bolt catch pivot pin on the left side of the lower receiver",
            },
            {
                "name": "Hammer",
                "parent": "Weapon Root",
                "presence": "optional",
                "movement_type": "rotate",
                "axis": "X",
                "constraints": [
                    {
                        "type": "LIMIT_ROTATION",
                        "min_x": -0.611,
                        "max_x": 0.0,
                        "use_limit_x": True,
                        "use_limit_y": True,
                        "use_limit_z": True,
                        "owner_space": "LOCAL",
                    }
                ],
                "parameters": {
                    "rotation_degrees": 35.0,
                },
                "description": "Rotates ~35 degrees under spring tension to strike firing pin",
                "placement": "Place at the hammer pin hole center in the lower receiver, behind the trigger",
            },
            {
                "name": "Buffer Spring",
                "parent": "Bolt Carrier",
                "presence": "optional",
                "movement_type": "scale",
                "axis": "Y",
                "drivers": [
                    {
                        "driven_property": "scale.y",
                        "driver_bone": "Bolt Carrier",
                        "driver_property": "location.y",
                        "expression": "1.0 + (var / 0.095) * 0.3",
                        "description": "Buffer spring compresses as carrier moves back. At full travel, spring is 30% shorter",
                    }
                ],
                "description": "Buffer spring in receiver extension. Absorbs carrier energy and returns it forward",
                "placement": "Place inside the buffer tube, at the front of the spring where it contacts the buffer",
            },
            {
                "name": "Cam Pin",
                "parent": "Bolt",
                "presence": "optional",
                "movement_type": "rotate",
                "axis": "Y",
                "description": "Rides in carrier cam track to force bolt rotation. Visual indicator of lock state",
                "placement": "Place at the cam pin hole in the bolt, perpendicular to the bore axis",
            },
            {
                "name": "Extractor",
                "parent": "Bolt",
                "presence": "optional",
                "movement_type": "rotate",
                "axis": "X",
                "constraints": [
                    {
                        "type": "LIMIT_ROTATION",
                        "min_x": 0.0,
                        "max_x": 0.087,
                        "use_limit_x": True,
                        "use_limit_y": True,
                        "use_limit_z": True,
                        "owner_space": "LOCAL",
                    }
                ],
                "description": "Spring-loaded claw that grips cartridge rim. Pivots ~5 degrees",
                "placement": "Place at the extractor pivot point on the bolt face, at the 3 o'clock position",
            },
        ],
        "physics": {
            "gas_impulse_duration_ms": 1.2,
            "carrier_peak_velocity_m_per_s": 5.8,
            "buffer_mass_kg": 0.091,
            "buffer_spring_rate_n_per_m": 3500,
            "return_spring_preload_n": 8.0,
            "bolt_carrier_mass_kg": 0.297,
        },
        "part_name_aliases": {
            "Bolt Carrier": ["bcg", "bolt_carrier_group", "carrier", "BCG"],
            "Bolt": ["bolt_head", "bolt_face"],
            "Trigger": ["trigger_blade", "trigger_shoe"],
            "Charging Handle": ["ch", "charge_handle", "cocking_handle"],
            "Magazine": ["mag", "clip", "magazine_body"],
            "Selector": ["selector_switch", "safety", "fire_selector"],
            "Dust Cover": ["ejection_port_cover", "port_cover"],
            "Forward Assist": ["fwd_assist", "FA"],
        },
    },
}


# ===================================================================
# SCHEMA
# ===================================================================

VALID_CONSTRAINT_TYPES = {
    "LIMIT_ROTATION", "LIMIT_LOCATION", "COPY_ROTATION", "TRACK_TO", "STRETCH_TO",
}


@dataclass
class ConstraintDef:
    type: str
    min_x: float = 0.0
    max_x: float = 0.0
    min_y: float = 0.0
    max_y: float = 0.0
    min_z: float = 0.0
    max_z: float = 0.0
    use_limit_x: bool = False
    use_limit_y: bool = False
    use_limit_z: bool = False
    use_min_x: bool = False
    use_max_x: bool = False
    use_min_y: bool = False
    use_max_y: bool = False
    use_min_z: bool = False
    use_max_z: bool = False
    owner_space: str = "LOCAL"
    target: Optional[str] = None
    subtarget: Optional[str] = None
    use_x: bool = True
    use_y: bool = True
    use_z: bool = True
    mix_mode: str = "REPLACE"
    target_space: str = "LOCAL"
    track_axis: str = "TRACK_NEGATIVE_Y"
    up_axis: str = "UP_Z"
    rest_length: float = 0.0
    influence: float = 1.0

    @classmethod
    def from_dict(cls, d: dict) -> "ConstraintDef":
        if d.get("type") not in VALID_CONSTRAINT_TYPES:
            raise ValueError(f"Unknown constraint type: {d.get('type')!r}")
        known = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class CamCurveKeyframe:
    carrier_travel_pct: float
    bolt_rotation_pct: float

    @classmethod
    def from_dict(cls, d: dict) -> "CamCurveKeyframe":
        return cls(d["carrier_travel_pct"], d["bolt_rotation_pct"])


@dataclass
class DriverDef:
    driven_property: str
    driver_bone: str
    driver_property: str
    expression: Optional[str] = None
    description: Optional[str] = None
    source: Optional[str] = None
    cam_curve_keyframes: list = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> "DriverDef":
        kfs = [CamCurveKeyframe.from_dict(kf) for kf in d.get("cam_curve_keyframes", [])]
        return cls(
            driven_property=d["driven_property"],
            driver_bone=d["driver_bone"],
            driver_property=d["driver_property"],
            expression=d.get("expression"),
            description=d.get("description"),
            source=d.get("source"),
            cam_curve_keyframes=kfs,
        )


@dataclass
class BoneDef:
    name: str
    parent: Optional[str] = None
    presence: str = "required"
    movement_type: str = "static"
    axis: Optional[str] = None
    description: Optional[str] = None
    placement: Optional[str] = None
    constraints: list = field(default_factory=list)
    drivers: list = field(default_factory=list)
    parameters: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "BoneDef":
        name = d.get("name")
        if not name:
            raise ValueError("Bone missing 'name'")
        return cls(
            name=name,
            parent=d.get("parent"),
            presence=d.get("presence", "required"),
            movement_type=d.get("movement_type", "static"),
            axis=d.get("axis"),
            description=d.get("description"),
            placement=d.get("placement"),
            constraints=[ConstraintDef.from_dict(c) for c in d.get("constraints", [])],
            drivers=[DriverDef.from_dict(dr) for dr in d.get("drivers", [])],
            parameters=d.get("parameters", {}),
        )


@dataclass
class WeaponConfig:
    schema_version: str
    operating_system: str
    display_name: str
    description: str = ""
    fire_modes: list = field(default_factory=list)
    cyclic_rate_rpm: dict = field(default_factory=dict)
    bones: list = field(default_factory=list)
    physics: dict = field(default_factory=dict)
    part_name_aliases: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "WeaponConfig":
        bones = [BoneDef.from_dict(b) for b in d.get("bones", [])]
        return cls(
            schema_version=d.get("schema_version", "1.0"),
            operating_system=d["operating_system"],
            display_name=d.get("display_name", d["operating_system"]),
            description=d.get("description", ""),
            fire_modes=d.get("fire_modes", []),
            cyclic_rate_rpm=d.get("cyclic_rate_rpm", {}),
            bones=bones,
            physics=d.get("physics", {}),
            part_name_aliases=d.get("part_name_aliases", {}),
        )

    def get_bone(self, name: str) -> Optional[BoneDef]:
        for b in self.bones:
            if b.name == name:
                return b
        return None


# ===================================================================
# SKELETON BUILDER
# ===================================================================

AXIS_VECTORS = {
    "X": Vector((0.05, 0, 0)),
    "Y": Vector((0, 0.05, 0)),
    "Z": Vector((0, 0, 0.05)),
    "-X": Vector((-0.05, 0, 0)),
    "-Y": Vector((0, -0.05, 0)),
    "-Z": Vector((0, 0, -0.05)),
}
DEFAULT_TAIL = Vector((0, 0.05, 0))


def get_or_create_armature(context):
    """Return the active WeaponRig armature, or create one."""
    active = context.active_object
    if active and active.type == "ARMATURE" and active.get("weaponrig"):
        return active

    for obj in context.scene.objects:
        if obj.type == "ARMATURE" and obj.get("weaponrig"):
            return obj

    arm_data = bpy.data.armatures.new("WeaponRig")
    arm_obj = bpy.data.objects.new("WeaponRig", arm_data)
    context.collection.objects.link(arm_obj)
    arm_obj["weaponrig"] = True
    return arm_obj


def add_single_bone(config, bone_name, armature_obj, position, context):
    """Add one bone to the armature at the given position."""
    bone_def = config.get_bone(bone_name)
    if bone_def is None:
        return {"error": f"No bone '{bone_name}' in config"}

    if bone_name in [b.name for b in armature_obj.data.bones]:
        return {"error": f"Bone '{bone_name}' already exists"}

    if context.object and context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")

    context.view_layer.objects.active = armature_obj
    armature_obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")

    eb = armature_obj.data.edit_bones.new(bone_def.name)
    eb.head = position.copy()

    if bone_def.axis and bone_def.axis in AXIS_VECTORS:
        eb.tail = eb.head + AXIS_VECTORS[bone_def.axis]
    else:
        eb.tail = eb.head + DEFAULT_TAIL

    if bone_def.parent:
        parent_eb = armature_obj.data.edit_bones.get(bone_def.parent)
        if parent_eb:
            eb.parent = parent_eb
            eb.use_connect = False

    bpy.ops.object.mode_set(mode="OBJECT")

    info = {
        "name": bone_def.name,
        "parent": bone_def.parent,
        "movement": bone_def.movement_type,
        "axis": bone_def.axis,
        "constraints_added": 0,
        "drivers_added": 0,
        "description": bone_def.description or "",
    }

    info["constraints_added"] = _apply_bone_constraints(armature_obj, bone_def)
    info["drivers_added"] = _apply_bone_drivers(armature_obj, bone_def)

    return info


# ===================================================================
# CONSTRAINT BUILDER
# ===================================================================

def _apply_bone_constraints(arm_obj, bone_def):
    if not bone_def.constraints:
        return 0
    pose_bone = arm_obj.pose.bones.get(bone_def.name)
    if pose_bone is None:
        return 0
    count = 0
    for cdef in bone_def.constraints:
        con = pose_bone.constraints.new(type=cdef.type)

        if cdef.type == "LIMIT_ROTATION":
            con.owner_space = cdef.owner_space
            con.use_limit_x = cdef.use_limit_x
            con.use_limit_y = cdef.use_limit_y
            con.use_limit_z = cdef.use_limit_z
            if cdef.use_limit_x:
                con.min_x = min(cdef.min_x, cdef.max_x)
                con.max_x = max(cdef.min_x, cdef.max_x)
            if cdef.use_limit_y:
                con.min_y = min(cdef.min_y, cdef.max_y)
                con.max_y = max(cdef.min_y, cdef.max_y)
            if cdef.use_limit_z:
                con.min_z = min(cdef.min_z, cdef.max_z)
                con.max_z = max(cdef.min_z, cdef.max_z)

        elif cdef.type == "LIMIT_LOCATION":
            con.owner_space = cdef.owner_space
            con.use_min_x = cdef.use_min_x
            con.use_max_x = cdef.use_max_x
            con.use_min_y = cdef.use_min_y
            con.use_max_y = cdef.use_max_y
            con.use_min_z = cdef.use_min_z
            con.use_max_z = cdef.use_max_z
            con.min_x = min(cdef.min_x, cdef.max_x)
            con.max_x = max(cdef.min_x, cdef.max_x)
            con.min_y = min(cdef.min_y, cdef.max_y)
            con.max_y = max(cdef.min_y, cdef.max_y)
            con.min_z = min(cdef.min_z, cdef.max_z)
            con.max_z = max(cdef.min_z, cdef.max_z)

        elif cdef.type == "COPY_ROTATION":
            con.target = arm_obj
            if cdef.subtarget:
                con.subtarget = cdef.subtarget
            con.use_x = cdef.use_x
            con.use_y = cdef.use_y
            con.use_z = cdef.use_z
            con.mix_mode = cdef.mix_mode
            con.target_space = cdef.target_space
            con.owner_space = cdef.owner_space

        elif cdef.type == "TRACK_TO":
            con.target = arm_obj
            if cdef.subtarget:
                con.subtarget = cdef.subtarget
            con.track_axis = cdef.track_axis
            con.up_axis = cdef.up_axis

        elif cdef.type == "STRETCH_TO":
            con.target = arm_obj
            if cdef.subtarget:
                con.subtarget = cdef.subtarget
            con.rest_length = cdef.rest_length

        con.influence = cdef.influence
        count += 1
    return count


# ===================================================================
# DRIVER BUILDER
# ===================================================================

_PROPERTY_TO_TRANSFORM = {
    "location.x": "LOC_X", "location.y": "LOC_Y", "location.z": "LOC_Z",
    "rotation_euler.x": "ROT_X", "rotation_euler.y": "ROT_Y", "rotation_euler.z": "ROT_Z",
    "scale.x": "SCALE_X", "scale.y": "SCALE_Y", "scale.z": "SCALE_Z",
}
_AXIS_INDEX = {"x": 0, "y": 1, "z": 2, "w": 3}


def _parse_prop(prop):
    parts = prop.rsplit(".", 1)
    return parts[0], _AXIS_INDEX[parts[1]]


def _apply_bone_drivers(arm_obj, bone_def):
    if not bone_def.drivers:
        return 0
    pose_bone = arm_obj.pose.bones.get(bone_def.name)
    if pose_bone is None:
        return 0
    count = 0
    for ddef in bone_def.drivers:
        data_path, axis_idx = _parse_prop(ddef.driven_property)
        fcurve = pose_bone.driver_add(data_path, axis_idx)
        driver = fcurve.driver
        driver.type = "SCRIPTED"

        var = driver.variables.new()
        var.name = "var"
        var.type = "TRANSFORMS"
        tgt = var.targets[0]
        tgt.id = arm_obj
        tgt.bone_target = ddef.driver_bone
        tgt.transform_type = _PROPERTY_TO_TRANSFORM[ddef.driver_property]
        tgt.transform_space = "LOCAL_SPACE"

        if ddef.cam_curve_keyframes:
            driver.expression = "var"
            travel = bone_def.parameters.get("carrier_travel_m", 1.0)
            rot_deg = bone_def.parameters.get("rotation_degrees", 1.0)
            rot_rad = math.radians(rot_deg)
            sorted_kfs = sorted(ddef.cam_curve_keyframes, key=lambda k: k.carrier_travel_pct)
            while fcurve.keyframe_points:
                fcurve.keyframe_points.remove(fcurve.keyframe_points[0])
            for kf in sorted_kfs:
                pt = fcurve.keyframe_points.insert(kf.carrier_travel_pct * travel, kf.bolt_rotation_pct * rot_rad)
                pt.interpolation = "LINEAR"
        else:
            driver.expression = ddef.expression or "var"

        count += 1
    return count


# ===================================================================
# OPERATORS
# ===================================================================

class WEAPONRIG_OT_add_bone(bpy.types.Operator):
    """Add the next weapon bone at the 3D cursor position"""
    bl_idname = "weaponrig.add_bone"
    bl_label = "Add Bone"
    bl_options = {"REGISTER", "UNDO"}

    bone_name: bpy.props.StringProperty(name="Bone Name")
    use_selection: bpy.props.BoolProperty(name="Use Selection", default=False)

    def execute(self, context):
        weapon_type = context.scene.weaponrig_weapon_type
        if weapon_type not in WEAPON_CONFIGS:
            self.report({"ERROR"}, f"Unknown weapon type: {weapon_type}")
            return {"CANCELLED"}

        config = WeaponConfig.from_dict(WEAPON_CONFIGS[weapon_type])

        bone_name = self.bone_name
        if not bone_name:
            added = set(_get_added_list(context))
            for b in config.bones:
                if b.name not in added:
                    bone_name = b.name
                    break
            if not bone_name:
                self.report({"INFO"}, "All bones have been added")
                return {"CANCELLED"}

        if self.use_selection:
            position = _selection_centroid(context)
            if position is None:
                self.report({"WARNING"}, "No selection found, using 3D cursor")
                position = context.scene.cursor.location.copy()
        else:
            position = context.scene.cursor.location.copy()

        arm_obj = get_or_create_armature(context)
        info = add_single_bone(config, bone_name, arm_obj, position, context)

        if "error" in info:
            self.report({"ERROR"}, info["error"])
            return {"CANCELLED"}

        added = _get_added_list(context)
        if bone_name not in added:
            added.append(bone_name)
            context.scene.weaponrig_added_bones = json.dumps(added)

        msg = f"Added: {info['name']}"
        if info.get("constraints_added"):
            msg += f" ({info['constraints_added']} constraints)"
        if info.get("drivers_added"):
            msg += f" ({info['drivers_added']} drivers)"

        self.report({"INFO"}, msg)

        context.view_layer.objects.active = arm_obj
        arm_obj.select_set(True)

        return {"FINISHED"}


class WEAPONRIG_OT_select_bone(bpy.types.Operator):
    """Select a bone in the armature"""
    bl_idname = "weaponrig.select_bone"
    bl_label = "Select Bone"

    bone_name: bpy.props.StringProperty(name="Bone Name")

    def execute(self, context):
        arm_obj = None
        for obj in context.scene.objects:
            if obj.type == "ARMATURE" and obj.get("weaponrig"):
                arm_obj = obj
                break

        if arm_obj is None:
            self.report({"WARNING"}, "No WeaponRig armature found")
            return {"CANCELLED"}

        context.view_layer.objects.active = arm_obj
        arm_obj.select_set(True)
        bpy.ops.object.mode_set(mode="POSE")

        for pb in arm_obj.pose.bones:
            pb.bone.select = pb.name == self.bone_name

        return {"FINISHED"}


class WEAPONRIG_OT_import_mesh(bpy.types.Operator, ImportHelper):
    """Import a weapon mesh file"""
    bl_idname = "weaponrig.import_mesh"
    bl_label = "Import Weapon Mesh"
    bl_options = {"REGISTER", "UNDO"}
    filter_glob: bpy.props.StringProperty(default="*.fbx;*.obj;*.gltf;*.glb", options={"HIDDEN"})

    def execute(self, context):
        fp = Path(self.filepath)
        ext = fp.suffix.lower()
        try:
            if ext == ".fbx":
                bpy.ops.import_scene.fbx(filepath=str(fp))
            elif ext == ".obj":
                bpy.ops.wm.obj_import(filepath=str(fp))
            elif ext in (".gltf", ".glb"):
                bpy.ops.import_scene.gltf(filepath=str(fp))
            else:
                self.report({"ERROR"}, f"Unsupported: {ext}")
                return {"CANCELLED"}
        except Exception as e:
            self.report({"ERROR"}, f"Import failed: {e}")
            return {"CANCELLED"}
        self.report({"INFO"}, f"Imported: {fp.name}")
        return {"FINISHED"}


# ===================================================================
# HELPERS
# ===================================================================

def _get_added_list(context):
    raw = context.scene.weaponrig_added_bones
    if not raw:
        return []
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return []


def _selection_centroid(context):
    obj = context.active_object
    if obj and obj.type == "MESH" and obj.mode == "EDIT":
        import bmesh
        bm = bmesh.from_edit_mesh(obj.data)
        selected_verts = [v for v in bm.verts if v.select]
        if selected_verts:
            centroid = sum((v.co for v in selected_verts), Vector()) / len(selected_verts)
            return obj.matrix_world @ centroid

    selected = [o for o in context.selected_objects if o.type == "MESH"]
    if selected:
        centroid = sum((o.location for o in selected), Vector()) / len(selected)
        return centroid

    return None


def _wrap_text(layout, text, width=40):
    col = layout.column(align=True)
    words = text.split()
    line = ""
    for word in words:
        if len(line) + len(word) + 1 > width:
            col.label(text=line)
            line = word
        else:
            line = f"{line} {word}" if line else word
    if line:
        col.label(text=line)


# ===================================================================
# UI PANEL
# ===================================================================

class WEAPONRIG_PT_main(bpy.types.Panel):
    """WeaponRig guided rigging panel"""
    bl_label = "WeaponRig"
    bl_idname = "WEAPONRIG_PT_main"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "WeaponRig"

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        # Weapon type selector
        box = layout.box()
        box.label(text="Weapon Type", icon="PREFERENCES")
        box.prop(scene, "weaponrig_weapon_type", text="")

        weapon_type = scene.weaponrig_weapon_type
        if weapon_type not in WEAPON_CONFIGS:
            layout.label(text="No config loaded", icon="ERROR")
            return

        config = WeaponConfig.from_dict(WEAPON_CONFIGS[weapon_type])
        added = set(_get_added_list(context))

        # Bone checklist
        box = layout.box()
        box.label(text="Bone Checklist", icon="ARMATURE_DATA")

        required_total = 0
        required_done = 0
        optional_total = 0
        optional_done = 0
        next_bone = None

        for bone_def in config.bones:
            is_added = bone_def.name in added
            is_required = bone_def.presence in ("required", "expected")

            if is_required:
                required_total += 1
                if is_added:
                    required_done += 1
            else:
                optional_total += 1
                if is_added:
                    optional_done += 1

            row = box.row(align=True)

            if is_added:
                row.label(text="", icon="CHECKMARK")
                row.label(text=bone_def.name)
                op = row.operator("weaponrig.select_bone", text="", icon="RESTRICT_SELECT_OFF")
                op.bone_name = bone_def.name
            else:
                if bone_def.presence == "required":
                    row.label(text="", icon="LAYER_ACTIVE")
                elif bone_def.presence == "expected":
                    row.label(text="", icon="LAYER_USED")
                else:
                    row.label(text="", icon="RADIOBUT_OFF")
                row.label(text=bone_def.name)

                if next_bone is None:
                    next_bone = bone_def

        # Progress
        row = layout.row()
        row.label(text=f"Required: {required_done}/{required_total}")
        row.label(text=f"Optional: {optional_done}/{optional_total}")

        # Next bone detail panel
        if next_bone:
            box = layout.box()
            box.label(text=f"Next: {next_bone.name}", icon="BONE_DATA")

            if next_bone.description:
                _wrap_text(box, next_bone.description)

            box.separator()

            if next_bone.movement_type != "static":
                box.label(text=f"Movement: {next_bone.movement_type} on {next_bone.axis}", icon="CON_LOCLIKE")

            if next_bone.parent:
                box.label(text=f"Parent: {next_bone.parent}", icon="CON_CHILDOF")

            if next_bone.placement:
                box.separator()
                box.label(text="Placement:", icon="CURSOR")
                _wrap_text(box, next_bone.placement)

            params = next_bone.parameters
            if params:
                box.separator()
                box.label(text="Specs:", icon="INFO")
                for key, val in params.items():
                    if key in ("source", "pivot_description"):
                        continue
                    if isinstance(val, (list, dict)):
                        continue
                    display_key = key.replace("_", " ").title()
                    box.label(text=f"  {display_key}: {val}")

            box.separator()

            row = box.row(align=True)
            op = row.operator("weaponrig.add_bone", text="Add at 3D Cursor", icon="CURSOR")
            op.bone_name = next_bone.name
            op.use_selection = False

            op = row.operator("weaponrig.add_bone", text="Add at Selection", icon="RESTRICT_SELECT_OFF")
            op.bone_name = next_bone.name
            op.use_selection = True
        else:
            box = layout.box()
            box.label(text="All bones added!", icon="CHECKMARK")


# ===================================================================
# REGISTRATION
# ===================================================================

_classes = (
    WEAPONRIG_OT_add_bone,
    WEAPONRIG_OT_select_bone,
    WEAPONRIG_OT_import_mesh,
    WEAPONRIG_PT_main,
)


def _weapon_type_items(self, context):
    return [(k, v["display_name"], v.get("description", "")) for k, v in WEAPON_CONFIGS.items()]


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.weaponrig_weapon_type = bpy.props.EnumProperty(
        name="Weapon Type",
        description="Select the weapon operating system",
        items=_weapon_type_items,
    )
    bpy.types.Scene.weaponrig_added_bones = bpy.props.StringProperty(
        name="Added Bones",
        description="JSON list of added bone names",
        default="",
    )


def unregister():
    del bpy.types.Scene.weaponrig_added_bones
    del bpy.types.Scene.weaponrig_weapon_type
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
