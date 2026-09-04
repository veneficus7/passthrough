"""Write a small fixture .blend for the M3 integration tests.

Run as ``blender -b --factory-startup --python blender_make_scene.py -- <path>``.
"""

import sys

import bpy

path = sys.argv[sys.argv.index("--") + 1]

scene = bpy.context.scene
scene.render.engine = "BLENDER_EEVEE"
scene.render.resolution_x = 240
scene.render.resolution_y = 320
scene.render.resolution_percentage = 100
scene.render.fps = 24
scene.world.mist_settings.use_mist = True
scene.world.mist_settings.start = 2.0
scene.world.mist_settings.depth = 20.0

bpy.ops.wm.save_as_mainfile(filepath=path)
print("PT_SCENE_SAVED")
