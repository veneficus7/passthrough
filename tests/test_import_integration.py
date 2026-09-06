"""M4 acceptance: the full After Effects import, against a real render.

The acceptance criterion is "no manual fixing required", so these tests check
that the generated script describes exactly what is on disk: every pass present,
in the right stacking order, correctly named, with the camera and nulls parented
and comp settings matching the Blender scene.
"""

import json
import re
import subprocess
from pathlib import Path

import pytest
from passthrough import jsx_writer, pass_spec
from test_jsx_writer import assert_balanced, assert_es3
from test_passes_integration import ADDON_PARENT, BLENDER

DRIVER = Path(__file__).parent / "blender_m4_driver.py"

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(BLENDER is None, reason="Blender not found"),
]


@pytest.fixture(scope="module")
def imported(tmp_path_factory):
    output_root = tmp_path_factory.mktemp("m4")
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
            str(ADDON_PARENT),
            str(output_root),
            str(report_path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=900,
    )
    if proc.returncode != 0 or "PT_M4_DONE" not in proc.stdout:
        pytest.fail(
            f"M4 driver failed (exit {proc.returncode})\n"
            f"{proc.stdout[-4000:]}\n{proc.stderr[-3000:]}"
        )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    source = Path(report["jsx_path"]).read_text(encoding="utf-8")
    return report, source


def pass_rows(source):
    table = re.search(r"var PT_PASSES = \[(.*?)\];", source, re.S).group(1)
    return re.findall(r'\["([^"]*)", "([^"]*)", (true|false), "([^"]*)"\]', table)


# --- the script itself -------------------------------------------------------


def test_the_operators_succeeded(imported):
    report, _ = imported
    assert report["setup_result"] == ["FINISHED"]
    assert report["export_result"] == ["FINISHED"]


def test_the_script_is_es3_and_balanced(imported):
    _, source = imported
    assert_es3(source, "M4 export")
    assert_balanced(source, "M4 export")


# --- passes ------------------------------------------------------------------


def test_every_pass_is_imported(imported):
    _, source = imported
    rows = pass_rows(source)
    assert [row[0] for row in rows] == [spec.label for spec in pass_spec.PASSES]


def test_pass_paths_exist_on_disk(imported):
    """The paths are predicted, never scanned -- so they had better be right."""
    _, source = imported
    for label, path, _guide, _note in pass_rows(source):
        assert Path(path).is_file(), f"{label} points at a file that does not exist: {path}"


def test_beauty_is_the_visible_base_layer(imported):
    """M4: beauty visible, everything else a disabled guide layer."""
    _, source = imported
    rows = pass_rows(source)
    assert rows[0][0] == "Beauty"
    assert rows[0][2] == "false"
    assert all(row[2] == "true" for row in rows[1:])


def test_layers_stack_with_beauty_underneath(imported):
    """Layers are added bottom first, so beauty must be emitted first."""
    _, source = imported
    labels = [row[0] for row in pass_rows(source)]
    assert labels.index("Beauty") == 0


def test_the_runtime_marks_guides_disabled():
    runtime = jsx_writer.load_runtime()
    body = runtime.split("function ptAddPassLayer")[1].split("\n}")[0]
    assert "layer.guideLayer = true;" in body
    assert "layer.enabled = false;" in body


# --- nulls -------------------------------------------------------------------


def test_nulls_are_created_for_every_empty(imported):
    report, source = imported
    assert sorted(report["null_names"]) == ["TrackMoving", "TrackStatic"]
    assert '"TrackMoving"' in source
    assert '"TrackStatic"' in source


def test_an_animated_null_keeps_a_key_per_frame(imported):
    report, _ = imported
    frames = report["frame_end"] - report["frame_start"] + 1
    assert report["null_track_lengths"]["TrackMoving"]["position"] == frames


def test_camera_and_nulls_are_parented(imported):
    """M4 acceptance: camera and nulls parented."""
    _, source = imported
    assert "var world = ptEnsureWorldNull(" in source
    assert "PT_CAM_ZOOM, world" in source
    assert "PT_NULL_ORIENTATION[i], world" in source


# --- comp settings -----------------------------------------------------------


def test_comp_settings_match_the_blender_scene(imported):
    report, source = imported
    comp = report["comp"]
    assert f"var PT_WIDTH = {comp['width']};" in source
    assert f"var PT_HEIGHT = {comp['height']};" in source
    assert f"var PT_FRAME_RATE = {jsx_writer.format_number(comp['frame_rate'])};" in source
    duration = jsx_writer.comp_duration(comp["frame_start"], comp["frame_end"], comp["frame_rate"])
    assert f"var PT_DURATION = {jsx_writer.format_number(duration)};" in source


def test_the_shot_folder_holds_the_script_beside_the_passes(imported):
    report, _ = imported
    assert Path(report["jsx_path"]).parent == Path(report["shot_dir"])
