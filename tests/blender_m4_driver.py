"""Driver run inside ``blender -b`` by tests/test_import_integration.py.

Builds a scene with two empties, renders the passes for real, exports the .jsx,
and reports where everything went. The pytest side then checks the script
describes what is actually on disk.
"""

import json
import math
import sys

import bpy
from mathutils import Euler

_args = sys.argv[sys.argv.index("--") + 1 :]
ADDON_PARENT, OUTPUT_ROOT, REPORT_PATH = _args[0], _args[1], _args[2]

sys.path.insert(0, ADDON_PARENT)

import passthrough  # noqa: E402
from passthrough import pass_spec, scene_capture  # noqa: E402

passthrough.register()

FRAME_START, FRAME_END = 1, 3
SHOT = "importme"

scene = bpy.context.scene
scene.render.engine = "BLENDER_EEVEE"
scene.render.resolution_x = 160
scene.render.resolution_y = 240
scene.render.resolution_percentage = 100
scene.render.fps = 24
scene.render.fps_base = 1.0
scene.frame_start = FRAME_START
scene.frame_end = FRAME_END
scene.world.mist_settings.use_mist = True

# One empty that moves, one that does not, so the collapse behaviour is covered.
moving = bpy.data.objects.new("TrackMoving", None)
scene.collection.objects.link(moving)
for frame in range(FRAME_START, FRAME_END + 1):
    moving.location = (frame * 0.5, 0.0, 1.0)
    moving.rotation_euler = Euler((0.0, 0.0, math.radians(frame * 15.0)), "XYZ")
    moving.keyframe_insert("location", frame=frame)
    moving.keyframe_insert("rotation_euler", frame=frame)

static = bpy.data.objects.new("TrackStatic", None)
static.location = (-2.0, 1.0, 0.5)
scene.collection.objects.link(static)

scene.passthrough.output_root = OUTPUT_ROOT
scene.passthrough.shot_name = SHOT

setup = sorted(bpy.ops.passthrough.setup_passes())

for frame in range(FRAME_START, FRAME_END + 1):
    scene.frame_set(frame)
    bpy.ops.render.render(write_still=False)

export = sorted(bpy.ops.passthrough.export_jsx())
comp, camera, passes, nulls = scene_capture.capture_shot(bpy.context)

report = {
    "setup_result": setup,
    "export_result": export,
    "jsx_path": scene_capture.jsx_output_path(scene),
    "shot_dir": pass_spec.shot_dir(bpy.path.abspath(OUTPUT_ROOT), SHOT),
    "comp": comp,
    "passes": passes,
    "null_names": [entry["name"] for entry in nulls],
    "null_track_lengths": {
        entry["name"]: {
            "position": len(entry["position"]),
            "orientation": len(entry["orientation"]),
        }
        for entry in nulls
    },
    "frame_start": FRAME_START,
    "frame_end": FRAME_END,
}

with open(REPORT_PATH, "w", encoding="utf-8") as handle:
    json.dump(report, handle, indent=1)

print("PT_M4_DONE")
