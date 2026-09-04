"""M1 acceptance, run against a real Blender (SPEC.md section 9, integration).

Skipped when Blender cannot be found. Point ``PASSTHROUGH_BLENDER`` at a
blender executable to override discovery.
"""

import os
import shutil
import subprocess
from pathlib import Path

import exr_header
import pytest
from passthrough import pass_spec

REPO_ROOT = Path(__file__).resolve().parents[1]
ADDON_PARENT = REPO_ROOT / "blender_addon"
DRIVER = Path(__file__).parent / "blender_m1_driver.py"

SHOT_NAME = "hallway"


def find_blender():
    override = os.environ.get("PASSTHROUGH_BLENDER")
    if override:
        return override if Path(override).is_file() else None

    on_path = shutil.which("blender")
    if on_path:
        return on_path

    base = Path("C:/Program Files/Blender Foundation")
    if base.is_dir():
        candidates = sorted(base.glob("Blender */blender.exe"), reverse=True)
        if candidates:
            return str(candidates[0])
    return None


BLENDER = find_blender()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        BLENDER is None,
        reason="Blender not found; set PASSTHROUGH_BLENDER to run integration tests",
    ),
]


@pytest.fixture(scope="module")
def rendered(tmp_path_factory):
    """Run the driver once; every test in this module reads its output."""
    output_root = tmp_path_factory.mktemp("m1")
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
            SHOT_NAME,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
    )
    if proc.returncode != 0 or "PT_DONE" not in proc.stdout:
        pytest.fail(
            f"Blender driver failed (exit {proc.returncode})\n"
            f"--- stdout ---\n{proc.stdout[-4000:]}\n"
            f"--- stderr ---\n{proc.stderr[-2000:]}"
        )

    markers = {}
    for line in proc.stdout.splitlines():
        if line.startswith("PT_") and ":" in line:
            key, _, value = line.partition(":")
            markers[key.strip()] = value.strip()
    return markers, output_root


def test_operator_reports_finished(rendered):
    markers, _ = rendered
    assert markers["PT_OP1"] == "['FINISHED']"
    assert markers["PT_OP2"] == "['FINISHED']"


def test_rerunning_the_operator_does_not_duplicate_nodes(rendered):
    """M1 acceptance: re-running the operator is idempotent."""
    markers, _ = rendered
    assert markers["PT_FINGERPRINT1"] == markers["PT_FINGERPRINT2"]
    assert markers["PT_LINKS1"] == markers["PT_LINKS2"]


def test_one_output_node_per_pass_plus_render_layers(rendered):
    markers, _ = rendered
    nodes = dict(entry.split(":") for entry in markers["PT_FINGERPRINT1"].split(";"))
    outputs = [name for name in nodes if name.startswith("PT_OUT_")]
    assert len(outputs) == len(pass_spec.PASSES)
    assert nodes["PT_RENDER_LAYERS"] == "CompositorNodeRLayers"
    for spec in pass_spec.PASSES:
        assert nodes["PT_OUT_" + spec.key] == "CompositorNodeOutputFile"
    assert int(markers["PT_LINKS1"]) == len(pass_spec.PASSES)


def test_every_pass_flag_is_enabled(rendered):
    markers, _ = rendered
    flags = dict(entry.split("=") for entry in markers["PT_PASS_FLAGS"].split(","))
    assert set(flags.values()) == {"True"}, flags
    assert int(markers["PT_CRYPTO_DEPTH"]) == pass_spec.CRYPTOMATTE_DEPTH


def test_output_is_single_layer_exr_not_multilayer(rendered):
    """Section 7.3: multi-layer EXR is what this whole layout exists to avoid."""
    markers, _ = rendered
    assert markers["PT_ITEM_COUNT"] == "1"
    assert markers["PT_ITEM_FORMAT"] == "OPEN_EXR"
    assert markers["PT_ITEM_OVERRIDE"] == "True"


def test_output_item_is_unnamed(rendered):
    """A named item becomes an EXR layer prefix that After Effects cannot read."""
    markers, _ = rendered
    assert markers["PT_ITEM_NAME"] == "''"


