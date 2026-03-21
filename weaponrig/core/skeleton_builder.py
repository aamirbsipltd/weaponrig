"""Creates and manages weapon armature bones one at a time."""

import bpy
from mathutils import Vector

from ..database.schema import BoneDef, WeaponConfig

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
    """Return the active WeaponRig armature, or create one if none exists."""
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
    """Add one bone to the armature at the given position.

    Creates the bone, sets its parent (if parent exists), and applies
    constraints and drivers defined in the config.

    Returns a dict with info about what was created for UI feedback.
    """
    bone_def = config.get_bone(bone_name)
    if bone_def is None:
        return {"error": f"No bone '{bone_name}' in config"}

    if bone_name in [b.name for b in armature_obj.data.bones]:
        return {"error": f"Bone '{bone_name}' already exists"}

    prev_active = context.view_layer.objects.active
    prev_mode = context.object.mode if context.object else "OBJECT"

    if prev_mode != "OBJECT":
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
        "position": tuple(position),
        "parent": bone_def.parent,
        "parent_connected": bone_def.parent and bone_def.parent in [b.name for b in armature_obj.data.bones],
        "movement": bone_def.movement_type,
        "axis": bone_def.axis,
        "constraints_added": 0,
        "drivers_added": 0,
        "description": bone_def.description or "",
        "placement": bone_def.placement or "",
    }

    from .constraint_builder import apply_bone_constraints
    from .driver_builder import apply_bone_drivers

    info["constraints_added"] = apply_bone_constraints(armature_obj, bone_def)
    info["drivers_added"] = apply_bone_drivers(armature_obj, bone_def)

    return info


def get_added_bones(armature_obj):
    """Return set of bone names currently in the armature."""
    if armature_obj is None or armature_obj.type != "ARMATURE":
        return set()
    return {b.name for b in armature_obj.data.bones}
