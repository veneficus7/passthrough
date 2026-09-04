"""M5 acceptance: the doctor's estimate against real measured memory.

Two criteria:

* the estimate is within +/-25% of the render's actual peak
* auto-fix takes a scene that busts the budget and produces one that renders
  inside it

The spec phrases the second as "a scene that OOMs at 16 GB". Deliberately
exhausting this machine's memory to prove that would be reckless and would tell
us nothing the budget check does not, so the same mechanism is exercised against
a smaller budget: the heavy scene overshoots it, the fixed scene does not, and
both are measured rather than asserted.

The spec also says to compare against "Blender's actual reported peak". Blender
5.1 reports no such figure in background mode -- see the M3 notes -- so peak
working set sampled from the parent process stands in, which is the truer number
anyway.
"""

import json
import subprocess
from pathlib import Path

import pytest
from passthrough import queue, scene_doctor
from test_passes_integration import ADDON_PARENT, BLENDER

DRIVER = Path(__file__).parent / "blender_m5_driver.py"
RENDER_JOB = ADDON_PARENT / "passthrough" / "render_job.py"

#: SPEC.md M5's tolerance.
TOLERANCE = 0.25

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(BLENDER is None, reason="Blender not found"),
]


def render_and_measure(blend, shot, output_root):
    job = queue.RenderJob(
        queue.build_command(BLENDER, blend, RENDER_JOB, shot, output_root, 1, 1),
        Path(output_root) / f"{shot}.log",
    )
    job.start()
    job.wait(timeout=1800)
    if job.returncode != 0:
        log = Path(job.log_path).read_text(encoding="utf-8", errors="replace")
        pytest.fail(f"render of {shot} exited {job.returncode}\n{log[-3000:]}")
    return job.peak_memory_bytes


@pytest.fixture(scope="module")
def doctored(tmp_path_factory):
    work = tmp_path_factory.mktemp("m5")
    report_path = work / "report.json"
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
            str(work),
            str(report_path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=1800,
    )
    if proc.returncode != 0 or "PT_M5_DONE" not in proc.stdout:
        pytest.fail(
            f"M5 driver failed (exit {proc.returncode})\n"
            f"{proc.stdout[-4000:]}\n{proc.stderr[-3000:]}"
        )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["heavy_peak"] = render_and_measure(report["heavy_blend"], "heavy", work)
    report["fixed_peak"] = render_and_measure(report["fixed_blend"], "fixed", work)
    return report


# --- the estimate ------------------------------------------------------------


def test_the_heavy_scene_is_genuinely_heavy(doctored):
    """Guards against the whole test passing on a trivial scene."""
    assert doctored["heavy_triangles"] > 1_000_000
    assert 4096 in doctored["heavy_texture_sizes"]
    assert not doctored["heavy_fits"]


def test_estimate_is_within_25_percent_of_the_measured_peak(doctored):
    """M5 acceptance."""
    estimate = doctored["heavy_estimate"]
    actual = doctored["heavy_peak"]
    error = (estimate - actual) / actual
    print(
        f"\nheavy scene: estimated {scene_doctor.format_bytes(estimate)}, "
        f"measured {scene_doctor.format_bytes(actual)}, error {error * 100:+.1f}%"
    )
    assert abs(error) <= TOLERANCE, f"estimate is {error * 100:+.1f}% off"


def test_the_fixed_scene_estimate_is_also_accurate(doctored):
    """The model has to hold after the scene has been degraded, too."""
    estimate = doctored["fixed_estimate"]
    actual = doctored["fixed_peak"]
    error = (estimate - actual) / actual
    print(
        f"\nfixed scene: estimated {scene_doctor.format_bytes(estimate)}, "
        f"measured {scene_doctor.format_bytes(actual)}, error {error * 100:+.1f}%"
    )
    assert abs(error) <= TOLERANCE, f"estimate is {error * 100:+.1f}% off"


# --- the auto-fix ------------------------------------------------------------


def test_autofix_brings_the_projection_under_budget(doctored):
    assert doctored["fixed_fits"]
    assert doctored["fixed_estimate"] < doctored["heavy_estimate"]


def test_autofix_brings_the_measured_render_under_budget(doctored):
    """M5 acceptance, measured rather than projected."""
    assert doctored["heavy_peak"] > doctored["budget"], (
        "the heavy scene did not actually exceed the budget, so this proves nothing"
    )
    assert doctored["fixed_peak"] <= doctored["budget"], (
        f"after auto-fix the render still peaked at "
        f"{scene_doctor.format_bytes(doctored['fixed_peak'])}"
    )


def test_autofix_reported_what_it_did(doctored):
    assert doctored["applied"]
    assert all(isinstance(note, str) and note for note in doctored["applied"])


def test_textures_were_actually_scaled_in_the_saved_file(doctored):
    """image.scale() alone does not survive a .blend round trip; packing does.

    Without the pack, a fresh Blender re-reads the full-size file and the whole
    saving evaporates -- silently, and only in the headless path.
    """
    if not any(fix["kind"] == "texture_scale" for fix in doctored["fixes"]):
        pytest.skip("the ladder did not need a texture fix")
    assert max(doctored["fixed_texture_sizes"]) < max(doctored["heavy_texture_sizes"])


def test_geometry_was_decimated_if_the_ladder_asked_for_it(doctored):
    if not any(fix["kind"] == "decimate" for fix in doctored["fixes"]):
        pytest.skip("the ladder did not need a decimate fix")
    assert doctored["fixed_triangles"] < doctored["heavy_triangles"]


def test_the_decimate_fix_really_reduces_geometry(doctored):
    """Covers apply_fix's decimate branch in a real Blender.

    The ladder stops as soon as the projection fits, so a texture cap alone can
    be enough and this branch would otherwise never run here.
    """
    before = doctored["decimate_before"]
    after = doctored["decimate_after"]
    assert before > 1_000_000
    assert after == pytest.approx(before * 0.25, rel=0.1)
