"""Driver run inside ``blender -b`` by tests/test_doctor_integration.py.

Builds a deliberately heavy scene, records the doctor's estimate, saves it, then
applies the auto-fix at a budget it cannot meet and saves that too. The pytest
side renders both and compares the estimates against measured peak memory.

Construction happens here and rendering happens in a separate process on
purpose: building a large mesh with a Blender operator spikes memory in ways
that loading the finished .blend does not, and mixing the two makes the
calibration meaningless.
"""

import json
import sys

import bpy

_args = sys.argv[sys.argv.index("--") + 1 :]
ADDON_PARENT, WORK_DIR, REPORT_PATH = _args[0], _args[1], _args[2]

sys.path.insert(0, ADDON_PARENT)

import passthrough  # noqa: E402
from passthrough import scene_capture, scene_doctor  # noqa: E402

passthrough.register()

#: Chosen so the heavy scene overshoots and the ladder has to do real work.
BUDGET = 1100 * 1024**2

TEXTURE_PATH = WORK_DIR + "/tex_4096.png"
texture = bpy.data.images.new("source", width=4096, height=4096)
texture.generated_type = "COLOR_GRID"
texture.filepath_raw = TEXTURE_PATH
texture.file_format = "PNG"
texture.save()
bpy.data.images.remove(texture)

scene = bpy.context.scene
scene.render.engine = "BLENDER_EEVEE"
scene.render.resolution_x = 1080
scene.render.resolution_y = 1920
scene.render.resolution_percentage = 100
scene.frame_start = scene.frame_end = 1
scene.world.mist_settings.use_mist = True

bpy.ops.mesh.primitive_grid_add(x_subdivisions=900, y_subdivisions=900, size=10)
grid = bpy.context.active_object

for index in range(4):
    image = bpy.data.images.load(TEXTURE_PATH, check_existing=False)
    image.name = f"heavy{index}"
    material = bpy.data.materials.new(f"mat{index}")
    material.use_nodes = True
    tree = material.node_tree
    node = tree.nodes.new("ShaderNodeTexImage")
    node.image = image
    bsdf = tree.nodes.get("Principled BSDF")
    if bsdf is not None:
        tree.links.new(node.outputs["Color"], bsdf.inputs["Base Color"])
    bpy.ops.mesh.primitive_plane_add(location=(index * 3, 0, 0))
    bpy.context.active_object.data.materials.append(material)

heavy_stats = scene_capture.capture_scene_stats(bpy.context)
heavy_report = scene_doctor.diagnose(heavy_stats, budget=BUDGET)

heavy_blend = WORK_DIR + "/heavy.blend"
bpy.ops.wm.save_as_mainfile(filepath=heavy_blend, copy=True)

applied = [scene_capture.apply_fix(bpy.context, fix) for fix in heavy_report.fixes]

fixed_stats = scene_capture.capture_scene_stats(bpy.context)
fixed_report = scene_doctor.diagnose(fixed_stats, budget=BUDGET)

fixed_blend = WORK_DIR + "/fixed.blend"
bpy.ops.wm.save_as_mainfile(filepath=fixed_blend, copy=True)

# The ladder stops as soon as the projection fits, so a texture cap alone may
# be enough and the decimate branch of apply_fix would go unexercised. Drive it
# directly against a copy of the grid so the real Blender path is covered.
decimate_before = scene_capture.evaluated_triangles(grid, bpy.context.evaluated_depsgraph_get())
scene_capture.apply_fix(
    bpy.context,
    scene_doctor.Fix(
        kind="decimate",
        description="forced",
        saves=0,
        detail={"ratio": 0.25, "objects": [grid.name]},
    ),
)
decimate_after = scene_capture.evaluated_triangles(grid, bpy.context.evaluated_depsgraph_get())

report = {
    "budget": BUDGET,
    "decimate_before": decimate_before,
    "decimate_after": decimate_after,
    "heavy_blend": heavy_blend,
    "fixed_blend": fixed_blend,
    "heavy_estimate": heavy_report.estimate.total,
    "heavy_breakdown": heavy_report.estimate.breakdown(),
    "heavy_fits": heavy_report.fits,
    "heavy_triangles": sum(o["triangles"] for o in heavy_stats["objects"]),
    "heavy_texture_sizes": sorted({t["width"] for t in heavy_stats["textures"]}),
    "fixes": [
        {"kind": f.kind, "saves": f.saves, "description": f.description} for f in heavy_report.fixes
    ],
    "applied": applied,
    "fixed_estimate": fixed_report.estimate.total,
    "fixed_fits": fixed_report.fits,
    "fixed_triangles": sum(o["triangles"] for o in fixed_stats["objects"]),
    "fixed_texture_sizes": sorted({t["width"] for t in fixed_stats["textures"]}),
    "fixed_resolution_percentage": scene.render.resolution_percentage,
}

with open(REPORT_PATH, "w", encoding="utf-8") as handle:
    json.dump(report, handle, indent=1)

print("PT_M5_DONE")
