"""WeaponRig — Automated weapon rigging pipeline for FPS games. Single-file addon."""

bl_info = {
    "name": "WeaponRig",
    "author": "Aamir Farrukh",
    "version": (0, 1, 0),
    "blender": (4, 0, 0),
    "location": "View3D > Sidebar > WeaponRig",
    "description": "Automated weapon rigging for FPS games",
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
                "name": "weapon_root",
                "parent": None,
                "presence": "required",
                "movement_type": "static",
                "description": "Lower receiver - root of all weapon bones",
            },
            {
                "name": "upper_receiver",
                "parent": "weapon_root",
                "presence": "required",
                "movement_type": "static",
                "description": "Upper receiver - static relative to lower",
            },
            {
                "name": "bolt_carrier",
                "parent": "upper_receiver",
                "presence": "required",
                "movement_type": "translate",
                "axis": "Y",
                "constraints": [
                    {
                        "type": "LIMIT_LOCATION",
                        "min_y": 0.0,
                        "max_y": -0.095,
                        "use_min_y": True,
                        "use_max_y": True,
                        "owner_space": "LOCAL",
                    }
                ],
                "parameters": {
                    "carrier_travel_m": 0.095,
                    "dwell_before_unlock_m": 0.003,
                    "carrier_mass_kg": 0.297,
                    "buffer_spring_rate_n_per_m": 3500,
                },
            },
            {
                "name": "bolt",
                "parent": "bolt_carrier",
                "presence": "required",
                "movement_type": "rotate",
                "axis": "Y",
                "constraints": [
                    {
                        "type": "LIMIT_ROTATION",
                        "min_y": 0.0,
                        "max_y": 0.361,
                        "use_limit_y": True,
                        "owner_space": "LOCAL",
                    }
                ],
                "drivers": [
                    {
                        "driven_property": "rotation_euler.y",
                        "driver_bone": "bolt_carrier",
                        "driver_property": "location.y",
                        "expression": "var * -3.8",
                        "description": "Bolt rotates 20.7deg as carrier travels back",
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
            },
            {
                "name": "trigger",
                "parent": "weapon_root",
                "presence": "required",
                "movement_type": "rotate",
                "axis": "X",
                "constraints": [
                    {
                        "type": "LIMIT_ROTATION",
                        "min_x": 0.0,
                        "max_x": -0.262,
                        "use_limit_x": True,
                        "owner_space": "LOCAL",
                    }
                ],
                "parameters": {
                    "rotation_degrees": 15.0,
                    "pivot_description": "Trigger pin center",
                },
            },
            {
                "name": "selector",
                "parent": "weapon_root",
                "presence": "expected",
                "movement_type": "rotate",
                "axis": "Z",
                "constraints": [
                    {
                        "type": "LIMIT_ROTATION",
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
                    "detent_count": 3,
                },
            },
            {
                "name": "charging_handle",
                "parent": "upper_receiver",
                "presence": "expected",
                "movement_type": "translate",
                "axis": "Y",
                "constraints": [
                    {
                        "type": "LIMIT_LOCATION",
                        "min_y": 0.0,
                        "max_y": -0.076,
                        "use_min_y": True,
                        "use_max_y": True,
                        "owner_space": "LOCAL",
                    }
                ],
            },
            {
                "name": "magazine",
                "parent": None,
                "presence": "required",
                "movement_type": "translate",
                "axis": "Z",
                "description": "Unparented when released, parents to weapon_root when inserted",
            },
            {
                "name": "magazine_release",
                "parent": "weapon_root",
                "presence": "expected",
                "movement_type": "translate",
                "axis": "X",
            },
            {
                "name": "dust_cover",
                "parent": "upper_receiver",
                "presence": "optional",
                "movement_type": "rotate",
                "axis": "X",
                "parameters": {
                    "rotation_degrees": 75.0,
                    "pivot_description": "Dust cover hinge pin",
                },
            },
            {
                "name": "forward_assist",
                "parent": "upper_receiver",
                "presence": "optional",
                "movement_type": "translate",
                "axis": "Y",
            },
            {
                "name": "bolt_catch",
                "parent": "weapon_root",
                "presence": "optional",
                "movement_type": "rotate",
                "axis": "X",
            },
            {
                "name": "hammer",
                "parent": "weapon_root",
                "presence": "optional",
                "movement_type": "rotate",
                "axis": "X",
                "parameters": {
                    "rotation_degrees": 35.0,
                    "pivot_description": "Hammer pin center",
                },
            },
            {
                "name": "buffer_spring",
                "parent": "bolt_carrier",
                "presence": "optional",
                "movement_type": "scale",
                "axis": "Y",
                "drivers": [
                    {
                        "driven_property": "scale.y",
                        "driver_bone": "bolt_carrier",
                        "driver_property": "location.y",
                        "expression": "1.0 + (var / 0.095) * 0.3",
                        "description": "Buffer spring compresses as carrier moves back",
                    }
                ],
            },
            {
                "name": "cam_pin",
                "parent": "bolt",
                "presence": "optional",
                "movement_type": "rotate",
                "axis": "Y",
                "description": "Rotates with bolt, visual only",
            },
            {
                "name": "extractor",
                "parent": "bolt",
                "presence": "optional",
                "movement_type": "rotate",
                "axis": "X",
            },
        ],
        "unified_skeleton_extra_bones": [
            "ik_hand_root",
            "ik_hand_gun",
            "ik_hand_l",
            "ik_hand_r",
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
            "bolt_carrier": ["bcg", "bolt_carrier_group", "carrier", "BCG"],
            "bolt": ["bolt_head", "bolt_face"],
            "trigger": ["trigger_blade", "trigger_shoe"],
            "charging_handle": ["ch", "charge_handle", "cocking_handle"],
            "magazine": ["mag", "clip", "magazine_body"],
            "selector": ["selector_switch", "safety", "fire_selector"],
            "dust_cover": ["ejection_port_cover", "port_cover"],
            "forward_assist": ["fwd_assist", "FA"],
        },
    },
}


