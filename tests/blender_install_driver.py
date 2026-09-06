"""Install the built zip and drive it, with the source nowhere in sight.

Run inside ``blender -b`` by tests/test_install_integration.py, with
``BLENDER_USER_RESOURCES`` pointed at a throwaway directory so nothing touches
the real Blender configuration.

Every other integration test puts ``blender_addon`` on ``sys.path`` and imports
the package directly. This one deliberately does not: it installs the zip and
then works only through ``bpy.ops``, exactly as a user on a machine that has
never seen the repository would. That is M7's acceptance criterion, and it is
the only test that would catch a file the build forgot to include.
"""

import json
import sys

import addon_utils
import bpy

_args = sys.argv[sys.argv.index("--") + 1 :]
ZIP_PATH, REPO_ADDON_DIR, OUTPUT_ROOT, REPORT_PATH = _args[0], _args[1], _args[2], _args[3]

report = {"zip": ZIP_PATH}

try:
    bpy.ops.extensions.package_install_files(
        filepath=ZIP_PATH, repo="user_default", enable_on_install=True
    )
    report["install"] = "ok"
except Exception as exc:  # noqa: BLE001 - the report is the only diagnostic
    report["install"] = f"{type(exc).__name__}: {exc}"

report["modules"] = [m.__name__ for m in addon_utils.modules() if "passthrough" in m.__name__]
report["enabled"] = [addon_utils.check(name)[1] for name in report["modules"]]

# The point of this test: the repository must not be reachable.
normalised = {path.replace("\\", "/").rstrip("/").lower() for path in sys.path}
report["source_on_path"] = REPO_ADDON_DIR.replace("\\", "/").rstrip("/").lower() in normalised

report["operators"] = sorted(name for name in dir(bpy.types) if name.startswith("PASSTHROUGH_OT"))
report["panels"] = sorted(name for name in dir(bpy.types) if name.startswith("PASSTHROUGH_PT"))
report["has_scene_settings"] = hasattr(bpy.context.scene, "passthrough")

if report["has_scene_settings"]:
    settings = bpy.context.scene.passthrough
    report["templates"] = [
        item.identifier for item in settings.bl_rna.properties["template"].enum_items
    ]

    settings.template = "corridor"
    settings.output_root = OUTPUT_ROOT
    settings.shot_name = "installed"

    # Prove the schemas shipped: the generated group must carry real parameters.
    group = getattr(settings, "tpl_corridor", None)
    report["template_parameters"] = (
        sorted(p.identifier for p in group.bl_rna.properties if not p.is_readonly)
        if group is not None
        else []
    )
    if group is not None:
        group.frames = 1
        group.length = 12.0

    report["build"] = sorted(bpy.ops.passthrough.build_template())

    scene = bpy.context.scene
    scene.render.resolution_percentage = 20
    scene.frame_end = scene.frame_start

    report["diagnose"] = sorted(bpy.ops.passthrough.diagnose())
    report["setup_passes"] = sorted(bpy.ops.passthrough.setup_passes())
    bpy.ops.render.render(write_still=False)
    report["export"] = sorted(bpy.ops.passthrough.export_jsx())

    shot_dir = bpy.path.abspath(OUTPUT_ROOT).replace("\\", "/").rstrip("/") + "/installed"
    report["shot_dir"] = shot_dir
    report["jsx"] = shot_dir + "/installed.jsx"

with open(REPORT_PATH, "w", encoding="utf-8") as handle:
    json.dump(report, handle, indent=1)

print("PT_INSTALL_DONE")
