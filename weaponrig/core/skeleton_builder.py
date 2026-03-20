"""Creates Blender armature from a WeaponConfig."""

import bpy
from mathutils import Vector

from ..database.schema import BoneDef, WeaponConfig

# Axis direction vectors for bone tail placement.
# Tail is offset from head along the bone's movement axis.
AXIS_VECTORS = {
    "X": Vector((0.05, 0, 0)),
    "Y": Vector((0, 0.05, 0)),
    "Z": Vector((0, 0, 0.05)),
    "-X": Vector((-0.05, 0, 0)),
    "-Y": Vector((0, -0.05, 0)),
    "-Z": Vector((0, 0, -0.05)),
}

DEFAULT_TAIL = Vector((0, 0.05, 0))

# Master unified skeleton bone list — bones not defined in the config
# are created as dormant (at origin, flagged unused).
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


def build_skeleton(
    config: WeaponConfig, context: bpy.types.Context
) -> bpy.types.Object:
    """Create an armature object with all bones from *config*.

    Bones are positioned at the origin with tails along their movement axis.
    Phase 2 (mesh segmentation) will reposition them to part centroids.

    Returns the armature object.
    """
    arm_data = bpy.data.armatures.new(f"{config.operating_system}_armature")
    arm_obj = bpy.data.objects.new(f"{config.operating_system}_rig", arm_data)

    context.collection.objects.link(arm_obj)
    context.view_layer.objects.active = arm_obj
    arm_obj.select_set(True)

    # -- Edit mode: create & parent bones ----------------------------------
    bpy.ops.object.mode_set(mode="EDIT")

    config_bone_names: set[str] = set()

    # Pass 1 — create bones from config
    for bone_def in config.bones:
        _create_edit_bone(arm_data, bone_def)
        config_bone_names.add(bone_def.name)

    # Create unified skeleton extra bones (IK helpers)
    for ik_name in config.unified_skeleton_extra_bones:
        if ik_name not in config_bone_names:
            eb = arm_data.edit_bones.new(ik_name)
            eb.head = Vector((0, 0, 0))
            eb.tail = DEFAULT_TAIL
            config_bone_names.add(ik_name)

    # Create dormant bones for unified skeleton completeness
    for master_name in UNIFIED_SKELETON_BONES:
        if master_name not in config_bone_names:
            eb = arm_data.edit_bones.new(master_name)
            eb.head = Vector((0, 0, 0))
            eb.tail = DEFAULT_TAIL

    # Pass 2 — set parent relationships
    for bone_def in config.bones:
        if bone_def.parent:
            child = arm_data.edit_bones.get(bone_def.name)
            parent = arm_data.edit_bones.get(bone_def.parent)
            if child and parent:
                child.parent = parent
                child.use_connect = False  # weapon bones are never connected

    bpy.ops.object.mode_set(mode="OBJECT")

    # Store config reference as custom property for later use
    arm_obj["weaponrig_config"] = config.operating_system

    return arm_obj


def _create_edit_bone(
    armature: bpy.types.Armature, bone_def: BoneDef
) -> bpy.types.EditBone:
    """Create a single edit bone positioned at origin with directional tail."""
    eb = armature.edit_bones.new(bone_def.name)
    eb.head = Vector((0, 0, 0))

    # Point tail along the bone's movement axis for visual clarity
    if bone_def.axis and bone_def.axis in AXIS_VECTORS:
        eb.tail = eb.head + AXIS_VECTORS[bone_def.axis]
    else:
        eb.tail = eb.head + DEFAULT_TAIL

    return eb
