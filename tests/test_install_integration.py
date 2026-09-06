"""M7 acceptance: a clean zip installs on a machine that has never seen the source.

The zip is built by tools/build_extension.py, installed into a throwaway Blender
configuration, and then driven entirely through ``bpy.ops`` with the repository
absent from ``sys.path``. Everything else in this suite imports the package
directly, which would happily paper over a file the build left out.

The manifest's minimum is 5.2, so a dev zip with the minimum relaxed is used when
the available Blender is older -- otherwise the extension installs and then
refuses to enable, and the test would be measuring the version gate rather than
the package.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from test_passes_integration import ADDON_PARENT, BLENDER, REPO_ROOT

sys.path.insert(0, str(REPO_ROOT / "tools"))
import build_extension  # noqa: E402

DRIVER = Path(__file__).parent / "blender_install_driver.py"

EXPECTED_OPERATORS = {
    "PASSTHROUGH_OT_setup_passes",
    "PASSTHROUGH_OT_export_jsx",
    "PASSTHROUGH_OT_render_headless",
    "PASSTHROUGH_OT_diagnose",
    "PASSTHROUGH_OT_auto_fix",
    "PASSTHROUGH_OT_build_template",
}

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(BLENDER is None, reason="Blender not found"),
]


def blender_version():
    proc = subprocess.run(
        [BLENDER, "--version"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    first = proc.stdout.splitlines()[0]
    return tuple(int(part) for part in first.split()[1].split(".")[:3])


@pytest.fixture(scope="module")
def installed(tmp_path_factory):
    work = tmp_path_factory.mktemp("m7")
    resources = work / "blender_resources"
    resources.mkdir()
    output_root = work / "out"
    report_path = work / "report.json"

    # Relax the minimum only when the local Blender could not enable the real
    # one; the shipped manifest is never changed.
    dev_version = None
    if blender_version() < (5, 2, 0):
        dev_version = "5.1.0"

    argv = ["--blender", BLENDER, "--output-dir", str(work / "dist")]
    if dev_version:
        argv += ["--dev-version", dev_version]
    build_extension.main(argv)
    zips = sorted((work / "dist").glob("*.zip"))
    assert zips, "the build tool produced no zip"
    zip_path = zips[0]

    environment = dict(os.environ, BLENDER_USER_RESOURCES=str(resources))
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
            str(zip_path),
            str(ADDON_PARENT),
            str(output_root),
            str(report_path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=1800,
        env=environment,
    )
    if proc.returncode != 0 or "PT_INSTALL_DONE" not in proc.stdout:
        pytest.fail(
            f"install driver failed (exit {proc.returncode})\n"
            f"{proc.stdout[-5000:]}\n{proc.stderr[-3000:]}"
        )
    return json.loads(report_path.read_text(encoding="utf-8")), zip_path


# --- the package -------------------------------------------------------------


def test_the_build_tool_verifies_what_it_produced(installed):
    """build_extension.verify_zip raises if a data file was left out."""
    _report, zip_path = installed
    assert build_extension.verify_zip(zip_path)


def test_the_zip_installs_and_enables(installed):
    """M7 acceptance."""
    report, _ = installed
    assert report["install"] == "ok", report["install"]
    assert report["modules"], "the extension did not appear as an add-on module"
    assert all(report["enabled"]), "the extension installed but would not enable"


def test_it_installed_as_a_real_extension(installed):
    report, _ = installed
    assert any(name.startswith("bl_ext.") for name in report["modules"]), report["modules"]


def test_the_source_tree_was_not_reachable(installed):
    """Without this the test would prove nothing about the package."""
    report, _ = installed
    assert not report["source_on_path"]


# --- what a clean install can actually do ------------------------------------


def test_everything_registers_from_the_installed_copy(installed):
    report, _ = installed
    assert set(report["operators"]) == EXPECTED_OPERATORS
    assert "PASSTHROUGH_PT_main" in report["panels"]
    assert report["has_scene_settings"]


def test_the_template_schemas_shipped(installed):
    """Data files are what a build silently drops."""
    report, _ = installed
    assert len(report["templates"]) == 5
    assert "corridor" in report["templates"]
    assert "length" in report["template_parameters"]


def test_the_whole_workflow_runs_from_the_installed_copy(installed):
    report, _ = installed
    assert report["build"] == ["FINISHED"]
    assert report["diagnose"] == ["FINISHED"]
    assert report["setup_passes"] == ["FINISHED"]
    assert report["export"] == ["FINISHED"]


def test_it_wrote_the_passes_and_the_script(installed):
    report, _ = installed
    shot_dir = Path(report["shot_dir"])
    for key in ("beauty", "emission", "mist", "normal", "crypto"):
        written = list((shot_dir / key).glob("*.exr"))
        assert written, f"{key} produced nothing from the installed copy"
    assert Path(report["jsx"]).is_file()


def test_the_extendscript_runtime_shipped(installed):
    """jsx_writer reads pt_runtime.jsx from beside itself at export time."""
    report, _ = installed
    source = Path(report["jsx"]).read_text(encoding="utf-8")
    assert "function ptEnsureComp(" in source
    assert "function ptAddPassLayer(" in source
