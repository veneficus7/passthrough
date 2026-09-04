"""Add-on preferences.

SPEC.md section 6 lists the AE project directory, pixels-per-unit and the RAM
budget here. Only pixels-per-unit exists so far; the other two belong to
milestones that have not been built.
"""

import bpy

from . import camera_convert


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

    def draw(self, context):
        self.layout.prop(self, "pixels_per_unit")


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
