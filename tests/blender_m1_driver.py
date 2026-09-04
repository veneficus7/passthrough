"""Driver run inside ``blender -b`` by tests/test_passes_integration.py.

Registers the add-on from source, runs the pass-setup operator twice to prove
idempotency, then renders one frame. Findings are printed as ``PT_*`` lines for
the pytest side to parse; nothing here asserts, so a failure shows up as a
missing or wrong line rather than an opaque Blender traceback.

Not named ``test_*`` so pytest does not try to collect it.
"""

import sys

import bpy

_args = sys.argv[sys.argv.index("--") + 1 :]
ADDON_PARENT, OUTPUT_ROOT, SHOT_NAME = _args[0], _args[1], _args[2]

sys.path.insert(0, ADDON_PARENT)

import passthrough  # noqa: E402
from passthrough import pass_spec  # noqa: E402

passthrough.register()

scene = bpy.context.scene
view_layer = bpy.context.view_layer

scene.render.engine = "BLENDER_EEVEE"
scene.render.resolution_x = 64
scene.render.resolution_y = 64
scene.render.resolution_percentage = 100
scene.frame_start = 1
scene.frame_end = 1
# The main render output is not part of the section 7.3 tree; park it elsewhere
# so the shot folder contains only pass sequences. render_job.py owns this in M3.
scene.render.filepath = OUTPUT_ROOT + "/_main/main_"

scene.passthrough.output_root = OUTPUT_ROOT
scene.passthrough.shot_name = SHOT_NAME


def fingerprint(tree):
    """Name+type of every node, so a duplicate shows up as a changed string."""
    return ";".join(sorted(node.name + ":" + node.bl_idname for node in tree.nodes))


print("PT_OP1:", sorted(bpy.ops.passthrough.setup_passes()))
tree = scene.compositing_node_group
print("PT_FINGERPRINT1:", fingerprint(tree))
print("PT_LINKS1:", len(tree.links))

print("PT_OP2:", sorted(bpy.ops.passthrough.setup_passes()))
tree = scene.compositing_node_group
print("PT_FINGERPRINT2:", fingerprint(tree))
print("PT_LINKS2:", len(tree.links))

print("PT_CRYPTO_DEPTH:", view_layer.pass_cryptomatte_depth)
print(
    "PT_PASS_FLAGS:",
    ",".join(
        f"{spec.view_layer_flag}={getattr(view_layer, spec.view_layer_flag)}"
        for spec in pass_spec.PASSES
    ),
)

beauty = tree.nodes["PT_OUT_beauty"]
item = beauty.file_output_items[0]
print("PT_ITEM_COUNT:", len(beauty.file_output_items))
print("PT_ITEM_FORMAT:", item.format.file_format)
print("PT_ITEM_OVERRIDE:", item.override_node_format)
print("PT_ITEM_SAVE_AS_RENDER:", item.save_as_render)
print("PT_ITEM_NAME:", repr(item.name))
print("PT_DIRECTORY:", beauty.directory)
print("PT_FILE_NAME:", beauty.file_name)
print(
    "PT_NODE_DEPTHS:",
    ",".join(
        "{}={}/{}".format(
            spec.key,
            tree.nodes["PT_OUT_" + spec.key].format.color_depth,
            tree.nodes["PT_OUT_" + spec.key].format.exr_codec,
        )
        for spec in pass_spec.PASSES
    ),
)

bpy.ops.render.render(animation=True)
print("PT_DONE")
