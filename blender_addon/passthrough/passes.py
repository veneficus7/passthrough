"""View layer pass configuration and the compositor File Output tree.

Everything here is written against Blender 5.x, whose compositor differs from
older releases in ways that matter (all verified against 5.1.2):

* The scene's tree lives on ``scene.compositing_node_group``, a node group
  datablock. ``scene.node_tree`` is gone and ``scene.use_nodes`` is deprecated
  for removal in 6.0, so neither is touched here.
* ``CompositorNodeComposite`` no longer exists.
* A File Output node writes exactly *one* file. Its ``file_output_items``
  become layers inside that file, and the node-level format enum accepts only
  ``OPEN_EXR_MULTILAYER``. Getting the one-sequence-per-pass layout of
  section 7.3 therefore means **one File Output node per pass**, each holding a
  single item whose format overrides the node's.
* ``base_path``/``file_slots`` were renamed ``directory``/``file_output_items``.
"""

import bpy

from . import pass_spec

#: Node names are the idempotency key: the operator looks these up and updates
#: them in place rather than adding a second copy (M1 acceptance).
RENDER_LAYERS_NODE = "PT_RENDER_LAYERS"
OUTPUT_NODE_PREFIX = "PT_OUT_"
NODE_GROUP_PREFIX = "PT_Comp_"


def is_eevee(engine_id):
    """True for any EEVEE engine id.

    Blender 5.1 reports ``BLENDER_EEVEE``; 4.2-4.5 reported
    ``BLENDER_EEVEE_NEXT``. Matching on the prefix keeps this correct either way.
    """
    return bool(engine_id) and engine_id.startswith("BLENDER_EEVEE")


def configure_view_layer(view_layer):
    """Turn on exactly the passes in the manifest and set cryptomatte depth."""
    for spec in pass_spec.PASSES:
        setattr(view_layer, spec.view_layer_flag, True)
    view_layer.pass_cryptomatte_depth = pass_spec.CRYPTOMATTE_DEPTH


def ensure_node_tree(scene):
    """Return the scene's compositing node group, creating one if needed.

    An existing group is reused rather than replaced, so this never discards
    compositing work the user already has in the scene.
    """
    tree = scene.compositing_node_group
    if tree is None:
        tree = bpy.data.node_groups.new(NODE_GROUP_PREFIX + scene.name, "CompositorNodeTree")
        scene.compositing_node_group = tree
    return tree


def _ensure_node(tree, name, bl_idname):
    """Fetch the node called ``name``, or create it. Wrong type is replaced."""
    node = tree.nodes.get(name)
    if node is not None and node.bl_idname != bl_idname:
        tree.nodes.remove(node)
        node = None
    if node is None:
        node = tree.nodes.new(bl_idname)
        node.name = name
    return node


def ensure_render_layers_node(tree, scene, view_layer):
    node = _ensure_node(tree, RENDER_LAYERS_NODE, "CompositorNodeRLayers")
    node.label = "Passthrough Render Layers"
    node.scene = scene
    node.layer = view_layer.name
    node.location = (0, 0)
    return node


def ensure_output_node(tree, spec, output_root, shot_name, index):
    """Create or update the File Output node that writes one pass.

    Two non-obvious things, both established by reading the EXR headers Blender
    actually wrote rather than by trusting the RNA:

    * ``color_depth`` and ``exr_codec`` are read from the **node** format even
      when an item overrides the file format. Setting them on the item is
      silently ignored, which yields 32-bit uncompressed files.
    * The item is left unnamed, because its name becomes an EXR layer prefix.
    """
    node = _ensure_node(tree, OUTPUT_NODE_PREFIX + spec.key, "CompositorNodeOutputFile")
    node.label = "Passthrough " + spec.label
    node.directory = pass_spec.pass_dir(output_root, shot_name, spec.key)
    node.file_name = pass_spec.frame_pattern(spec.key)
    node.format.color_depth = spec.color_depth
    node.format.exr_codec = pass_spec.EXR_CODEC
    # Linear EXR, never the view transform (section 7.4). Baking AgX into a
    # pass is the "everything looks muddy" failure.
    node.save_as_render = False
    node.location = (400, -index * 180)

    items = node.file_output_items
    if len(items) != 1 or items[0].name != pass_spec.OUTPUT_ITEM_NAME:
        items.clear()
        items.new("RGBA", pass_spec.OUTPUT_ITEM_NAME)
    item = items[0]
    item.override_node_format = True
    item.format.file_format = "OPEN_EXR"
    item.format.color_mode = "RGBA"
    item.save_as_render = False
    return node


def build_output_tree(scene, view_layer, output_root, shot_name):
    """Wire every pass to its own File Output node. Safe to run repeatedly.

    Returns ``(nodes, missing_sockets)``.
    """
    tree = ensure_node_tree(scene)
    render_layers = ensure_render_layers_node(tree, scene, view_layer)

    nodes = []
    missing = []
    for index, spec in enumerate(pass_spec.PASSES):
        node = ensure_output_node(tree, spec, output_root, shot_name, index)
        nodes.append(node)
        socket = render_layers.outputs.get(spec.socket)
        if socket is None:
            # The socket only exists once the pass is enabled and the node has
            # refreshed; a missing one means the pass did not survive.
            missing.append(spec.socket)
            continue
        tree.links.new(socket, node.inputs[0])
    return nodes, missing


class PASSTHROUGH_OT_setup_passes(bpy.types.Operator):
    """Configure render passes and build the File Output tree for this scene."""

    bl_idname = "passthrough.setup_passes"
    bl_label = "Set Up Passes"
    bl_description = (
        "Enable the Passthrough render passes and wire one File Output node per "
        "pass. Running this again updates the existing nodes"
    )
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        settings = scene.passthrough

        if not settings.output_root:
            self.report({"ERROR"}, "Set an output root before setting up passes")
            return {"CANCELLED"}

        if not is_eevee(scene.render.engine):
            self.report(
                {"WARNING"},
                f"Passthrough targets EEVEE; this scene uses {scene.render.engine}",
            )

        shot = pass_spec.sanitize_shot_name(settings.shot_name)
        configure_view_layer(context.view_layer)
        nodes, missing = build_output_tree(scene, context.view_layer, settings.output_root, shot)

        if missing:
            self.report({"WARNING"}, "Passes with no socket: " + ", ".join(missing))
        self.report(
            {"INFO"},
            f"{len(nodes) - len(missing)} passes -> "
            f"{pass_spec.shot_dir(settings.output_root, shot)}",
        )
        return {"FINISHED"}


_CLASSES = (PASSTHROUGH_OT_setup_passes,)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
