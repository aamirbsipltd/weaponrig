"""Operator: Build weapon rig from config."""

import bpy
from pathlib import Path

from ..database.schema import WeaponConfig
from ..core.skeleton_builder import build_skeleton
from ..core.constraint_builder import apply_constraints
from ..core.driver_builder import apply_drivers


class WEAPONRIG_OT_build_rig(bpy.types.Operator):
    """Build a weapon rig from the selected weapon config"""

    bl_idname = "weaponrig.build_rig"
    bl_label = "Build Weapon Rig"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        weapon_type = context.scene.weaponrig_weapon_type
        if not weapon_type:
            self.report({"ERROR"}, "No weapon type selected")
            return {"CANCELLED"}

        config_path = WeaponConfig.configs_dir() / f"{weapon_type}.json"
        if not config_path.exists():
            self.report({"ERROR"}, f"Config not found: {config_path.name}")
            return {"CANCELLED"}

        try:
            config = WeaponConfig.load(config_path)
        except (ValueError, KeyError) as e:
            self.report({"ERROR"}, f"Invalid config: {e}")
            return {"CANCELLED"}

        # Deselect everything
        bpy.ops.object.select_all(action="DESELECT")

        # Build skeleton
        arm_obj = build_skeleton(config, context)

        # Apply constraints and drivers (armature is in OBJECT mode)
        constraint_count = apply_constraints(arm_obj, config)
        driver_count = apply_drivers(arm_obj, config)

        bone_count = len(arm_obj.data.bones)
        self.report(
            {"INFO"},
            f"Built {config.display_name}: "
            f"{bone_count} bones, {constraint_count} constraints, "
            f"{driver_count} drivers",
        )
        return {"FINISHED"}
