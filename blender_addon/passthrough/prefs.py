"""Add-on preferences.

SPEC.md section 6 lists the AE project directory, pixels-per-unit and the RAM
budget here. The AE project directory belongs to a milestone that has not been
built.
"""

import bpy

from . import camera_convert, scene_doctor


class PassthroughPreferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    pixels_per_unit: bpy.props.FloatProperty(
        name="Pixels per Blender Unit",
        description=(
            "Scale between Blender metres and After Effects pixels. 100 matches "
            "Blender's own After Effects exporter, so scenes arrive the size AE "
            "users expect"
        ),
        default=camera_convert.DEFAULT_PIXELS_PER_UNIT,
        min=0.001,
        soft_min=1.0,
        soft_max=1000.0,
    )

    memory_budget_gb: bpy.props.FloatProperty(
        name="Memory Budget (GB)",
        description=(
            "Ceiling the scene doctor checks against. 6 GB is what SPEC.md M3 "
            "allows: 16 GB of RAM, roughly 11 GB usable, and After Effects wants "
            "the rest"
        ),
        default=scene_doctor.DEFAULT_BUDGET_BYTES / (1024**3),
        min=0.5,
        soft_max=32.0,
    )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "pixels_per_unit")
        layout.prop(self, "memory_budget_gb")


def memory_budget(context):
    """Budget in bytes, falling back to the default when uninstalled."""
    try:
        gigabytes = context.preferences.addons[__package__].preferences.memory_budget_gb
        return int(gigabytes * 1024**3)
    except (KeyError, AttributeError):
        return scene_doctor.DEFAULT_BUDGET_BYTES


def pixels_per_unit(context):
    """Preference value, falling back to the default.

    The fallback matters: when the add-on is loaded straight from ``sys.path``
    rather than installed as an extension -- which is how the integration tests
    run it -- there is no preferences entry to read.
    """
    try:
        return context.preferences.addons[__package__].preferences.pixels_per_unit
    except (KeyError, AttributeError):
        return camera_convert.DEFAULT_PIXELS_PER_UNIT


_CLASSES = (PassthroughPreferences,)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
