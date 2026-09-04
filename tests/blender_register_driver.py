"""Report what the add-on registers. Run inside ``blender -b``.

Consolidates the registration checks that were previously run by hand once per
milestone.
"""

import json
import sys

import bpy

_args = sys.argv[sys.argv.index("--") + 1 :]
ADDON_PARENT, REPORT_PATH = _args[0], _args[1]

sys.path.insert(0, ADDON_PARENT)

import passthrough  # noqa: E402
from passthrough import scene_capture  # noqa: E402

passthrough.register()


def registered(prefix):
    return sorted(name for name in dir(bpy.types) if name.startswith(prefix))


operator_properties = {}
for name in registered("PASSTHROUGH_OT"):
    idname = getattr(bpy.types, name).bl_idname
    module, _, func = idname.partition(".")
    rna = getattr(getattr(bpy.ops, module), func).get_rna_type()
    operator_properties[idname] = sorted(
        prop.identifier for prop in rna.properties if not prop.is_readonly
    )

report = {
    "operators": registered("PASSTHROUGH_OT"),
    "panels": registered("PASSTHROUGH_PT"),
    "operator_properties": operator_properties,
    "scene_property": hasattr(bpy.context.scene, "passthrough"),
    "scene_property_fields": sorted(
        prop.identifier
        for prop in bpy.context.scene.passthrough.bl_rna.properties
        if not prop.is_readonly
    ),
    "render_script_exists": bool(scene_capture.render_script_path()),
    "panel_contexts": {
        name: getattr(bpy.types, name).bl_context for name in registered("PASSTHROUGH_PT")
    },
}

passthrough.unregister()
report["clean_after_unregister"] = {
    "operators": registered("PASSTHROUGH_OT"),
    "panels": registered("PASSTHROUGH_PT"),
}

# Registering twice in a row must work, or reloading the add-on breaks.
passthrough.register()
passthrough.unregister()
report["second_cycle_ok"] = True

with open(REPORT_PATH, "w", encoding="utf-8") as handle:
    json.dump(report, handle, indent=1)

print("PT_REG_DONE")
