"""Driver run inside ``blender -b`` by tests/test_camera_integration.py.

Builds an orbiting, constraint-driven camera, exports the .jsx through the real
operator, and dumps a JSON report containing:

* Blender's own projection of known world points, via ``world_to_camera_view``
* the After Effects camera parameters this add-on derived for each frame
* the After Effects position of those same world points

The pytest side then projects the points through the AE parameters and checks
the pixels agree. That is the numeric half of SPEC.md section 7.2's
verification test.

The camera is driven by a parent empty plus a Track To constraint on purpose,
so the depsgraph evaluation path is exercised rather than a bare transform.
"""

import json
import math
import sys

import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Euler, Vector

_args = sys.argv[sys.argv.index("--") + 1 :]
ADDON_PARENT, OUTPUT_ROOT, REPORT_PATH = _args[0], _args[1], _args[2]

sys.path.insert(0, ADDON_PARENT)

import passthrough  # noqa: E402
from passthrough import camera_convert, scene_capture  # noqa: E402

passthrough.register()

FRAME_START, FRAME_END = 1, 9
POINTS = [
    (0.0, 0.0, 0.0),
    (1.0, 0.0, 0.0),
    (0.0, 1.0, 0.0),
    (0.0, 0.0, 1.0),
    (-1.5, 0.8, 0.4),
    (0.7, -1.2, -0.6),
]

scene = bpy.context.scene
scene.render.engine = "BLENDER_EEVEE"
scene.render.resolution_x = 1080
scene.render.resolution_y = 1920
scene.render.resolution_percentage = 100
scene.render.fps = 24
scene.render.fps_base = 1.0
scene.frame_start = FRAME_START
scene.frame_end = FRAME_END

# Orbit rig: an empty at the origin spins a full turn, the camera hangs off it
# and is aimed back at the centre by a constraint.
pivot = bpy.data.objects.new("PT_Pivot", None)
scene.collection.objects.link(pivot)
# A key on every frame, so the sampled value is exact whatever the
# interpolation is. Blender 5 moved fcurves to
# action.layers[0].strips[0].channelbags[0].fcurves (slotted actions), and
# Action.fcurves no longer exists -- this avoids needing either path.
_span = FRAME_END - FRAME_START
for frame in range(FRAME_START, FRAME_END + 1):
    turn = 360.0 * (frame - FRAME_START) / _span
    pivot.rotation_euler = Euler((0.0, 0.0, math.radians(turn)), "XYZ")
    pivot.keyframe_insert("rotation_euler", frame=frame)

camera = scene.camera
camera.parent = pivot
camera.location = (8.0, 0.0, 3.0)
camera.rotation_euler = (0.0, 0.0, 0.0)
camera.data.lens = 50.0
camera.data.sensor_width = 36.0
camera.data.sensor_fit = "AUTO"
track = camera.constraints.new("TRACK_TO")
track.target = pivot
track.track_axis = "TRACK_NEGATIVE_Z"
track.up_axis = "UP_Y"

scene.passthrough.output_root = OUTPUT_ROOT
scene.passthrough.shot_name = "orbit"

width, height = scene_capture.render_dimensions(scene)

frames = []
euler_matrix_error = 0.0
for frame in range(FRAME_START, FRAME_END + 1):
    scene.frame_set(frame)
    evaluated = camera.evaluated_get(bpy.context.evaluated_depsgraph_get())
    rows = scene_capture.matrix_rows(evaluated.matrix_world)

    # Does the pure Euler port rebuild the same rotation mathutils would?
    mine = camera_convert.to_euler_zyx(rows)
    rebuilt = Euler(mine, "ZYX").to_matrix()
    actual = evaluated.matrix_world.to_3x3().normalized()
    euler_matrix_error = max(
        euler_matrix_error,
        max(abs(rebuilt[r][c] - actual[r][c]) for r in range(3) for c in range(3)),
    )

    frames.append(
        {
            "frame": frame,
            "zoom": camera_convert.zoom_from_lens(
                evaluated.data.lens,
                evaluated.data.sensor_fit,
                evaluated.data.sensor_width,
                evaluated.data.sensor_height,
                width,
                height,
            ),
            "cam_pos": list(
                camera_convert.convert_position(camera_convert.to_translation(rows), width, height)
            ),
            "cam_orientation": list(
                camera_convert.convert_orientation(
                    camera_convert.to_euler_zyx(rows), x_rot_correction=True
                )
            ),
            "points": [
                {
                    "world": list(p),
                    "blender_px": [
                        world_to_camera_view(scene, evaluated, Vector(p)).x * width,
                        (1.0 - world_to_camera_view(scene, evaluated, Vector(p)).y) * height,
                    ],
                    "ae_pos": list(camera_convert.convert_position(p, width, height)),
                }
                for p in POINTS
            ],
        }
    )

comp, camera_data = scene_capture.capture_camera(bpy.context)
result = bpy.ops.passthrough.export_jsx()

report = {
    "width": width,
    "height": height,
    "frame_start": FRAME_START,
    "frame_end": FRAME_END,
    "euler_matrix_error": euler_matrix_error,
    "frames": frames,
    "comp": comp,
    "orientation_track": [list(o) for o in camera_data["orientation"]],
    "operator_result": sorted(result),
    "jsx_path": scene_capture.jsx_output_path(scene),
}
with open(REPORT_PATH, "w", encoding="utf-8") as handle:
    json.dump(report, handle, indent=1)

print("PT_M2_DONE")
