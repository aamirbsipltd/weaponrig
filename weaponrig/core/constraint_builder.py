"""Adds constraints to pose bones from config definitions."""

import bpy

from ..database.schema import BoneDef, ConstraintDef, WeaponConfig


def apply_bone_constraints(arm_obj, bone_def):
    """Add constraints to a single pose bone. Returns count of constraints added."""
    if not bone_def.constraints:
        return 0

    pose_bone = arm_obj.pose.bones.get(bone_def.name)
    if pose_bone is None:
        return 0

    count = 0
    for cdef in bone_def.constraints:
        _add_constraint(pose_bone, cdef, arm_obj, bone_def)
        count += 1
    return count


def apply_constraints(arm_obj, config):
    """Add constraints to all bones. Returns total count."""
    count = 0
    for bone_def in config.bones:
        count += apply_bone_constraints(arm_obj, bone_def)
    return count


def _add_constraint(pose_bone, cdef, arm_obj, bone_def):
    """Create a single constraint on a pose bone."""
    con = pose_bone.constraints.new(type=cdef.type)

    if cdef.type == "LIMIT_ROTATION":
        _apply_limit_rotation(con, cdef)
    elif cdef.type == "LIMIT_LOCATION":
        _apply_limit_location(con, cdef)
    elif cdef.type == "COPY_ROTATION":
        _apply_copy_rotation(con, cdef, arm_obj)
    elif cdef.type == "TRACK_TO":
        _apply_track_to(con, cdef, arm_obj)
    elif cdef.type == "STRETCH_TO":
        _apply_stretch_to(con, cdef, arm_obj)

    con.influence = cdef.influence
    return con


def _apply_limit_rotation(con, cdef):
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


def _apply_limit_location(con, cdef):
    con.owner_space = cdef.owner_space

    # Lock all 6 axes
    con.use_min_x = cdef.use_min_x
    con.use_max_x = cdef.use_max_x
    con.use_min_y = cdef.use_min_y
    con.use_max_y = cdef.use_max_y
    con.use_min_z = cdef.use_min_z
    con.use_max_z = cdef.use_max_z

    # Ensure min <= max (swap if backwards)
    con.min_x = min(cdef.min_x, cdef.max_x)
    con.max_x = max(cdef.min_x, cdef.max_x)
    con.min_y = min(cdef.min_y, cdef.max_y)
    con.max_y = max(cdef.min_y, cdef.max_y)
    con.min_z = min(cdef.min_z, cdef.max_z)
    con.max_z = max(cdef.min_z, cdef.max_z)


def _apply_copy_rotation(con, cdef, arm_obj):
    con.target = arm_obj
    if cdef.subtarget:
        con.subtarget = cdef.subtarget
    con.use_x = cdef.use_x
    con.use_y = cdef.use_y
    con.use_z = cdef.use_z
    con.mix_mode = cdef.mix_mode
    con.target_space = cdef.target_space
    con.owner_space = cdef.owner_space


def _apply_track_to(con, cdef, arm_obj):
    con.target = arm_obj
    if cdef.subtarget:
        con.subtarget = cdef.subtarget
    con.track_axis = cdef.track_axis
    con.up_axis = cdef.up_axis


def _apply_stretch_to(con, cdef, arm_obj):
    con.target = arm_obj
    if cdef.subtarget:
        con.subtarget = cdef.subtarget
    con.rest_length = cdef.rest_length
