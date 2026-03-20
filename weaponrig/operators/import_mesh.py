"""Operator: Import weapon mesh file."""

import bpy
from bpy_extras.io_utils import ImportHelper
from pathlib import Path


class WEAPONRIG_OT_import_mesh(bpy.types.Operator, ImportHelper):
    """Import a weapon mesh file (FBX, OBJ, glTF)"""

    bl_idname = "weaponrig.import_mesh"
    bl_label = "Import Weapon Mesh"
    bl_options = {"REGISTER", "UNDO"}

    filter_glob: bpy.props.StringProperty(
        default="*.fbx;*.obj;*.gltf;*.glb",
        options={"HIDDEN"},
    )

    def execute(self, context):
        filepath = Path(self.filepath)
        if not filepath.exists():
            self.report({"ERROR"}, f"File not found: {filepath}")
            return {"CANCELLED"}

        ext = filepath.suffix.lower()

        try:
            if ext == ".fbx":
                bpy.ops.import_scene.fbx(filepath=str(filepath))
            elif ext == ".obj":
                bpy.ops.wm.obj_import(filepath=str(filepath))
            elif ext in (".gltf", ".glb"):
                bpy.ops.import_scene.gltf(filepath=str(filepath))
            else:
                self.report({"ERROR"}, f"Unsupported format: {ext}")
                return {"CANCELLED"}
        except Exception as e:
            self.report({"ERROR"}, f"Import failed: {e}")
            return {"CANCELLED"}

        self.report({"INFO"}, f"Imported: {filepath.name}")
        return {"FINISHED"}
