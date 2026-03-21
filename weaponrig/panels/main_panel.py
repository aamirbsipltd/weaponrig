"""WeaponRig N-panel — guided bone-by-bone rigging workflow."""

import json

import bpy

from ..database.schema import WeaponConfig


def _load_config(weapon_type):
    try:
        config_path = WeaponConfig.configs_dir() / f"{weapon_type}.json"
        return WeaponConfig.load(config_path)
    except Exception:
        return None


def _get_added_list(context):
    raw = context.scene.weaponrig_added_bones
    if not raw:
        return []
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return []


def _wrap_text(layout, text, width=40):
    """Draw word-wrapped text labels."""
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
        config = _load_config(weapon_type)
        if config is None:
            layout.label(text="No config loaded", icon="ERROR")
            return

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

        # Progress bar
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

            # Parameter highlights
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

            # Add buttons
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
