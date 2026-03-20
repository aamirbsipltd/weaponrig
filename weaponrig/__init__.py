"""WeaponRig — Automated weapon rigging pipeline for FPS games."""

bl_info = {
    "name": "WeaponRig",
    "author": "Aamir",
    "version": (0, 1, 0),
    "blender": (4, 0, 0),
    "location": "View3D > Sidebar > WeaponRig",
    "description": "Automated weapon rigging for FPS games",
    "category": "Rigging",
}


def _weapon_type_items(self, context):
    """Dynamically populate weapon type dropdown from available configs."""
    from .database.schema import WeaponConfig

    items = []
    for identifier, display_name, description in WeaponConfig.list_configs():
        items.append((identifier, display_name, description))
    if not items:
        items.append(("NONE", "No configs found", ""))
    return items


def register():
    import bpy
    from .operators.build_rig import WEAPONRIG_OT_build_rig
    from .operators.import_mesh import WEAPONRIG_OT_import_mesh
    from .panels.main_panel import WEAPONRIG_PT_main

    for cls in (WEAPONRIG_OT_build_rig, WEAPONRIG_OT_import_mesh, WEAPONRIG_PT_main):
        bpy.utils.register_class(cls)

    bpy.types.Scene.weaponrig_weapon_type = bpy.props.EnumProperty(
        name="Weapon Type",
        description="Select the weapon operating system",
        items=_weapon_type_items,
    )


def unregister():
    import bpy
    from .operators.build_rig import WEAPONRIG_OT_build_rig
    from .operators.import_mesh import WEAPONRIG_OT_import_mesh
    from .panels.main_panel import WEAPONRIG_PT_main

    del bpy.types.Scene.weaponrig_weapon_type

    for cls in (WEAPONRIG_PT_main, WEAPONRIG_OT_import_mesh, WEAPONRIG_OT_build_rig):
        bpy.utils.unregister_class(cls)
