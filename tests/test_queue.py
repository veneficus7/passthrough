"""Unit tests for the render subprocess manager.

No Blender here: the job lifecycle is exercised with a small Python child, which
is what keeping ``queue.py`` free of ``bpy`` buys.
"""

import sys
import textwrap
from pathlib import Path

import pytest
from passthrough import queue

# --- progress parsing --------------------------------------------------------


def test_parses_our_own_frame_marker():
    event = queue.parse_progress("PT_FRAME 12/120")
    assert event.kind == "frame"
    assert (event.frame, event.total) == (12, 120)


def test_parses_done_and_error_markers():
    assert queue.parse_progress("PT_DONE frames=120").kind == "done"
    error = queue.parse_progress("PT_ERROR RuntimeError: no camera")
    assert error.kind == "error"
    assert error.message == "RuntimeError: no camera"


def test_parses_the_form_the_spec_documents():
    """Section 7.6's `Fra:12 Mem:412.35M`.

    Blender 5.1 does not actually emit this, but the parser keeps it: it costs
    nothing and a future version may restore it.
    """
    event = queue.parse_progress("Fra:12 Mem:412.35M | Time:00:02.11 | Compositing")
    assert event.kind == "frame"
    assert event.frame == 12
    assert event.memory_bytes == pytest.approx(412.35 * 1024**2)


@pytest.mark.parametrize(("suffix", "multiplier"), [("K", 1024), ("M", 1024**2), ("G", 1024**3)])
def test_memory_units(suffix, multiplier):
    event = queue.parse_progress(f"Fra:1 Mem:2.5{suffix}")
    assert event.memory_bytes == pytest.approx(2.5 * multiplier)


def test_parses_the_form_blender_5_actually_emits():
    line = r"00:02.125  render           | Saved: 'C:\out\hall\beauty\beauty_0001.exr'"
    event = queue.parse_progress(line)
    assert event.kind == "saved"
    assert event.path.endswith("beauty_0001.exr")


@pytest.mark.parametrize(
    "line", ["", "   ", "Blender quit", "Info: Saved as scene.blend", "random noise"]
)
def test_uninteresting_lines_are_ignored(line):
    assert queue.parse_progress(line) is None


# --- command building --------------------------------------------------------


def test_build_command_matches_section_7_6():
    command = queue.build_command(
        "blender.exe", "scene.blend", "render_job.py", "hall", "C:/out", 1, 120
    )
    assert command[:6] == ["blender.exe", "-b", "scene.blend", "-P", "render_job.py", "--"]
    tail = command[6:]
    assert tail == ["--shot", "hall", "--out", "C:/out", "--start", "1", "--end", "120"]


def test_build_command_appends_extra_arguments():
    command = queue.build_command("b", "s", "r", "hall", "o", 1, 2, extra=["--samples", "16"])
    assert command[-2:] == ["--samples", "16"]


def test_build_command_rejects_a_reversed_range():
    with pytest.raises(ValueError):
        queue.build_command("b", "s", "r", "hall", "o", 10, 2)


# --- formatting --------------------------------------------------------------


@pytest.mark.parametrize(
    ("count", "expected"),
    [(0, "0 B"), (512, "512 B"), (1536, "1.50 KB"), (5 * 1024**3, "5.00 GB")],
)
def test_format_bytes(count, expected):
    assert queue.format_bytes(count) == expected


# --- job lifecycle -----------------------------------------------------------


def write_child(tmp_path, body):
    script = tmp_path / "child.py"
    script.write_text(textwrap.dedent(body), encoding="utf-8")
    return script


@pytest.fixture
def finished_job(tmp_path):
    script = write_child(
        tmp_path,
        """
        import sys, time
        print("PT_JOB shot=hall start=1 end=3", flush=True)
        for i in (1, 2, 3):
            print("PT_FRAME %d/3" % i, flush=True)
            time.sleep(0.02)
        print("PT_DONE frames=3", flush=True)
        """,
    )
    job = queue.RenderJob([sys.executable, str(script)], tmp_path / "render.log")
    job.start()
    job.wait(timeout=60)
    return job


def test_job_runs_to_completion(finished_job):
    assert finished_job.returncode == 0
    assert not finished_job.running


def test_job_tracks_progress(finished_job):
    assert finished_job.frame == 3
    assert finished_job.total == 3
    assert finished_job.progress_fraction == pytest.approx(1.0)


def test_job_records_every_event(finished_job):
    kinds = [event.kind for event in finished_job.events]
    assert kinds.count("frame") == 3
    assert "done" in kinds


def test_job_writes_a_log_that_survives(finished_job):
    text = Path(finished_job.log_path).read_text(encoding="utf-8")
    assert "PT_DONE frames=3" in text


@pytest.mark.skipif(sys.platform != "win32", reason="peak working set is measured via Win32")
def test_job_measures_peak_memory(finished_job):
    """SPEC.md section 9 wants peak memory logged on every run."""
    assert finished_job.peak_memory_bytes > 0


def test_job_reports_child_failure(tmp_path):
    script = write_child(
        tmp_path,
        """
        import sys
        print("PT_ERROR RuntimeError: the scene has no camera", flush=True)
        sys.exit(1)
        """,
    )
    job = queue.RenderJob([sys.executable, str(script)], tmp_path / "render.log")
    job.start()
    job.wait(timeout=60)
    assert job.returncode == 1
    assert job.error == "RuntimeError: the scene has no camera"


def test_cancelling_terminates_the_child(tmp_path):
    """M3 acceptance: cancelling terminates the child process cleanly."""
    script = write_child(
        tmp_path,
        """
        import time
        print("PT_FRAME 1/10000", flush=True)
        time.sleep(120)
        """,
    )
    job = queue.RenderJob([sys.executable, str(script)], tmp_path / "render.log")
    process = job.start()
    for _ in range(200):
        job.poll()
        if job.frame:
            break
    assert job.running, "child exited before it could be cancelled"

    job.cancel(timeout=30)
    assert not job.running
    assert process.poll() is not None
    assert job.returncode != 0


def test_cancel_is_safe_before_start(tmp_path):
    job = queue.RenderJob([sys.executable, "-c", "pass"], tmp_path / "render.log")
    assert job.cancel() is None


def test_starting_twice_is_refused(tmp_path):
    job = queue.RenderJob([sys.executable, "-c", "pass"], tmp_path / "render.log")
    job.start()
    with pytest.raises(RuntimeError):
        job.start()
    job.wait(timeout=30)


def test_close_is_idempotent(finished_job):
    assert finished_job.close() == 0
    assert finished_job.close() == 0


def test_progress_fraction_is_none_before_any_frame(tmp_path):
    job = queue.RenderJob([sys.executable, "-c", "pass"], tmp_path / "render.log")
    assert job.progress_fraction is None


def test_wait_times_out_on_a_hung_child(tmp_path):
    script = write_child(tmp_path, "import time\ntime.sleep(120)\n")
    job = queue.RenderJob([sys.executable, str(script)], tmp_path / "render.log")
    job.start()
    try:
        with pytest.raises(TimeoutError):
            job.wait(timeout=0.5)
    finally:
        job.cancel(timeout=30)
