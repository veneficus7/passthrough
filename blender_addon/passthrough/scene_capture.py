"""Read Blender scene state into plain data, and write the .jsx.

This is the boundary SPEC.md section 6 asks for: "Pass ``bpy`` data *in*; do not
reach *out* for it." Everything that touches ``bpy`` lives here, and
``camera_convert`` and ``jsx_writer`` receive dicts, floats and tuples.

Not in the section 6 file list. It exists because the operators have to touch
``bpy`` somewhere, and the modules that do the actual work -- ``jsx_writer``,
``camera_convert``, ``queue`` -- are kept importable without it so they can be
unit tested. M4 (nulls and lights) and M5 (the scene doctor's inputs) capture
from here too.
"""

import contextlib
import os

import bpy

from . import camera_convert, jsx_writer, pass_spec, prefs, queue, scene_doctor


def render_dimensions(scene):
    """Comp size in pixels, after the resolution percentage is applied."""
    percent = scene.render.resolution_percentage / 100.0
    return (
        int(round(scene.render.resolution_x * percent)),
        int(round(scene.render.resolution_y * percent)),
    )


def pixel_aspect(scene):
    return scene.render.pixel_aspect_x / scene.render.pixel_aspect_y


def frame_rate(scene):
    """Blender stores fps as a numerator/denominator pair; 23.976 is fps 24 / 1.001."""
    return scene.render.fps / scene.render.fps_base


def matrix_rows(matrix):
    """``mathutils.Matrix`` -> nested tuples, so pure modules never see bpy types."""
    return tuple(tuple(matrix[row][col] for col in range(4)) for row in range(4))


def null_objects(scene):
    """Objects that become After Effects nulls.

    Empties only, and deliberately so: an empty is the thing a compositor
    actually places as a track point, and one predictable rule beats an option
    nobody asked for. To get a null on a mesh, parent an empty to it.
    """
    return [obj for obj in scene.objects if obj.type == "EMPTY"]


def capture_passes(scene):
    """Where every pass sequence will be, predicted rather than scanned.

    Section 7.3 requires the paths be derivable without inspecting the disk, so
    the .jsx can be written before the render has finished.
    """
    settings = scene.passthrough
    root = bpy.path.abspath(settings.output_root)
    shot = pass_spec.sanitize_shot_name(settings.shot_name)
    return [
        {
            "key": spec.key,
            "label": spec.label,
            "path": pass_spec.frame_path(root, shot, spec.key, scene.frame_start),
            # Beauty is the visible base layer; everything else is a disabled
            # guide layer. No look is presumed (SPEC.md M4).
            "guide": spec.key != "beauty",
            "note": spec.note,
        }
        for spec in pass_spec.PASSES
    ]


def capture_shot(context, pixels_per_unit=camera_convert.DEFAULT_PIXELS_PER_UNIT):
    """Sample the active camera across the frame range.

    The camera is read through the dependency graph, so constraints, drivers
    and parented rigs are all evaluated -- which the M6 orbit/dolly rigs need.
    """
    scene = context.scene
    camera = scene.camera
    if camera is None:
        raise LookupError("the scene has no active camera")

    width, height = render_dimensions(scene)
    aspect = pixel_aspect(scene)

    positions = []
    orientations = []
    zooms = []
    empties = null_objects(scene)
    null_tracks = {obj.name: {"position": [], "orientation": []} for obj in empties}

    original_frame = scene.frame_current
    try:
        for frame in range(scene.frame_start, scene.frame_end + 1):
            scene.frame_set(frame)
            depsgraph = context.evaluated_depsgraph_get()

            for obj in empties:
                obj_rows = matrix_rows(obj.evaluated_get(depsgraph).matrix_world)
                track = null_tracks[obj.name]
                track["position"].append(
                    camera_convert.convert_position(
                        camera_convert.to_translation(obj_rows),
                        width,
                        height,
                        pixels_per_unit,
                        aspect,
                    )
                )
                # No x_rot_correction here: that 90 degree twist reconciles
                # things that point down an axis -- cameras and lights -- not
                # plain objects.
                track["orientation"].append(
                    camera_convert.convert_orientation(camera_convert.to_euler_zyx(obj_rows))
                )

            evaluated = camera.evaluated_get(depsgraph)
            rows = matrix_rows(evaluated.matrix_world)

            positions.append(
                camera_convert.convert_position(
                    camera_convert.to_translation(rows), width, height, pixels_per_unit, aspect
                )
            )
            orientations.append(
                camera_convert.convert_orientation(
                    camera_convert.to_euler_zyx(rows), x_rot_correction=True
                )
            )
            data = evaluated.data
            zooms.append(
                camera_convert.zoom_from_lens(
                    data.lens,
                    data.sensor_fit,
                    data.sensor_width,
                    data.sensor_height,
                    width,
                    height,
                    aspect,
                )
            )
    finally:
        scene.frame_set(original_frame)

    comp = {
        "name": pass_spec.sanitize_shot_name(scene.passthrough.shot_name),
        "width": width,
        "height": height,
        "pixel_aspect": aspect,
        "frame_rate": frame_rate(scene),
        "frame_start": scene.frame_start,
        "frame_end": scene.frame_end,
    }
    camera_data = {
        "name": jsx_writer.CAMERA_LAYER_NAME,
        "position": positions,
        # Unwrapped so After Effects does not spin the camera a full turn where
        # atan2 happened to wrap between two frames.
        "orientation": camera_convert.unwrap_track(orientations),
        "zoom": zooms,
    }
    nulls = [
        {
            "name": obj.name,
            "position": null_tracks[obj.name]["position"],
            "orientation": camera_convert.unwrap_track(null_tracks[obj.name]["orientation"]),
        }
        for obj in empties
    ]
    return comp, camera_data, capture_passes(scene), nulls


