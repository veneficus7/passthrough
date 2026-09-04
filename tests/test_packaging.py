"""The built extension zip must contain everything the add-on needs at runtime.

SPEC.md section 6 puts `pt_runtime.jsx` in `ae_scripts/` at the repo root, but
nothing outside `blender_addon/passthrough/` is included in the zip Blender
builds. This is the test that keeps the runtime shipping.
"""

import subprocess
import zipfile
from pathlib import Path

import pytest
from passthrough import jsx_writer
from test_passes_integration import ADDON_PARENT, BLENDER

ADDON_DIR = ADDON_PARENT / "passthrough"


def test_runtime_lives_inside_the_addon_package():
    """A plain-Python check that needs no Blender."""
    runtime = Path(jsx_writer.runtime_path())
    assert runtime.is_file()
    assert ADDON_DIR.resolve() in runtime.resolve().parents


def test_runtime_is_not_empty():
    assert "function ptEnsureComp(" in jsx_writer.load_runtime()


@pytest.mark.integration
@pytest.mark.skipif(BLENDER is None, reason="Blender not found")
def test_built_zip_contains_every_module_and_the_runtime(tmp_path):
    proc = subprocess.run(
        [
            BLENDER,
            "--command",
            "extension",
            "build",
            "--source-dir",
            str(ADDON_DIR),
            "--output-dir",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
    )
    zips = list(tmp_path.glob("*.zip"))
    if proc.returncode != 0 or not zips:
        pytest.fail(f"extension build failed\n{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}")

    names = set(zipfile.ZipFile(zips[0]).namelist())

    assert "blender_manifest.toml" in names
    assert "ae_runtime/pt_runtime.jsx" in names, (
        f"the ExtendScript runtime is missing from the built zip; got {sorted(names)}"
    )
    for module in ADDON_DIR.glob("*.py"):
        assert module.name in names, f"{module.name} did not make it into the zip"


@pytest.mark.integration
@pytest.mark.skipif(BLENDER is None, reason="Blender not found")
def test_built_zip_is_flat_not_nested_in_a_folder(tmp_path):
    """Section 7.5 claims the zip needs a folder named after the id. It does not.

    Blender's own build emits a flat archive and creates the directory at
    install time from the manifest id.
    """
    subprocess.run(
        [
            BLENDER,
            "--command",
            "extension",
            "build",
            "--source-dir",
            str(ADDON_DIR),
            "--output-dir",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
        check=True,
    )
    names = zipfile.ZipFile(next(tmp_path.glob("*.zip"))).namelist()
    assert not any(name.startswith("passthrough/") for name in names)
