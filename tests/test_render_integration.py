"""M3 acceptance: the headless render, driven through the real queue.

Runs the section 7.6 command line for real, then checks the output tree, the
progress reporting, the peak memory and cancellation.
"""

import subprocess
import sys
import time
from pathlib import Path

import pytest
from passthrough import pass_spec, queue
from test_passes_integration import ADDON_PARENT, BLENDER

RENDER_SCRIPT = ADDON_PARENT / "passthrough" / "render_job.py"
SCENE_MAKER = Path(__file__).parent / "blender_make_scene.py"

SHOT = "hall"
FRAME_START, FRAME_END = 1, 4

#: M3 acceptance. The fixture scene is tiny, so this is a ceiling with room to
#: spare rather than a tight bound -- but it is the number the spec names, and a
#: regression that blows past it is exactly what section 9 asks to catch.
PEAK_MEMORY_LIMIT = 6 * 1024**3

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(BLENDER is None, reason="Blender not found"),
]


@pytest.fixture(scope="module")
def blend_file(tmp_path_factory):
    path = tmp_path_factory.mktemp("m3scene") / "scene.blend"
    proc = subprocess.run(
        [BLENDER, "-b", "--factory-startup", "--python", str(SCENE_MAKER), "--", str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
    )
    if "PT_SCENE_SAVED" not in proc.stdout or not path.is_file():
        pytest.fail(f"could not build fixture scene\n{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}")
    return path


@pytest.fixture(scope="module")
def rendered(blend_file, tmp_path_factory):
    output_root = tmp_path_factory.mktemp("m3out")
    job = queue.RenderJob(
        queue.build_command(
            BLENDER, blend_file, RENDER_SCRIPT, SHOT, output_root, FRAME_START, FRAME_END
        ),
        output_root / "render.log",
    )
    job.start()
    job.wait(timeout=900)
    if job.returncode != 0:
        log = Path(job.log_path).read_text(encoding="utf-8", errors="replace")
        pytest.fail(f"render exited {job.returncode}\n{log[-4000:]}")
    return job, output_root


# --- the render --------------------------------------------------------------


def test_render_completes_without_the_blender_ui(rendered):
    """M3 acceptance: launched headlessly, finishes on its own."""
    job, _ = rendered
    assert job.returncode == 0
    assert job.error is None


def test_progress_is_reported(rendered):
    """M3 acceptance: progress is reported."""
    job, _ = rendered
    frames = [event for event in job.events if event.kind == "frame"]
    assert len(frames) == FRAME_END - FRAME_START + 1
    assert job.frame == FRAME_END - FRAME_START + 1
    assert job.progress_fraction == pytest.approx(1.0)


def test_the_job_finished_marker_is_emitted(rendered):
    job, _ = rendered
    assert any(event.kind == "done" for event in job.events)


def test_output_is_exactly_the_section_7_3_tree(rendered):
    """No stray main render output: rendering frame by frame avoids it."""
    _, output_root = rendered
    expected = pass_spec.expected_files(str(output_root), SHOT, FRAME_START, FRAME_END)
    wanted = {Path(p).resolve() for paths in expected.values() for p in paths}

    shot_dir = Path(pass_spec.shot_dir(str(output_root), SHOT))
    actual = {p.resolve() for p in shot_dir.rglob("*") if p.is_file()}

    assert actual == wanted


def test_colour_management_is_forced_not_inherited(rendered):
    """Section 7.4: AgX baked into a pass is the muddy-looking failure."""
    job, _ = rendered
    log = Path(job.log_path).read_text(encoding="utf-8", errors="replace")
    colour = [line for line in log.splitlines() if line.startswith("PT_COLOUR")]
    assert colour, "render_job did not report its colour management"
    assert "'view_transform': 'Raw'" in colour[0]


@pytest.mark.skipif(sys.platform != "win32", reason="peak working set is measured through Win32")
def test_peak_memory_stays_under_the_budget(rendered):
    """M3 acceptance: peak RAM under 6 GB. Section 9 wants it logged each run."""
    job, _ = rendered
    peak = job.peak_memory_bytes
    print(f"\npeak working set for the fixture render: {queue.format_bytes(peak)}")
    assert peak > 0, "peak memory was never sampled"
    assert peak < PEAK_MEMORY_LIMIT, (
        f"peak {queue.format_bytes(peak)} exceeds the "
        f"{queue.format_bytes(PEAK_MEMORY_LIMIT)} budget"
    )


# --- cancellation ------------------------------------------------------------


def test_cancelling_terminates_the_render_cleanly(blend_file, tmp_path):
    """M3 acceptance: cancelling terminates the child process cleanly."""
    output_root = tmp_path / "cancel"
    job = queue.RenderJob(
        queue.build_command(BLENDER, blend_file, RENDER_SCRIPT, "cancelme", output_root, 1, 5000),
        output_root / "render.log",
    )
    process = job.start()

    # Wait until the child has genuinely started working, so this is not just
    # killing a process that had not begun. Blender needs a second or two to
    # start, so this has to be a real wait rather than a busy loop.
    deadline = time.monotonic() + 120.0
    while time.monotonic() < deadline:
        job.poll()
        if job.events:
            break
        if not job.running:
            pytest.fail("the render exited before it could be cancelled")
        time.sleep(0.1)
    else:
        pytest.fail("the render never reported anything to cancel")
    assert job.running

    job.cancel(timeout=60)

    assert not job.running
    assert process.poll() is not None
    frames_written = list((output_root / "cancelme").rglob("*.exr"))
    assert len(frames_written) < 5000, "the render somehow ran to completion"
