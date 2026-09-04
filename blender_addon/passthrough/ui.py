"""Panels and properties.

Milestone 0 registers the container panel only. The operators, properties and
add-on preferences arrive with later milestones (SPEC.md section 8).
"""

import bpy


class PASSTHROUGH_PT_main(bpy.types.Panel):
    """Root Passthrough panel, hosted in Render Properties."""

    bl_idname = "PASSTHROUGH_PT_main"
    bl_label = "Passthrough"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "render"

    def draw(self, context):
        col = self.layout.column(align=True)
        col.label(text="Skeleton installed (M0).", icon="CHECKMARK")
        col.label(text="Pass setup arrives in M1.")


_CLASSES = (PASSTHROUGH_PT_main,)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
