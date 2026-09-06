"""Driver run inside ``blender -b`` by tests/test_template_integration.py.

Walks every template through the exact sequence a user has in the panel, using
only the operators the panel exposes and the properties it shows:

    pick a template -> Build Scene -> Set Up Passes -> render -> Export Script

Nothing here opens the shader editor, the compositor or the node graph, which is
M6's acceptance criterion. It then measures the rendered passes, because a
template that produces a black frame has not really produced a shot.
"""

import json
import sys

import bpy
import numpy as np

_args = sys.argv[sys.argv.index("--") + 1 :]
ADDON_PARENT, OUTPUT_ROOT, REPORT_PATH = _args[0], _args[1], _args[2]

sys.path.insert(0, ADDON_PARENT)

import passthrough  # noqa: E402
from passthrough import pass_spec, scene_capture, template_build, template_spec  # noqa: E402

passthrough.register()

#: The templates render at 1080x1920; a quarter of that keeps the test honest
#: about the pipeline while staying quick.
TEST_PERCENTAGE = 25


def pass_statistics(path):
    image = bpy.data.images.load(path)
    try:
        buffer = np.empty(len(image.pixels), dtype=np.float32)
        image.pixels.foreach_get(buffer)
        rgb = buffer.reshape(-1, 4)[:, :3]
        return {
            "min": float(rgb.min()),
            "max": float(rgb.max()),
            "mean": float(rgb.mean()),
            "nonzero_fraction": float((rgb != 0).mean()),
            # Contrast is what separates a real shot from a flat wall. Checking
            # only that pixels are non-black passed a frame that was one
            # uniform grey, which is how a broken template slipped through.
            "std": float(rgb.std()),
        }
    finally:
        bpy.data.images.remove(image)


results = {}
templates = template_spec.load_templates()

for key, template in templates.items():
    scene = bpy.context.scene
    settings = scene.passthrough
    settings.template = key
    settings.output_root = OUTPUT_ROOT
    settings.shot_name = key

    build_result = sorted(bpy.ops.passthrough.build_template())
    scene = bpy.context.scene
    first_object_count = len(bpy.data.collections[template_build.COLLECTION_NAME].objects)
    bpy.ops.passthrough.build_template()
    scene = bpy.context.scene
    rebuilt_object_count = len(bpy.data.collections[template_build.COLLECTION_NAME].objects)

    # Only after the template has set the real resolution, so the ratio and the
    # camera framing stay exactly as a user would get them.
    scene.render.resolution_percentage = TEST_PERCENTAGE
    scene.frame_end = scene.frame_start

    passes_result = sorted(bpy.ops.passthrough.setup_passes())
    bpy.ops.render.render(write_still=False)
    export_result = sorted(bpy.ops.passthrough.export_jsx())

    collection = bpy.data.collections.get(template_build.COLLECTION_NAME)
    statistics = {}
    for spec in pass_spec.PASSES:
        path = pass_spec.frame_path(bpy.path.abspath(OUTPUT_ROOT), key, spec.key, scene.frame_start)
        statistics[spec.key] = pass_statistics(path)

    results[key] = {
        "name": template.name,
        "build_result": build_result,
        "passes_result": passes_result,
        "export_result": export_result,
        "objects": len(collection.objects),
        "first_object_count": first_object_count,
        "rebuilt_object_count": rebuilt_object_count,
        "scene_objects": len(scene.objects),
        "meshes": len([o for o in collection.objects if o.type in ("MESH", "FONT")]),
        "lights": len([o for o in collection.objects if o.type == "LIGHT"]),
        "cameras": len([o for o in collection.objects if o.type == "CAMERA"]),
        "has_active_camera": scene.camera is not None,
        "resolution": [scene.render.resolution_x, scene.render.resolution_y],
        "frames": scene.frame_end - scene.frame_start + 1,
        "jsx_path": scene_capture.jsx_output_path(scene),
        "shot_dir": pass_spec.shot_dir(bpy.path.abspath(OUTPUT_ROOT), key),
        "pass_statistics": statistics,
        "parameters": [p.key for p in template.parameters],
    }

with open(REPORT_PATH, "w", encoding="utf-8") as handle:
    json.dump(results, handle, indent=1)

print("PT_M6_DONE")