def capture_camera(context, pixels_per_unit=camera_convert.DEFAULT_PIXELS_PER_UNIT):
    """Just the comp and the camera, for callers that do not want the rest."""
    comp, camera_data, _passes, _nulls = capture_shot(context, pixels_per_unit)
    return comp, camera_data


def jsx_output_path(scene):
    """The .jsx sits beside the pass folders it will eventually import."""
    settings = scene.passthrough
    shot = pass_spec.sanitize_shot_name(settings.shot_name)
    directory = pass_spec.shot_dir(bpy.path.abspath(settings.output_root), shot)
    return f"{directory}/{shot}.jsx"


class PASSTHROUGH_OT_export_jsx(bpy.types.Operator):
    """Write the After Effects script for this scene's camera."""

    bl_idname = "passthrough.export_jsx"
    bl_label = "Export After Effects Script"
    bl_description = "Write a .jsx that rebuilds this shot's comp and camera in After Effects"
    bl_options = {"REGISTER"}

    def execute(self, context):
        scene = context.scene
        if not scene.passthrough.output_root:
            self.report({"ERROR"}, "Set an output root first")
            return {"CANCELLED"}

        try:
            comp, camera, passes, nulls = capture_shot(context, prefs.pixels_per_unit(context))
        except LookupError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        path = jsx_output_path(scene)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(jsx_writer.write_jsx(comp, camera, passes=passes, nulls=nulls))

        self.report({"INFO"}, f"Wrote {path} ({len(passes)} passes, {len(nulls)} nulls)")
        return {"FINISHED"}


RENDER_SCRIPT = "render_job.py"
LOG_FILENAME = "render.log"

#: The running job, so the panel can show state and the modal operator can be
#: found again after a UI redraw.
_active_job = None


def active_job():
    return _active_job


def render_script_path():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), RENDER_SCRIPT)


def snapshot_blend(scene):
    """Save a copy of the current scene beside the shot output.

    A copy rather than the user's own file: it captures unsaved edits, works for
    a scene that has never been saved, leaves the original untouched, and makes
    the render reproducible later.
    """
    directory = shot_directory(scene)
    os.makedirs(directory, exist_ok=True)
    shot = pass_spec.sanitize_shot_name(scene.passthrough.shot_name)
    path = os.path.join(directory, shot + ".blend")
    bpy.ops.wm.save_as_mainfile(filepath=path, copy=True)
    return path


def shot_directory(scene):
    settings = scene.passthrough
    shot = pass_spec.sanitize_shot_name(settings.shot_name)
    return pass_spec.shot_dir(bpy.path.abspath(settings.output_root), shot)


