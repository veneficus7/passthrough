"""Build shot scenes from the template schemas.

The Blender half of M6. Every scene is constructed here in Python from a
validated parameter dict, so nothing the user needs is hidden in a binary
``.blend`` and nothing requires opening the shader editor or the node graph --
which is exactly what M6's acceptance criterion asks for.

Everything a template creates goes into one collection. Rebuilding empties that
collection first, so pressing Build twice gives the same scene rather than two
overlapping ones.
"""

import math
import random

import bpy

from . import template_spec

#: Everything a template builds lives here, so a rebuild can clear it.
COLLECTION_NAME = "PT Template"

#: Portrait, per SPEC.md Appendix B.
RESOLUTION = (1080, 1920)


# --- scaffolding -------------------------------------------------------------


def clear_template(scene):
    """Delete the template collection and everything in it."""
    collection = bpy.data.collections.get(COLLECTION_NAME)
    if collection is None:
        return
    # Removing the objects is enough to stop them rendering; Blender drops the
    # now-unused meshes, lights and cameras when the file is saved.
    for obj in list(collection.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    bpy.data.collections.remove(collection)


def clear_scene_objects(scene):
    """Remove everything left in the scene.

    Without this the startup file's cube sits in the middle of every template,
    which is exactly the kind of thing a user with no Blender knowledge has no
    way to diagnose. Called only when the operator asks for it.
    """
    for obj in list(scene.objects):
        bpy.data.objects.remove(obj, do_unlink=True)


def template_collection(scene):
    collection = bpy.data.collections.new(COLLECTION_NAME)
    scene.collection.children.link(collection)
    return collection


def place(obj, collection):
    """Move a freshly created object into the template collection."""
    for existing in list(obj.users_collection):
        existing.objects.unlink(obj)
    collection.objects.link(obj)
    return obj


def add_mesh(collection, kind, **kwargs):
    getattr(bpy.ops.mesh, kind)(**kwargs)
    return place(bpy.context.active_object, collection)


def surface_material(name, color, roughness=0.6, emission=None, emission_strength=0.0):
    """A Principled BSDF, wired up so the user never opens the shader editor."""
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    bsdf = material.node_tree.nodes.get("Principled BSDF")
    if bsdf is not None:
        bsdf.inputs["Base Color"].default_value = (*color, 1.0)
        bsdf.inputs["Roughness"].default_value = roughness
        if emission is not None and "Emission Color" in bsdf.inputs:
            bsdf.inputs["Emission Color"].default_value = (*emission, 1.0)
            bsdf.inputs["Emission Strength"].default_value = emission_strength
    return material


def emission_material(name, color, strength):
    """A pure emitter. This is what shows up in the emission pass."""
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    tree = material.node_tree
    tree.nodes.clear()
    emit = tree.nodes.new("ShaderNodeEmission")
    emit.inputs["Color"].default_value = (*color, 1.0)
    emit.inputs["Strength"].default_value = strength
    output = tree.nodes.new("ShaderNodeOutputMaterial")
    tree.links.new(emit.outputs["Emission"], output.inputs["Surface"])
    return material


def setup_world(scene, fog_density=0.0, background=(0.02, 0.02, 0.025), extent=40.0):
    """Background colour, volumetric fog and the mist pass range."""
    world = bpy.data.worlds.new("PT World")
    world.use_nodes = True
    tree = world.node_tree
    tree.nodes.clear()
    output = tree.nodes.new("ShaderNodeOutputWorld")

    background_node = tree.nodes.new("ShaderNodeBackground")
    background_node.inputs["Color"].default_value = (*background, 1.0)
    background_node.inputs["Strength"].default_value = 1.0
    tree.links.new(background_node.outputs["Background"], output.inputs["Surface"])

    if fog_density > 0.0:
        scatter = tree.nodes.new("ShaderNodeVolumeScatter")
        scatter.inputs["Density"].default_value = fog_density
        tree.links.new(scatter.outputs["Volume"], output.inputs["Volume"])

    scene.world = world
    # The mist pass is meaningless without a range that covers the scene.
    world.mist_settings.use_mist = True
    world.mist_settings.start = 0.5
    world.mist_settings.depth = max(1.0, extent)

    scene.eevee.volumetric_start = 0.1
    scene.eevee.volumetric_end = max(10.0, extent * 1.5)
    # Without this a spot light in fog is just a glow: the shaft only appears
    # once the volume is shadowed by the geometry the light passes through.
    scene.eevee.use_volumetric_shadows = True
    scene.eevee.volumetric_samples = 96
    return world


def setup_render(scene, frames):
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x, scene.render.resolution_y = RESOLUTION
    scene.render.resolution_percentage = 100
    scene.render.fps = 24
    scene.render.fps_base = 1.0
    scene.frame_start = 1
    scene.frame_end = max(1, int(frames))
    scene.frame_set(1)


def add_camera(collection, scene, location, target_location=(0.0, 0.0, 0.0), lens=50.0):
    """A camera aimed at a target empty, so the user never sets a rotation."""
    target = bpy.data.objects.new("PT Target", None)
    target.location = target_location
    target.empty_display_size = 0.4
    place(target, collection)

    camera_data = bpy.data.cameras.new("PT Camera")
    camera_data.lens = lens
    camera_data.sensor_fit = "AUTO"
    camera = bpy.data.objects.new("PT Camera", camera_data)
    camera.location = location
    place(camera, collection)

    track = camera.constraints.new("TRACK_TO")
    track.target = target
    track.track_axis = "TRACK_NEGATIVE_Z"
    track.up_axis = "UP_Y"

    scene.camera = camera
    return camera, target


def keyframe_location(obj, frames):
    """``frames`` is ``[(frame, (x, y, z)), ...]``."""
    for frame, location in frames:
        obj.location = location
        obj.keyframe_insert("location", frame=frame)


def keyframe_rotation(obj, frames):
    for frame, rotation in frames:
        obj.rotation_euler = rotation
        obj.keyframe_insert("rotation_euler", frame=frame)


# --- the templates -----------------------------------------------------------


def build_corridor(scene, collection, p):
    length, width, height = p["length"], p["width"], p["height"]
    walls = surface_material("PT Wall", p["wall_color"], roughness=0.75)
    panel = emission_material("PT Panel", p["light_color"], max(0.5, p["light_energy"] / 20.0))

    slabs = (
        ("PT Floor", (0.0, length / 2.0, 0.0), (width / 2.0, length / 2.0, 0.02)),
        ("PT Ceiling", (0.0, length / 2.0, height), (width / 2.0, length / 2.0, 0.02)),
        (
            "PT Wall L",
            (-width / 2.0, length / 2.0, height / 2.0),
            (0.02, length / 2.0, height / 2.0),
        ),
        (
            "PT Wall R",
            (width / 2.0, length / 2.0, height / 2.0),
            (0.02, length / 2.0, height / 2.0),
        ),
        ("PT End", (0.0, length, height / 2.0), (width / 2.0, 0.02, height / 2.0)),
    )
    for name, location, scale in slabs:
        slab = add_mesh(collection, "primitive_cube_add", size=2.0, location=location)
        slab.name = name
        slab.scale = scale
        slab.data.materials.append(walls)

    spacing = max(0.5, p["light_spacing"])
    count = max(1, int(length / spacing))
    for index in range(count):
        y = spacing * (index + 0.5)
        strip = add_mesh(
            collection, "primitive_plane_add", size=1.0, location=(0.0, y, height - 0.05)
        )
        strip.name = f"PT Panel {index:02d}"
        strip.scale = (width * 0.28, spacing * 0.18, 1.0)
        strip.data.materials.append(panel)

        light_data = bpy.data.lights.new(f"PT Light {index:02d}", type="AREA")
        light_data.energy = p["light_energy"]
        light_data.color = p["light_color"]
        light_data.size = width * 0.5
        light = bpy.data.objects.new(f"PT Light {index:02d}", light_data)
        light.location = (0.0, y, height - 0.1)
        place(light, collection)

    camera, _target = add_camera(
        collection, scene, (0.0, 1.0, height * 0.55), (0.0, length * 0.9, height * 0.5)
    )
    drift = p["camera_drift"]
    if drift:
        keyframe_location(
            camera,
            [
                (scene.frame_start, (0.0, 1.0, height * 0.55)),
                (scene.frame_end, (0.0, 1.0 + drift, height * 0.55)),
            ],
        )
    setup_world(scene, p["fog_density"], (0.01, 0.01, 0.012), extent=length)


def build_light_room(scene, collection, p):
    size = p["room_size"]
    half = size / 2.0
    shell = surface_material("PT Room", (0.16, 0.16, 0.18), roughness=0.9)

    for name, location, scale in (
        ("PT Floor", (0.0, 0.0, 0.0), (half, half, 0.02)),
        ("PT Ceiling", (0.0, 0.0, size), (half, half, 0.02)),
        ("PT Wall N", (0.0, half, half), (half, 0.02, half)),
        ("PT Wall S", (0.0, -half, half), (half, 0.02, half)),
        ("PT Wall E", (half, 0.0, half), (0.02, half, half)),
    ):
        slab = add_mesh(collection, "primitive_cube_add", size=2.0, location=location)
        slab.name = name
        slab.scale = scale
        slab.data.materials.append(shell)

    # The west wall is built in segments with gaps left between them. The light
    # comes through those gaps -- which is the whole point of the template, and
    # what an unbroken wall with lights behind it cannot do.
    count = max(1, p["slit_count"])
    slit = max(0.02, p["slit_width"])
    centres = [-half + size * (index + 1) / (count + 1) for index in range(count)]

    edges = [-half]
    for centre in centres:
        edges.extend((centre - slit / 2.0, centre + slit / 2.0))
    edges.append(half)
    for index in range(0, len(edges), 2):
        low, high = edges[index], edges[index + 1]
        if high - low <= 1e-4:
            continue
        segment = add_mesh(
            collection,
            "primitive_cube_add",
            size=2.0,
            location=(-half, (low + high) / 2.0, half),
        )
        segment.name = f"PT Wall W {index // 2:02d}"
        segment.scale = (0.02, (high - low) / 2.0, half)
        segment.data.materials.append(shell)

    angle = max(1.0, min(89.0, p["beam_angle"]))
    glow = emission_material("PT Slit Glow", p["beam_color"], 30.0)
    for index, centre in enumerate(centres):
        # One target per beam, so they stay roughly parallel instead of
        # converging on a single point.
        target = bpy.data.objects.new(f"PT Beam Target {index:02d}", None)
        target.location = (half * 0.2, centre, 0.0)
        target.empty_display_size = 0.2
        place(target, collection)

        light_data = bpy.data.lights.new(f"PT Beam {index:02d}", type="SPOT")
        light_data.energy = p["beam_energy"]
        light_data.color = p["beam_color"]
        light_data.spot_size = math.radians(45.0)
        light_data.spot_blend = 0.12
        light_data.shadow_soft_size = 0.05
        light = bpy.data.objects.new(f"PT Beam {index:02d}", light_data)
        light.location = (-half - size * 0.5, centre, size * (0.35 + angle / 180.0))
        place(light, collection)
        track = light.constraints.new("TRACK_TO")
        track.target = target
        track.track_axis = "TRACK_NEGATIVE_Z"
        track.up_axis = "UP_Y"

        # A visible glow in each gap, so the emission pass is a usable layer.
        panel = add_mesh(
            collection,
            "primitive_plane_add",
            size=1.0,
            location=(-half + 0.03, centre, half),
            rotation=(0.0, math.radians(90.0), 0.0),
        )
        panel.name = f"PT Slit {index:02d}"
        panel.scale = (half * 0.85, slit * 0.5, 1.0)
        panel.data.materials.append(glow)

    start_at = (half * 0.75, -half * 0.75, size * 0.5)
    camera, _target = add_camera(
        collection, scene, start_at, (-half * 0.5, 0.0, size * 0.3), lens=35.0
    )
    drift = p["camera_drift"]
    if drift:
        keyframe_location(
            camera,
            [
                (scene.frame_start, start_at),
                (scene.frame_end, (start_at[0] - drift, start_at[1] + drift, start_at[2])),
            ],
        )
    setup_world(scene, p["fog_density"], (0.004, 0.004, 0.006), extent=size * 2.0)


def build_camera_move(scene, collection, p):
    if p["build_subject"]:
        subject = add_mesh(collection, "primitive_ico_sphere_add", subdivisions=3, radius=1.4)
        subject.name = "PT Subject"
        subject.data.materials.append(surface_material("PT Subject", (0.55, 0.55, 0.6), 0.35))

        glow = add_mesh(collection, "primitive_uv_sphere_add", radius=0.5, location=(2.6, 1.2, 1.1))
        glow.name = "PT Glow"
        glow.data.materials.append(emission_material("PT Glow", (1.0, 0.5, 0.2), 12.0))

        reach = max(3.0, p["radius"])
        key_data = bpy.data.lights.new("PT Key", type="AREA")
        key_data.energy = reach * reach * 30.0
        key_data.size = reach * 0.8
        key = bpy.data.objects.new("PT Key", key_data)
        key.location = (reach * 0.7, -reach * 0.7, reach * 0.9)
        key.rotation_euler = (math.radians(45.0), 0.0, math.radians(45.0))
        place(key, collection)

        rim_data = bpy.data.lights.new("PT Rim", type="AREA")
        rim_data.energy = reach * reach * 12.0
        rim_data.color = (0.5, 0.7, 1.0)
        rim_data.size = reach
        rim = bpy.data.objects.new("PT Rim", rim_data)
        rim.location = (-reach * 0.8, reach * 0.8, reach * 0.5)
        rim.rotation_euler = (math.radians(70.0), 0.0, math.radians(-135.0))
        place(rim, collection)

    radius, height, travel = p["radius"], p["height"], p["travel"]
    start = (radius, 0.0, height)
    camera, pivot = add_camera(collection, scene, start, (0.0, 0.0, height * 0.4), p["lens"])
    pivot.name = "PT Pivot"

    first, last = scene.frame_start, scene.frame_end
    if p["move"] == "ORBIT":
        camera.parent = pivot
        camera.location = start
        keyframe_rotation(
            pivot,
            [(first, (0.0, 0.0, 0.0)), (last, (0.0, 0.0, math.tau * travel))],
        )
    elif p["move"] == "DOLLY":
        keyframe_location(
            camera,
            [(first, (radius, -travel, height)), (last, (radius, travel, height))],
        )
    else:  # PUSH_IN
        keyframe_location(
            camera,
            [(first, (radius, 0.0, height)), (last, (max(0.5, radius - travel), 0.0, height))],
        )
    setup_world(scene, 0.01, (0.02, 0.02, 0.03), extent=radius * 3.0)


def build_text_in_space(scene, collection, p):
    bpy.ops.object.text_add()
    text = place(bpy.context.active_object, collection)
    text.name = "PT Text"
    text.data.body = p["text"] or "PASSTHROUGH"
    text.data.size = p["size"]
    text.data.extrude = p["extrude"]
    text.data.align_x = "CENTER"
    text.data.align_y = "CENTER"
    # A small bevel catches a highlight along every edge, which is most of what
    # makes extruded text read as solid rather than as a flat cut-out.
    text.data.bevel_depth = max(0.002, p["size"] * 0.012)
    text.data.bevel_resolution = 2
    text.rotation_euler = (math.radians(90.0), 0.0, 0.0)
    text.data.materials.append(
        surface_material(
            "PT Text",
            p["text_color"],
            roughness=0.3,
            emission=p["text_color"],
            emission_strength=p["glow"],
        )
    )

    # Distance is derived from the text's actual bounding box, so any wording or
    # size frames correctly. A fixed camera distance put the lens inside a
    # letter as soon as the text was longer than a word or two.
    bpy.context.view_layer.update()
    lens = 60.0
    half_angle = math.atan(36.0 / 2.0 / lens)
    aspect = RESOLUTION[0] / RESOLUTION[1]
    margin = 1.35
    text_width = max(0.2, text.dimensions.x) * margin
    text_height = max(0.2, text.dimensions.z) * margin
    distance = max(
        3.0,
        text_width / (2.0 * math.tan(half_angle) * aspect),
        text_height / (2.0 * math.tan(half_angle)),
    )
    # Off-axis on purpose: straight down the barrel, extruded text looks flat.
    add_camera(
        collection,
        scene,
        (distance * 0.28, -distance * 0.93, distance * 0.16),
        (0.0, 0.0, 0.0),
        lens=lens,
    )

    # Lights scale with the framing, so long text is lit the same as short text.
    rim_data = bpy.data.lights.new("PT Rim", type="AREA")
    rim_data.energy = p["rim_energy"] * (distance / 7.0) ** 2
    rim_data.color = p["rim_color"]
    rim_data.size = distance
    rim = bpy.data.objects.new("PT Rim", rim_data)
    rim.location = (0.0, distance * 0.8, distance * 0.25)
    rim.rotation_euler = (math.radians(-70.0), 0.0, 0.0)
    place(rim, collection)

    key_data = bpy.data.lights.new("PT Key", type="AREA")
    key_data.energy = p["rim_energy"] * 0.6 * (distance / 7.0) ** 2
    key_data.size = distance
    key = bpy.data.objects.new("PT Key", key_data)
    key.location = (-distance * 0.6, -distance * 0.7, distance * 0.4)
    key.rotation_euler = (math.radians(55.0), 0.0, math.radians(-40.0))
    place(key, collection)
    if p["spin"]:
        keyframe_rotation(
            text,
            [
                (scene.frame_start, (math.radians(90.0), 0.0, 0.0)),
                (scene.frame_end, (math.radians(90.0), math.tau * p["spin"], 0.0)),
            ],
        )
    # The mist range has to follow the camera: framing long text pushes it far
    # enough back that a fixed range would read as solid white everywhere.
    setup_world(scene, p["fog_density"], (0.01, 0.012, 0.02), extent=distance * 1.6)


def build_debris_field(scene, collection, p):
    rng = random.Random(p["seed"])
    body = surface_material("PT Debris", p["body_color"], roughness=0.55)
    glow = emission_material("PT Debris Glow", p["glow_color"], 8.0)

    # One shared mesh for every piece: thousands of objects that each own a mesh
    # would cost far more memory than the scene doctor would expect.
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=1, radius=1.0)
    source = bpy.context.active_object
    mesh = source.data
    mesh.materials.append(body)
    bpy.data.objects.remove(source, do_unlink=True)

    spread = p["spread"]
    low, high = sorted((p["scale_min"], p["scale_max"]))
    for index in range(max(1, p["count"])):
        piece = bpy.data.objects.new(f"PT Debris {index:04d}", mesh)
        piece.location = (
            rng.uniform(-spread, spread),
            rng.uniform(-spread, spread),
            rng.uniform(-spread * 0.4, spread * 0.4),
        )
        scale = rng.uniform(low, high)
        piece.scale = (scale, scale * rng.uniform(0.7, 1.3), scale * rng.uniform(0.7, 1.3))
        start_rotation = (
            rng.uniform(0.0, math.tau),
            rng.uniform(0.0, math.tau),
            rng.uniform(0.0, math.tau),
        )
        piece.rotation_euler = start_rotation
        place(piece, collection)

        # Every piece shares one mesh, so the material has to be linked to the
        # object rather than the mesh -- otherwise they would all take whatever
        # the mesh says and the glowing fraction would be nothing but a number.
        slot = piece.material_slots[0]
        slot.link = "OBJECT"
        slot.material = glow if rng.random() < p["glow_fraction"] else body

        if p["tumble"]:
            spin = math.tau * p["tumble"] * rng.uniform(0.5, 1.5)
            keyframe_rotation(
                piece,
                [
                    (scene.frame_start, start_rotation),
                    (
                        scene.frame_end,
                        (
                            start_rotation[0] + spin,
                            start_rotation[1] + spin * 0.6,
                            start_rotation[2],
                        ),
                    ),
                ],
            )

    key_data = bpy.data.lights.new("PT Key", type="SUN")
    key_data.energy = 9.0
    key = bpy.data.objects.new("PT Key", key_data)
    key.rotation_euler = (math.radians(50.0), 0.0, math.radians(30.0))
    place(key, collection)

    fill_data = bpy.data.lights.new("PT Fill", type="AREA")
    fill_data.energy = spread * spread * 9.0
    fill_data.size = spread
    fill = bpy.data.objects.new("PT Fill", fill_data)
    fill.location = (-spread, -spread, spread * 0.6)
    fill.rotation_euler = (math.radians(55.0), 0.0, math.radians(-45.0))
    place(fill, collection)

    add_camera(collection, scene, (0.0, -spread * 1.6, spread * 0.35), (0.0, 0.0, 0.0), lens=45.0)
    setup_world(scene, p["fog_density"], (0.01, 0.01, 0.015), extent=spread * 3.0)