def test_node_depth_and_codec_follow_the_manifest(rendered):
    markers, _ = rendered
    depths = dict(entry.split("=") for entry in markers["PT_NODE_DEPTHS"].split(","))
    for spec in pass_spec.PASSES:
        assert depths[spec.key] == f"{spec.color_depth}/{pass_spec.EXR_CODEC}"


def test_passes_are_not_view_transformed(rendered):
    """Section 7.4: AgX baked into a pass will not composite correctly."""
    markers, _ = rendered
    assert markers["PT_ITEM_SAVE_AS_RENDER"] == "False"


def test_node_paths_match_the_manifest(rendered):
    markers, output_root = rendered
    expected_dir = pass_spec.pass_dir(str(output_root), SHOT_NAME, "beauty")
    assert Path(markers["PT_DIRECTORY"]).resolve() == Path(expected_dir).resolve()
    assert markers["PT_FILE_NAME"] == pass_spec.frame_pattern("beauty")


def test_render_produces_exactly_the_section_7_3_tree(rendered):
    """M1 acceptance: one image per pass, in the folder layout the spec draws."""
    _, output_root = rendered
    expected = pass_spec.expected_files(str(output_root), SHOT_NAME, 1, 1)

    shot_dir = Path(pass_spec.shot_dir(str(output_root), SHOT_NAME))
    actual = {p.resolve() for p in shot_dir.rglob("*") if p.is_file()}
    wanted = {Path(p).resolve() for paths in expected.values() for p in paths}

    assert actual == wanted


def test_each_pass_folder_holds_one_non_empty_image(rendered):
    _, output_root = rendered
    for spec in pass_spec.PASSES:
        path = Path(pass_spec.frame_path(str(output_root), SHOT_NAME, spec.key, 1))
        assert path.is_file(), f"{spec.key} produced no image"
        assert path.stat().st_size > 0, f"{spec.key} image is empty"


@pytest.fixture(scope="module")
def headers(rendered):
    _, output_root = rendered
    return {
        spec.key: exr_header.read_header(
            pass_spec.frame_path(str(output_root), SHOT_NAME, spec.key, 1)
        )
        for spec in pass_spec.PASSES
    }


def test_written_exrs_have_plain_rgba_channels(headers):
    """The check that matters for After Effects.

    AE reads the unprefixed R/G/B/A channels. If Blender writes ``beauty.R``
    the file opens as an empty layer, which looks like a render failure and is
    not one.
    """
    for key, header in headers.items():
        upper = tuple(sorted(name.upper() for name in header.channel_names))
        assert upper == ("A", "B", "G", "R"), f"{key}: {header.channel_names}"
        assert header.layer_prefixes == (), f"{key} has layer prefixes"
        assert not header.multipart


def test_cryptomatte_channels_are_lowercase(headers):
    """Documents a real Blender quirk rather than hiding it.

    Every other pass writes R/G/B/A; the cryptomatte pass writes r/g/b/a. AE's
    EXR reader looks for the uppercase names, so the crypto sequence may well
    import as black. That is acceptable for now -- AE has no native cryptomatte
    support anyway, and M4 imports this pass as a disabled guide layer -- but
    M4 should not be surprised by it.
    """
    assert headers["crypto"].channel_names == ("a", "b", "g", "r")
    for key in ("beauty", "emission", "mist", "normal"):
        assert headers[key].channel_names == ("A", "B", "G", "R")


def test_written_exrs_use_the_requested_bit_depth(headers):
    """Guards the trap that depth comes from the node format, not the item."""
    expected = {"16": "HALF", "32": "FLOAT"}
    for spec in pass_spec.PASSES:
        header = headers[spec.key]
        assert header.pixel_types == {expected[spec.color_depth]}, (
            f"{spec.key} wrote {header.pixel_types}, wanted {expected[spec.color_depth]}"
        )


def test_cryptomatte_is_full_float(headers):
    """Half float rounds away cryptomatte's object-id hashes."""
    assert headers["crypto"].pixel_types == {"FLOAT"}


def test_written_exrs_are_losslessly_compressed(headers):
    for key, header in headers.items():
        assert header.compression == pass_spec.EXR_CODEC, f"{key}: {header.compression}"