class PASSTHROUGH_OT_render_headless(bpy.types.Operator):
    """Render the shot in a background Blender, with this UI free to close."""

    bl_idname = "passthrough.render_headless"
    bl_label = "Render Headless"
    bl_description = (
        "Render the frame range in a separate background Blender. The UI can be "
        "closed while it runs, which is what keeps memory available for After Effects"
    )
    bl_options = {"REGISTER"}

    close_ui: bpy.props.BoolProperty(
        name="Quit Blender After Launching",
        description=(
            "Launch the render detached and quit Blender immediately. Saves roughly "
            "1-2 GB of RAM; progress then goes only to render.log"
        ),
        default=False,
    )

    _timer = None
    _job = None

    def _prepare(self, context):
        scene = context.scene
        if not scene.passthrough.output_root:
            self.report({"ERROR"}, "Set an output root first")
            return None
        shot = pass_spec.sanitize_shot_name(scene.passthrough.shot_name)
        blend = snapshot_blend(scene)
        command = queue.build_command(
            bpy.app.binary_path,
            blend,
            render_script_path(),
            shot,
            bpy.path.abspath(scene.passthrough.output_root),
            scene.frame_start,
            scene.frame_end,
        )
        return queue.RenderJob(
            command,
            os.path.join(shot_directory(scene), LOG_FILENAME),
            detached=self.close_ui,
        )

    def execute(self, context):
        global _active_job
        job = self._prepare(context)
        if job is None:
            return {"CANCELLED"}
        job.start()
        _active_job = job
        self.report({"INFO"}, f"Rendering detached; log at {job.log_path}")
        bpy.ops.wm.quit_blender()
        return {"FINISHED"}

    def invoke(self, context, event):
        global _active_job
        if self.close_ui:
            return self.execute(context)

        job = self._prepare(context)
        if job is None:
            return {"CANCELLED"}
        job.start()
        _active_job = job
        self._job = job
        self._timer = context.window_manager.event_timer_add(0.25, window=context.window)
        context.window_manager.modal_handler_add(self)
        self.report({"INFO"}, "Rendering; press Esc to cancel")
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type == "ESC":
            self._job.cancel()
            self._finish(context)
            self.report({"WARNING"}, "Render cancelled")
            return {"CANCELLED"}

        if event.type != "TIMER":
            return {"PASS_THROUGH"}

        self._job.poll()
        if self._job.running:
            context.workspace.status_text_set(self._status())
            return {"RUNNING_MODAL"}

        code = self._job.close()
        self._finish(context)
        if self._job.error:
            self.report({"ERROR"}, self._job.error)
            return {"CANCELLED"}
        if code:
            self.report({"ERROR"}, f"Blender exited {code}; see {self._job.log_path}")
            return {"CANCELLED"}
        self.report(
            {"INFO"},
            f"Rendered {self._job.frame or 0} frames, peak "
            f"{queue.format_bytes(self._job.peak_memory_bytes)}",
        )
        return {"FINISHED"}

    def _status(self):
        fraction = self._job.progress_fraction
        percent = "" if fraction is None else f" {fraction * 100:.0f}%"
        return (
            f"Passthrough:{percent} frame {self._job.frame or 0}/{self._job.total or '?'} "
            f"peak {queue.format_bytes(self._job.peak_memory_bytes)}"
        )

    def _finish(self, context):
        if self._timer is not None:
            context.window_manager.event_timer_remove(self._timer)
            self._timer = None
        context.workspace.status_text_set(None)


# --- scene doctor (M5) -------------------------------------------------------

#: Images that are not real textures and must not be counted.
_NON_TEXTURE_IMAGES = {"Render Result", "Viewer Node"}

#: Name given to the modifier auto-fix adds, so it can be found and updated
#: rather than stacked up on every run.
DECIMATE_MODIFIER = "PT Decimate"


def evaluated_triangles(obj, depsgraph):
    """Triangle count after modifiers.

    The evaluated mesh is what actually costs memory: a subdivision surface can
    multiply a cage by a hundred, and estimating from the original mesh would
    miss all of it.
    """
    try:
        mesh = obj.evaluated_get(depsgraph).data
    except (RuntimeError, AttributeError):
        return 0
    if mesh is None or not hasattr(mesh, "polygons"):
        return 0
    with contextlib.suppress(RuntimeError, AttributeError):
        mesh.calc_loop_triangles()
    count = len(getattr(mesh, "loop_triangles", ()))
    if count:
        return count
    return sum(max(0, len(polygon.vertices) - 2) for polygon in mesh.polygons)


