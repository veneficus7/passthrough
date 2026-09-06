"""M6 acceptance: every template produces a rendered, composited shot.

The criterion is that someone with no Blender knowledge can get a shot out using
only the Passthrough panel, without opening the shader editor or the node graph.
That is hard to assert directly, so it is decomposed into things that are
checkable: each template builds a complete scene (geometry, lights and an active
camera) from its own defaults, every pass renders with real content in it, and
the .jsx lands beside the passes -- all driven purely through the operators the
panel exposes.
"""

import json
import subprocess
from pathlib import Path

import pytest
from passthrough import pass_spec, template_spec
from test_passes_integration import ADDON_PARENT, BLENDER

DRIVER = Path(__file__).parent / "blender_m6_driver.py"

TEMPLATES = sorted(template_spec.load_templates())

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(BLENDER is None, reason="Blender not found"),
]


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    output_root = tmp_path_factory.mktemp("m6")
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
        timeout=3600,
    )
    if proc.returncode != 0 or "PT_M6_DONE" not in proc.stdout:
        pytest.fail(
            f"M6 driver failed (exit {proc.returncode})\n"
            f"{proc.stdout[-5000:]}\n{proc.stderr[-3000:]}"
        )
    return json.loads(report_path.read_text(encoding="utf-8"))


def test_the_spec_names_five_templates():
    """SPEC.md M6: liminal corridor, volumetric light room, camera rig, 3D text,
    debris field."""
    assert len(TEMPLATES) == 5


@pytest.mark.parametrize("key", TEMPLATES)
def test_every_operator_in_the_panel_sequence_succeeds(built, key):
    entry = built[key]
    assert entry["build_result"] == ["FINISHED"]
    assert entry["passes_result"] == ["FINISHED"]
    assert entry["export_result"] == ["FINISHED"]


@pytest.mark.parametrize("key", TEMPLATES)
def test_every_template_builds_a_complete_scene(built, key):
    """Geometry, light and a camera -- nothing left for the user to add."""
    entry = built[key]
    assert entry["meshes"] >= 1, f"{key} built no geometry"
    assert entry["lights"] >= 1, f"{key} built no lights"
    assert entry["cameras"] == 1, f"{key} should build exactly one camera"
    assert entry["has_active_camera"], f"{key} did not set the scene camera"


@pytest.mark.parametrize("key", TEMPLATES)
def test_every_template_targets_portrait(built, key):
    """Appendix B: work at 1080x1920."""
    assert built[key]["resolution"] == [1080, 1920]


@pytest.mark.parametrize("key", TEMPLATES)
def test_the_beauty_pass_is_not_black(built, key):
    """A template that renders black has not produced a shot."""
    stats = built[key]["pass_statistics"]["beauty"]
    assert stats["max"] > 0.01, f"{key} rendered a black beauty pass"
    assert stats["nonzero_fraction"] > 0.05


@pytest.mark.parametrize("key", TEMPLATES)
def test_the_beauty_pass_has_real_contrast(built, key):
    """Not-black is too weak a test.

    An early version of the light room rendered one flat grey wall: no beams, no
    shadows, nothing recognisable. Every "is it black" check passed. Standard
    deviation is what actually distinguishes a shot from a blank surface.
    """
    stats = built[key]["pass_statistics"]["beauty"]
    assert stats["std"] > 0.01, f"{key} rendered a nearly featureless frame"


@pytest.mark.parametrize("key", TEMPLATES)
def test_building_twice_gives_the_same_scene(built, key):
    """Rebuilding replaces the template rather than stacking a second copy."""
    entry = built[key]
    assert entry["first_object_count"] == entry["rebuilt_object_count"]


@pytest.mark.parametrize("key", TEMPLATES)
def test_the_startup_scene_is_replaced(built, key):
    """The default cube used to sit in the middle of every template."""
    entry = built[key]
    assert entry["scene_objects"] == entry["objects"], (
        f"{key} left {entry['scene_objects'] - entry['objects']} object(s) "
        "outside the template collection"
    )


@pytest.mark.parametrize("key", TEMPLATES)
def test_the_mist_pass_has_depth_in_it(built, key):
    """Mist is useless if the range was never set for the scene's scale."""
    stats = built[key]["pass_statistics"]["mist"]
    assert stats["max"] > stats["min"], f"{key} produced a flat mist pass"


@pytest.mark.parametrize("key", TEMPLATES)
def test_the_normal_pass_has_surfaces_in_it(built, key):
    stats = built[key]["pass_statistics"]["normal"]
    assert stats["nonzero_fraction"] > 0.01, f"{key} produced an empty normal pass"


@pytest.mark.parametrize("key", TEMPLATES)
def test_every_template_lights_the_emission_pass(built, key):
    """Every template includes emissive geometry on purpose.

    A pass that always renders black is a layer the user has to work out is
    useless, so each template puts something in it -- including the light room,
    where spot lights alone would contribute nothing.
    """
    stats = built[key]["pass_statistics"]["emission"]
    assert stats["max"] > 0.01, f"{key} produced a black emission pass"


@pytest.mark.parametrize("key", TEMPLATES)
def test_the_script_lands_beside_the_passes(built, key):
    entry = built[key]
    assert Path(entry["jsx_path"]).is_file()
    assert Path(entry["jsx_path"]).parent == Path(entry["shot_dir"])


@pytest.mark.parametrize("key", TEMPLATES)
def test_every_pass_was_written(built, key):
    """The whole section 7.3 tree, for every template."""
    shot_dir = Path(built[key]["shot_dir"])
    for spec in pass_spec.PASSES:
        path = shot_dir / spec.key / pass_spec.frame_filename(spec.key, 1)
        assert path.is_file(), f"{key} did not write {spec.key}"
        assert path.stat().st_size > 0


@pytest.mark.parametrize("key", TEMPLATES)
def test_templates_expose_parameters_to_tune(built, key):
    """A template with no knobs is a fixed scene, not a template."""
    assert len(built[key]["parameters"]) >= 5