BUILDERS = {
    "corridor": build_corridor,
    "light_room": build_light_room,
    "camera_move": build_camera_move,
    "text_in_space": build_text_in_space,
    "debris_field": build_debris_field,
}


def build(context, template, params, clear_scene=True):
    """Build ``template`` into the current scene. Returns the collection."""
    builder = BUILDERS.get(template.key)
    if builder is None:
        raise template_spec.TemplateError(f"no builder for template {template.key!r}")

    scene = context.scene
    resolved = template.validate(params)

    clear_template(scene)
    if clear_scene:
        clear_scene_objects(scene)
    collection = template_collection(scene)
    setup_render(scene, resolved["frames"])
    builder(scene, collection, resolved)
    context.view_layer.update()
    return collection


# --- property groups generated from the schemas ------------------------------

#: Prefix for the per-template PointerProperty on the scene settings.
GROUP_PREFIX = "tpl_"

#: template key -> generated PropertyGroup class, filled in by register().
PROPERTY_GROUPS = {}

_generated_classes = []


def _annotation(parameter):
    """One Blender property, described by one schema entry."""
    common = {"name": parameter.label, "description": parameter.description}
    if parameter.kind == "float":
        kwargs = dict(common, default=float(parameter.default))
        if parameter.minimum is not None:
            kwargs["min"] = float(parameter.minimum)
        if parameter.maximum is not None:
            kwargs["max"] = float(parameter.maximum)
        if parameter.subtype != "NONE":
            kwargs["subtype"] = parameter.subtype
        return bpy.props.FloatProperty(**kwargs)
    if parameter.kind == "int":
        kwargs = dict(common, default=int(parameter.default))
        if parameter.minimum is not None:
            kwargs["min"] = int(parameter.minimum)
        if parameter.maximum is not None:
            kwargs["max"] = int(parameter.maximum)
        return bpy.props.IntProperty(**kwargs)
    if parameter.kind == "bool":
        return bpy.props.BoolProperty(**common, default=bool(parameter.default))
    if parameter.kind == "string":
        return bpy.props.StringProperty(**common, default=str(parameter.default))
    if parameter.kind == "enum":
        return bpy.props.EnumProperty(
            **common,
            items=[tuple(item) for item in parameter.items],
            default=str(parameter.default),
        )
    if parameter.kind == "color":
        return bpy.props.FloatVectorProperty(
            **common,
            subtype="COLOR",
            size=3,
            min=0.0,
            max=1.0,
            default=tuple(parameter.default),
        )
    raise template_spec.TemplateError(f"unsupported kind {parameter.kind!r}")


