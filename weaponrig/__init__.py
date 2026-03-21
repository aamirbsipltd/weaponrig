"""WeaponRig — Guided weapon rigging assistant for FPS games."""

bl_info = {
    "name": "WeaponRig",
    "author": "Aamir Farrukh",
    "version": (0, 2, 0),
    "blender": (4, 0, 0),
    "location": "View3D > Sidebar > WeaponRig",
    "description": "Guided weapon rigging assistant for FPS games",
    "category": "Rigging",
}


def _weapon_type_items(self, context):
    from .database.schema import WeaponConfig

    items = []
    for identifier, display_name, description in WeaponConfig.list_configs():
        items.append((identifier, display_name, description))
    if not items:
        items.append(("NONE", "No configs found", ""))
    return items


def register():
    import bpy
    from .operators.add_bone import WEAPONRIG_OT_add_bone, WEAPONRIG_OT_select_bone
    from .operators.import_mesh import WEAPONRIG_OT_import_mesh
    from .panels.main_panel import WEAPONRIG_PT_main

    for cls in (WEAPONRIG_OT_add_bone, WEAPONRIG_OT_select_bone, WEAPONRIG_OT_import_mesh, WEAPONRIG_PT_main):
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
    import bpy
    from .operators.add_bone import WEAPONRIG_OT_add_bone, WEAPONRIG_OT_select_bone
    from .operators.import_mesh import WEAPONRIG_OT_import_mesh
    from .panels.main_panel import WEAPONRIG_PT_main

    del bpy.types.Scene.weaponrig_added_bones
    del bpy.types.Scene.weaponrig_weapon_type

    for cls in (WEAPONRIG_PT_main, WEAPONRIG_OT_import_mesh, WEAPONRIG_OT_select_bone, WEAPONRIG_OT_add_bone):
        bpy.utils.unregister_class(cls)
