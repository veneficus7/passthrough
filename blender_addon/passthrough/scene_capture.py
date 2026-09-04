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

import os

import bpy

from . import camera_convert, jsx_writer, pass_spec, prefs, queue


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


def capture_camera(context, pixels_per_unit=camera_convert.DEFAULT_PIXELS_PER_UNIT):
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

    original_frame = scene.frame_current
    try:
        for frame in range(scene.frame_start, scene.frame_end + 1):
            scene.frame_set(frame)
            evaluated = camera.evaluated_get(context.evaluated_depsgraph_get())
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
            comp, camera = capture_camera(context, prefs.pixels_per_unit(context))
        except LookupError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        path = jsx_output_path(scene)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(jsx_writer.write_jsx(comp, camera))

        self.report({"INFO"}, f"Wrote {path}")
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


_CLASSES = (PASSTHROUGH_OT_export_jsx, PASSTHROUGH_OT_render_headless)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
