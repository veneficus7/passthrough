"""Headless render entry point.

Run as::

    blender -b <scene.blend> -P render_job.py -- --shot <name> --out <dir> \
        --start 1 --end 120

Arguments after ``--`` belong to this script; Blender ignores them
(SPEC.md section 7.6).

This runs as ``__main__``, not as part of the package, so relative imports are
unavailable and the package directory is put on ``sys.path`` explicitly.

Rendering happens one frame at a time with ``write_still=False`` rather than as
an animation. That is deliberate: Blender still substitutes the ``####`` token
in the File Output nodes, but writes **no** main render output, so the shot
folder ends up containing exactly the section 7.3 tree and nothing else.
"""

import argparse
import importlib
import os
import sys
import traceback

import bpy

_HERE = os.path.dirname(os.path.abspath(__file__))
_PACKAGE_PARENT = os.path.dirname(_HERE)
if _PACKAGE_PARENT not in sys.path:
    sys.path.insert(0, _PACKAGE_PARENT)

_PACKAGE = os.path.basename(_HERE)
passes = importlib.import_module(f"{_PACKAGE}.passes")
pass_spec = importlib.import_module(f"{_PACKAGE}.pass_spec")
queue = importlib.import_module(f"{_PACKAGE}.queue")


def script_arguments(argv=None):
    """Everything after the ``--`` separator."""
    argv = sys.argv if argv is None else argv
    if "--" not in argv:
        return []
    return argv[argv.index("--") + 1 :]


def build_parser():
    parser = argparse.ArgumentParser(prog="render_job", description="Passthrough headless render")
    parser.add_argument("--shot", required=True)
    parser.add_argument("--out", required=True, help="output root; the shot folder is made inside")
    parser.add_argument("--start", type=int, required=True)
    parser.add_argument("--end", type=int, required=True)
    parser.add_argument("--resolution-x", type=int, default=None)
    parser.add_argument("--resolution-y", type=int, default=None)
    parser.add_argument("--samples", type=int, default=None)
    return parser


def emit(text):
    """Progress markers must reach the log immediately, not at exit."""
    print(text, flush=True)


def apply_colour_management(scene):
    """Force linear, untransformed output (SPEC.md section 7.4).

    The passes are written by File Output items with ``save_as_render`` off, so
    the view transform does not reach them -- but the spec says to set this
    explicitly rather than inherit whatever the scene had, and it still governs
    anything else the scene writes.

    Blender 5.1 reports only ``NONE`` in the ``view_transform`` enum in
    background mode while still accepting real values, so assignment is
    attempted rather than validated.
    """
    applied = {}
    for name, value in (("view_transform", "Raw"), ("look", "None")):
        try:
            setattr(scene.view_settings, name, value)
            applied[name] = getattr(scene.view_settings, name)
        except (TypeError, ValueError) as exc:
            applied[name] = f"unchanged ({exc.__class__.__name__})"
    scene.view_settings.exposure = 0.0
    scene.view_settings.gamma = 1.0
    scene.view_settings.use_curve_mapping = False
    return applied


def configure(scene, view_layer, args):
    if not passes.is_eevee(scene.render.engine):
        scene.render.engine = "BLENDER_EEVEE"

    if args.resolution_x:
        scene.render.resolution_x = args.resolution_x
    if args.resolution_y:
        scene.render.resolution_y = args.resolution_y
    scene.render.resolution_percentage = 100

    if args.samples is not None and hasattr(scene.eevee, "taa_render_samples"):
        scene.eevee.taa_render_samples = args.samples

    scene.frame_start = args.start
    scene.frame_end = args.end

    applied = apply_colour_management(scene)
    passes.configure_view_layer(view_layer)
    nodes, missing = passes.build_output_tree(scene, view_layer, args.out, args.shot)
    return applied, nodes, missing


def render(scene, args):
    total = args.end - args.start + 1
    for index, frame in enumerate(range(args.start, args.end + 1), start=1):
        scene.frame_set(frame)
        bpy.ops.render.render(write_still=False)
        emit(f"{queue.FRAME_MARKER} {index}/{total}")
    return total


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(script_arguments(argv))

    scene = bpy.context.scene
    view_layer = bpy.context.view_layer
    shot = pass_spec.sanitize_shot_name(args.shot)
    args.shot = shot

    emit(
        f"{queue.JOB_MARKER} shot={shot} start={args.start} end={args.end} "
        f"out={pass_spec.shot_dir(args.out, shot)}"
    )

    applied, _nodes, missing = configure(scene, view_layer, args)
    emit(f"PT_COLOUR {applied}")
    if missing:
        emit(f"PT_WARNING passes with no socket: {', '.join(missing)}")

    total = render(scene, args)
    emit(f"{queue.DONE_MARKER} frames={total}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001 - the log is the only diagnostic here
        emit(f"{queue.ERROR_MARKER} {exc.__class__.__name__}: {exc}")
        traceback.print_exc()
        sys.stdout.flush()
        sys.exit(1)
