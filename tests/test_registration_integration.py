"""What the add-on registers inside a real Blender.

Covers the M0 acceptance criterion (a Passthrough panel appears in Render
Properties) and the operator surface every later milestone adds, including the
properties the panel assigns to when drawing a button.
"""

import json
import subprocess
from pathlib import Path

import pytest
from test_passes_integration import ADDON_PARENT, BLENDER

DRIVER = Path(__file__).parent / "blender_register_driver.py"

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(BLENDER is None, reason="Blender not found"),
]


@pytest.fixture(scope="module")
def report(tmp_path_factory):
    path = tmp_path_factory.mktemp("reg") / "report.json"
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
            str(path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
    )
    if proc.returncode != 0 or "PT_REG_DONE" not in proc.stdout:
        pytest.fail(
            f"registration driver failed (exit {proc.returncode})\n"
            f"{proc.stdout[-3000:]}\n{proc.stderr[-2000:]}"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def test_the_panel_lands_in_render_properties(report):
    """M0 acceptance."""
    assert "PASSTHROUGH_PT_main" in report["panels"]
    assert report["panel_contexts"]["PASSTHROUGH_PT_main"] == "render"


def test_every_milestone_operator_is_registered(report):
    assert set(report["operators"]) == {
        "PASSTHROUGH_OT_setup_passes",
        "PASSTHROUGH_OT_export_jsx",
        "PASSTHROUGH_OT_render_headless",
    }


def test_the_render_operator_exposes_close_ui(report):
    """The panel assigns to this when drawing; losing it breaks draw()."""
    assert "close_ui" in report["operator_properties"]["passthrough.render_headless"]


def test_scene_settings_are_attached(report):
    assert report["scene_property"]
    assert {"output_root", "shot_name"} <= set(report["scene_property_fields"])


def test_unregister_removes_everything(report):
    assert report["clean_after_unregister"]["operators"] == []
    assert report["clean_after_unregister"]["panels"] == []


def test_the_add_on_can_be_registered_twice(report):
    """Reloading scripts registers again without a restart."""
    assert report["second_cycle_ok"]
