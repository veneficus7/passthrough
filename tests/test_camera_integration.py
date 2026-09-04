"""M2 acceptance against a real Blender (SPEC.md sections 7.2 and 9).

The important test here is the projection check the spec calls for: a point at a
known world position must land on the same pixel in After Effects as it does in
Blender's render. Blender supplies the ground truth via ``world_to_camera_view``;
this module re-projects the same points through the derived AE camera and
compares. If the position mapping, the orientation or the zoom were wrong, the
pixels would not agree.
"""

import json
import math
import subprocess
from pathlib import Path

import pytest
from passthrough import jsx_writer
from test_jsx_writer import assert_balanced, assert_es3
from test_passes_integration import BLENDER, REPO_ROOT

DRIVER = Path(__file__).parent / "blender_m2_driver.py"

#: A tenth of a pixel is far tighter than anything visible, and loose enough to
#: absorb float32 round-tripping through JSON.
PIXEL_TOLERANCE = 0.1

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        BLENDER is None,
        reason="Blender not found; set PASSTHROUGH_BLENDER to run integration tests",
    ),
]


@pytest.fixture(scope="module")
def report(tmp_path_factory):
    output_root = tmp_path_factory.mktemp("m2")
    report_path = output_root / "report.json"
    proc = subprocess.run(
        [
            BLENDER,
            "-b",
            "--factory-startup",
            "--python-exit-code",
            "1",
            "--python",
            str(DRIVER),
            "--",
            str(REPO_ROOT / "blender_addon"),
            str(output_root),
            str(report_path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
    )
    if proc.returncode != 0 or "PT_M2_DONE" not in proc.stdout:
        pytest.fail(
            f"Blender driver failed (exit {proc.returncode})\n"
            f"--- stdout ---\n{proc.stdout[-4000:]}\n"
            f"--- stderr ---\n{proc.stderr[-3000:]}"
        )
    return json.loads(report_path.read_text(encoding="utf-8"))


# --- the section 7.2 verification -------------------------------------------


def rotation_matrix(orientation_degrees):
    """After Effects composes orientation as Rx @ Ry @ Rz.

    Determined empirically: of the six possible orders, only this one reproduces
    Blender's projection, and it does so to about 1e-4 px. The others are wrong
    by hundreds of pixels.
    """

    def rx(a):
        c, s = math.cos(a), math.sin(a)
        return ((1, 0, 0), (0, c, -s), (0, s, c))

    def ry(a):
        c, s = math.cos(a), math.sin(a)
        return ((c, 0, s), (0, 1, 0), (-s, 0, c))

    def rz(a):
        c, s = math.cos(a), math.sin(a)
        return ((c, -s, 0), (s, c, 0), (0, 0, 1))

    def mul(a, b):
        return tuple(
            tuple(sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)) for i in range(3)
        )

    x, y, z = (math.radians(v) for v in orientation_degrees)
    return mul(mul(rx(x), ry(y)), rz(z))


def project(ae_point, cam_pos, cam_orientation, zoom, width, height):
    """Where After Effects puts ``ae_point`` on screen."""
    rot = rotation_matrix(cam_orientation)
    rel = [ae_point[i] - cam_pos[i] for i in range(3)]
    # Camera space = R^T applied to the offset.
    cam_space = [sum(rot[k][i] * rel[k] for k in range(3)) for i in range(3)]
    if cam_space[2] <= 0:
        raise AssertionError("point is behind the camera")
    return (
        width / 2.0 + zoom * cam_space[0] / cam_space[2],
        height / 2.0 + zoom * cam_space[1] / cam_space[2],
    )


def test_ae_camera_projects_points_where_blender_renders_them(report):
    """The check section 7.2 says catches everything."""
    worst = 0.0
    worst_where = None
    for frame in report["frames"]:
        for point in frame["points"]:
            sx, sy = project(
                point["ae_pos"],
                frame["cam_pos"],
                frame["cam_orientation"],
                frame["zoom"],
                report["width"],
                report["height"],
            )
            bx, by = point["blender_px"]
            error = math.hypot(sx - bx, sy - by)
            if error > worst:
                worst, worst_where = error, (frame["frame"], point["world"], (sx, sy), (bx, by))
    assert worst < PIXEL_TOLERANCE, f"worst {worst:.4f}px at {worst_where}"


def test_euler_port_matches_mathutils(report):
    """The pure ZYX extraction rebuilds the same rotation matrix Blender has."""
    assert report["euler_matrix_error"] < 1e-5


# --- the exported script -----------------------------------------------------


def test_operator_wrote_a_script(report):
    assert report["operator_result"] == ["FINISHED"]
    assert Path(report["jsx_path"]).is_file()


def test_exported_script_is_es3(report):
    assert_es3(Path(report["jsx_path"]).read_text(encoding="utf-8"), "exported .jsx")


def test_exported_script_is_structurally_balanced(report):
    assert_balanced(Path(report["jsx_path"]).read_text(encoding="utf-8"), "exported .jsx")


def test_exported_comp_matches_the_scene(report):
    source = Path(report["jsx_path"]).read_text(encoding="utf-8")
    assert f"var PT_WIDTH = {report['width']};" in source
    assert f"var PT_HEIGHT = {report['height']};" in source
    assert "var PT_FRAME_RATE = 24;" in source
    expected = jsx_writer.comp_duration(report["frame_start"], report["frame_end"], 24.0)
    assert f"var PT_DURATION = {jsx_writer.format_number(expected)};" in source


def test_exported_script_has_a_key_per_frame(report):
    source = Path(report["jsx_path"]).read_text(encoding="utf-8")
    count = report["frame_end"] - report["frame_start"] + 1
    times = source.split("var PT_TIMES = [")[1].split("]")[0]
    assert len(times.split(",")) == count


# --- animation continuity ----------------------------------------------------


def test_orientation_track_never_jumps_a_whole_turn(report):
    """A full orbit crosses the atan2 wrap; unwrapping must absorb it.

    Without it After Effects would spin the camera 358 degrees between two
    frames, which is exactly the sort of thing that looks like a broken export.
    """
    track = report["orientation_track"]
    worst = 0.0
    for index in range(len(track) - 1):
        previous, current = track[index], track[index + 1]
        worst = max(worst, max(abs(a - b) for a, b in zip(previous, current, strict=True)))
    assert worst < 180.0, f"orientation jumps {worst:.1f} degrees between frames"


def test_camera_actually_moves(report):
    """Guards against the whole suite passing because nothing was animated.

    Compared against the furthest frame, not the last one: the rig orbits a full
    turn, so the camera ends up back where it started.
    """
    first = report["frames"][0]["cam_pos"]
    furthest = max(math.dist(first, f["cam_pos"]) for f in report["frames"])
    assert furthest > 100.0, "the camera never moved; the rig did not animate"