def capture_scene_stats(context):
    """Describe the scene for scene_doctor, as plain data."""
    scene = context.scene
    depsgraph = context.evaluated_depsgraph_get()

    objects = []
    for obj in scene.objects:
        if obj.type != "MESH" or not obj.visible_get():
            continue
        triangles = evaluated_triangles(obj, depsgraph)
        if triangles:
            objects.append({"name": obj.name, "triangles": triangles})

    textures = []
    for image in bpy.data.images:
        if image.name in _NON_TEXTURE_IMAGES or image.type != "IMAGE":
            continue
        width, height = image.size[0], image.size[1]
        channels = image.channels or 4
        if width <= 0 or height <= 0:
            continue
        textures.append(
            {
                "name": image.name,
                "width": width,
                "height": height,
                "channels": channels,
                # image.depth is bits for the whole pixel, so divide it out.
                "depth": max(8, (image.depth or 32) // channels),
            }
        )

    return {
        "resolution_x": scene.render.resolution_x,
        "resolution_y": scene.render.resolution_y,
        "resolution_percentage": scene.render.resolution_percentage,
        "objects": objects,
        "textures": textures,
    }


def diagnose_scene(context):
    return scene_doctor.diagnose(capture_scene_stats(context), prefs.memory_budget(context))


def apply_fix(context, fix):
    """Apply one scene_doctor fix. Returns a human-readable note."""
    scene = context.scene

    if fix.kind == "resolution":
        scene.render.resolution_percentage = int(fix.detail["percentage"])
        return f"resolution set to {fix.detail['percentage']}%"

    if fix.kind == "decimate":
        ratio = float(fix.detail["ratio"])
        touched = 0
        for name in fix.detail["objects"]:
            obj = scene.objects.get(name)
            if obj is None:
                continue
            modifier = obj.modifiers.get(DECIMATE_MODIFIER)
            if modifier is None:
                modifier = obj.modifiers.new(DECIMATE_MODIFIER, "DECIMATE")
            modifier.decimate_type = "COLLAPSE"
            modifier.ratio = ratio
            touched += 1
        return f"decimated {touched} object(s) to {ratio:.0%}"

    if fix.kind == "texture_scale":
        limit = int(fix.detail["limit"])
        touched = 0
        for name in fix.detail["images"]:
            image = bpy.data.images.get(name)
            if image is None:
                continue
            width, height = image.size[0], image.size[1]
            if max(width, height) <= limit:
                continue
            if width >= height:
                new_width, new_height = limit, max(1, round(height * limit / width))
            else:
                new_height, new_width = limit, max(1, round(width * limit / height))
            image.scale(new_width, new_height)
            # Scaling alone does not survive a .blend round trip: the image's
            # source is still FILE, so a fresh Blender re-reads the full-size
            # file and the saving evaporates. Since the headless render works
            # from a saved snapshot, that would leave the doctor predicting a
            # cost the real render sails past. Packing embeds the scaled buffer,
            # which does persist. Reversible with unpack() then reload().
            with contextlib.suppress(RuntimeError):
                image.pack()
            touched += 1
        return f"scaled {touched} texture(s) to {limit}px"

    return f"unknown fix: {fix.kind}"


class PASSTHROUGH_OT_diagnose(bpy.types.Operator):
    """Estimate what this scene will cost to render, before committing to it."""

    bl_idname = "passthrough.diagnose"
    bl_label = "Check Scene"
    bl_description = (
        "Estimate peak memory from texture sizes, polygon counts and render "
        "resolution, and report whether the render fits the budget"
    )
    bl_options = {"REGISTER"}

    def execute(self, context):
        report = diagnose_scene(context)
        for line in scene_doctor.summarise(report):
            print("Passthrough: " + line)
        context.scene.passthrough.last_estimate = report.estimate.total
        if report.fits:
            self.report(
                {"INFO"},
                f"Projected {scene_doctor.format_bytes(report.estimate.total)}; fits the budget",
            )
        else:
            self.report(
                {"WARNING"},
                f"Projected {scene_doctor.format_bytes(report.estimate.total)}, over the "
                f"{scene_doctor.format_bytes(report.budget)} budget. "
                f"{len(report.fixes)} fix(es) available; see the console",
            )
        return {"FINISHED"}


class PASSTHROUGH_OT_auto_fix(bpy.types.Operator):
    """Degrade the scene until it fits the memory budget."""

    bl_idname = "passthrough.auto_fix"
    bl_label = "Fit to Budget"
    bl_description = (
        "Cap oversized textures, decimate heavy objects and clamp the render "
        "resolution until the projected memory fits the budget"
    )
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        report = diagnose_scene(context)
        if report.fits:
            self.report({"INFO"}, "Already within budget; nothing changed")
            return {"CANCELLED"}

        notes = [apply_fix(context, fix) for fix in report.fixes]
        after = diagnose_scene(context)
        context.scene.passthrough.last_estimate = after.estimate.total

        summary = "; ".join(notes) if notes else "no fix available"
        if after.fits:
            self.report(
                {"INFO"},
                f"{summary}. Now {scene_doctor.format_bytes(after.estimate.total)}",
            )
        else:
            self.report(
                {"WARNING"},
                f"{summary}. Still {scene_doctor.format_bytes(after.estimate.total)}, "
                f"over budget -- reduce the scene by hand",
            )
        return {"FINISHED"}


_CLASSES = (
    PASSTHROUGH_OT_export_jsx,
    PASSTHROUGH_OT_render_headless,
    PASSTHROUGH_OT_diagnose,
    PASSTHROUGH_OT_auto_fix,
)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