def make_property_group(template):
    """A PropertyGroup class whose fields are this template's parameters.

    Generated rather than hand-written so the JSON schema stays the only place a
    parameter is defined. Hand-writing five of these would mean every new
    parameter had to be added in two places, and they would drift.
    """
    annotations = {p.key: _annotation(p) for p in template.parameters}
    return type(
        f"PASSTHROUGH_PG_template_{template.key}",
        (bpy.types.PropertyGroup,),
        {"__annotations__": annotations},
    )


def group_name(template_key):
    return GROUP_PREFIX + template_key


def params_from_group(template, group):
    """Read a generated PropertyGroup back into a plain dict."""
    values = {}
    for parameter in template.parameters:
        value = getattr(group, parameter.key)
        if parameter.kind == "color":
            value = tuple(value)
        values[parameter.key] = value
    return template.validate(values)


class PASSTHROUGH_OT_build_template(bpy.types.Operator):
    """Build the selected shot template into this scene."""

    bl_idname = "passthrough.build_template"
    bl_label = "Build Scene"
    bl_description = (
        "Replace the Passthrough template collection with a fresh build of the "
        "selected template, using the parameters below"
    )
    bl_options = {"REGISTER", "UNDO"}

    clear_scene: bpy.props.BoolProperty(
        name="Replace Scene",
        description=(
            "Delete everything already in the scene first. Leave this on unless "
            "you are adding a template to work you want to keep"
        ),
        default=True,
    )

    def execute(self, context):
        settings = context.scene.passthrough
        templates = template_spec.load_templates()
        template = templates.get(settings.template)
        if template is None:
            self.report({"ERROR"}, f"unknown template {settings.template!r}")
            return {"CANCELLED"}

        group = getattr(settings, group_name(template.key), None)
        params = params_from_group(template, group) if group else template.defaults()

        try:
            collection = build(context, template, params, clear_scene=self.clear_scene)
        except template_spec.TemplateError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        self.report(
            {"INFO"},
            f"Built {template.name}: {len(collection.objects)} objects, "
            f"{context.scene.frame_end} frames",
        )
        return {"FINISHED"}


_CLASSES = (PASSTHROUGH_OT_build_template,)


def register():
    PROPERTY_GROUPS.clear()
    for template in template_spec.load_templates().values():
        cls = make_property_group(template)
        bpy.utils.register_class(cls)
        _generated_classes.append(cls)
        PROPERTY_GROUPS[template.key] = cls
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
    while _generated_classes:
        bpy.utils.unregister_class(_generated_classes.pop())
    PROPERTY_GROUPS.clear()