# ===================================================================
# SCHEMA (dataclasses)
# ===================================================================

VALID_CONSTRAINT_TYPES = {
    "LIMIT_ROTATION",
    "LIMIT_LOCATION",
    "COPY_ROTATION",
    "TRACK_TO",
    "STRETCH_TO",
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
    unified_skeleton_extra_bones: list = field(default_factory=list)
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
            unified_skeleton_extra_bones=d.get("unified_skeleton_extra_bones", []),
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

UNIFIED_SKELETON_BONES = [
    "weapon_root", "upper_receiver", "lower_receiver",
    "bolt_carrier", "bolt", "cam_pin", "extractor", "ejector",
    "trigger", "hammer", "disconnector", "selector",
    "charging_handle", "magazine", "magazine_release", "magazine_follower",
    "dust_cover", "forward_assist", "bolt_catch", "buffer_spring",
    "gas_piston", "barrel", "muzzle_device", "handguard_rail",
    "sight_front", "sight_rear",
    "ik_hand_root", "ik_hand_gun", "ik_hand_l", "ik_hand_r",
]


def build_skeleton(config, context):
    arm_data = bpy.data.armatures.new(f"{config.operating_system}_armature")
    arm_obj = bpy.data.objects.new(f"{config.operating_system}_rig", arm_data)
    context.collection.objects.link(arm_obj)
    context.view_layer.objects.active = arm_obj
    arm_obj.select_set(True)

    bpy.ops.object.mode_set(mode="EDIT")

    config_bone_names = set()

    # Pass 1: create config bones
    for bone_def in config.bones:
        eb = arm_data.edit_bones.new(bone_def.name)
        eb.head = Vector((0, 0, 0))
        if bone_def.axis and bone_def.axis in AXIS_VECTORS:
            eb.tail = eb.head + AXIS_VECTORS[bone_def.axis]
        else:
            eb.tail = eb.head + DEFAULT_TAIL
        config_bone_names.add(bone_def.name)

    # IK helper bones
    for ik_name in config.unified_skeleton_extra_bones:
        if ik_name not in config_bone_names:
            eb = arm_data.edit_bones.new(ik_name)
            eb.head = Vector((0, 0, 0))
            eb.tail = DEFAULT_TAIL
            config_bone_names.add(ik_name)

    # Dormant unified skeleton bones
    for name in UNIFIED_SKELETON_BONES:
        if name not in config_bone_names:
            eb = arm_data.edit_bones.new(name)
            eb.head = Vector((0, 0, 0))
            eb.tail = DEFAULT_TAIL

    # Pass 2: parent relationships
    for bone_def in config.bones:
        if bone_def.parent:
            child = arm_data.edit_bones.get(bone_def.name)
            parent = arm_data.edit_bones.get(bone_def.parent)
            if child and parent:
                child.parent = parent
                child.use_connect = False

    bpy.ops.object.mode_set(mode="OBJECT")
    arm_obj["weaponrig_config"] = config.operating_system
    return arm_obj


# ===================================================================
# CONSTRAINT BUILDER
# ===================================================================

def apply_constraints(arm_obj, config):
    count = 0
    for bone_def in config.bones:
        if not bone_def.constraints:
            continue
        pose_bone = arm_obj.pose.bones.get(bone_def.name)
        if not pose_bone:
            continue
        for cdef in bone_def.constraints:
            con = pose_bone.constraints.new(type=cdef.type)
            con.influence = cdef.influence

            if cdef.type == "LIMIT_ROTATION":
                con.owner_space = cdef.owner_space
                con.use_limit_x = cdef.use_limit_x
                con.use_limit_y = cdef.use_limit_y
                con.use_limit_z = cdef.use_limit_z
                if cdef.use_limit_x:
                    con.min_x = cdef.min_x
                    con.max_x = cdef.max_x
                if cdef.use_limit_y:
                    con.min_y = cdef.min_y
                    con.max_y = cdef.max_y
                if cdef.use_limit_z:
                    con.min_z = cdef.min_z
                    con.max_z = cdef.max_z

            elif cdef.type == "LIMIT_LOCATION":
                con.owner_space = cdef.owner_space
                con.use_min_x = cdef.use_min_x
                con.use_max_x = cdef.use_max_x
                con.use_min_y = cdef.use_min_y
                con.use_max_y = cdef.use_max_y
                con.use_min_z = cdef.use_min_z
                con.use_max_z = cdef.use_max_z
                if cdef.use_min_x:
                    con.min_x = cdef.min_x
                if cdef.use_max_x:
                    con.max_x = cdef.max_x
                if cdef.use_min_y:
                    con.min_y = cdef.min_y
                if cdef.use_max_y:
                    con.max_y = cdef.max_y
                if cdef.use_min_z:
                    con.min_z = cdef.min_z
                if cdef.use_max_z:
                    con.max_z = cdef.max_z

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


def apply_drivers(arm_obj, config):
    count = 0
    for bone_def in config.bones:
        if not bone_def.drivers:
            continue
        pose_bone = arm_obj.pose.bones.get(bone_def.name)
        if not pose_bone:
            continue
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

class WEAPONRIG_OT_build_rig(bpy.types.Operator):
    """Build a weapon rig from the selected config"""
    bl_idname = "weaponrig.build_rig"
    bl_label = "Build Weapon Rig"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        weapon_type = context.scene.weaponrig_weapon_type
        if weapon_type not in WEAPON_CONFIGS:
            self.report({"ERROR"}, f"Unknown weapon type: {weapon_type}")
            return {"CANCELLED"}

        config = WeaponConfig.from_dict(WEAPON_CONFIGS[weapon_type])
        bpy.ops.object.select_all(action="DESELECT")
        arm_obj = build_skeleton(config, context)
        c_count = apply_constraints(arm_obj, config)
        d_count = apply_drivers(arm_obj, config)

        self.report(
            {"INFO"},
            f"Built {config.display_name}: "
            f"{len(arm_obj.data.bones)} bones, {c_count} constraints, {d_count} drivers",
        )
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
# UI PANEL
# ===================================================================

class WEAPONRIG_PT_main(bpy.types.Panel):
    """WeaponRig panel"""
    bl_label = "WeaponRig"
    bl_idname = "WEAPONRIG_PT_main"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "WeaponRig"

    def draw(self, context):
        layout = self.layout

        box = layout.box()
        box.label(text="1. Import", icon="IMPORT")
        box.operator("weaponrig.import_mesh", text="Import Weapon Mesh")

        box = layout.box()
        box.label(text="2. Weapon Type", icon="PREFERENCES")
        box.prop(context.scene, "weaponrig_weapon_type", text="")

        box = layout.box()
        box.label(text="3. Build Rig", icon="ARMATURE_DATA")
        box.operator("weaponrig.build_rig", text="Build Skeleton + Drivers")

        active = context.active_object
        if active and active.type == "ARMATURE" and active.get("weaponrig_config"):
            box = layout.box()
            box.label(text="4. Rig Info", icon="INFO")
            box.label(text=f"Config: {active['weaponrig_config']}")
            box.label(text=f"Bones: {len(active.data.bones)}")


# ===================================================================
# REGISTRATION
# ===================================================================

_classes = (
    WEAPONRIG_OT_build_rig,
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


def unregister():
    del bpy.types.Scene.weaponrig_weapon_type
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
