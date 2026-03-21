"""Operator to add a single bone from the weapon config."""

import json

import bpy

from ..core.skeleton_builder import add_single_bone, get_or_create_armature
from ..database.schema import WeaponConfig


class WEAPONRIG_OT_add_bone(bpy.types.Operator):
    """Add the next weapon bone at the 3D cursor position"""
    bl_idname = "weaponrig.add_bone"
    bl_label = "Add Bone"
    bl_options = {"REGISTER", "UNDO"}

    bone_name: bpy.props.StringProperty(name="Bone Name")
    use_selection: bpy.props.BoolProperty(name="Use Selection", default=False)

    def execute(self, context):
        weapon_type = context.scene.weaponrig_weapon_type
        config = _load_config(weapon_type)
        if config is None:
            self.report({"ERROR"}, f"Cannot load config: {weapon_type}")
            return {"CANCELLED"}

        bone_name = self.bone_name
        if not bone_name:
            bone_name = _get_next_bone(config, context)
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

        # Track added bones
        added = _get_added_list(context)
        if bone_name not in added:
            added.append(bone_name)
            context.scene.weaponrig_added_bones = json.dumps(added)

        # Build report message
        msg = f"Added: {info['name']}"
        if info.get("constraints_added"):
            msg += f" ({info['constraints_added']} constraints)"
        if info.get("drivers_added"):
            msg += f" ({info['drivers_added']} drivers)"
        if info.get("description"):
            msg += f"\n{info['description']}"

        self.report({"INFO"}, msg)

        # Select the armature and the new bone
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


def _load_config(weapon_type):
    """Load weapon config by identifier."""
    try:
        config_path = WeaponConfig.configs_dir() / f"{weapon_type}.json"
        return WeaponConfig.load(config_path)
    except Exception:
        return None


def _get_added_list(context):
    """Get list of already-added bone names."""
    raw = context.scene.weaponrig_added_bones
    if not raw:
        return []
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return []


def _get_next_bone(config, context):
    """Return the name of the next bone to add, following config order."""
    added = set(_get_added_list(context))
    for bone_def in config.bones:
        if bone_def.name not in added:
            return bone_def.name
    return None


def _selection_centroid(context):
    """Compute centroid of selected vertices or objects."""
    from mathutils import Vector

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
