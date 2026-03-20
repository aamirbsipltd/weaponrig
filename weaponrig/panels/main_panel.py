"""N-panel UI for WeaponRig addon."""

import bpy


class WEAPONRIG_PT_main(bpy.types.Panel):
    """WeaponRig main panel in the 3D Viewport sidebar"""

    bl_label = "WeaponRig"
    bl_idname = "WEAPONRIG_PT_main"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "WeaponRig"

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        # -- Section 1: Import ---------------------------------------------
        box = layout.box()
        box.label(text="1. Import", icon="IMPORT")
        box.operator("weaponrig.import_mesh", text="Import Weapon Mesh")

        # -- Section 2: Weapon Type ----------------------------------------
        box = layout.box()
        box.label(text="2. Weapon Type", icon="PREFERENCES")
        box.prop(scene, "weaponrig_weapon_type", text="")

        # -- Section 3: Build Rig ------------------------------------------
        box = layout.box()
        box.label(text="3. Build Rig", icon="ARMATURE_DATA")
        box.operator("weaponrig.build_rig", text="Build Skeleton + Drivers")

        # -- Section 4: Status (shown if an active rig exists) -------------
        active = context.active_object
        if active and active.type == "ARMATURE" and active.get("weaponrig_config"):
            box = layout.box()
            box.label(text="4. Rig Info", icon="INFO")
            box.label(text=f"Config: {active['weaponrig_config']}")
            box.label(text=f"Bones: {len(active.data.bones)}")
