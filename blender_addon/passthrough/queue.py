"""Launch and supervise the headless render subprocess.

Pure Python -- no ``bpy`` -- so the command building, progress parsing and
process control can be unit tested without Blender. The Blender-side operators
that drive this live in ``scene_capture.py``.

Design note: the child's stdout goes to a **log file** rather than a pipe. A
pipe would have to be drained by a reader thread or it fills and blocks the
render, and it dies with the parent. A log file is non-blocking to poll, and it
survives Blender closing -- which is the entire point of this milestone
(SPEC.md section 3, principle 1).

SPEC.md section 7.6 says to parse progress from lines shaped like
``Fra:12 Mem:412.35M``. Blender 5.1 does not emit those: a background EEVEE
render prints ``00:02.125  render  | Saved: '<path>'`` and nothing else. So
``render_job.py`` prints its own ``PT_`` markers, and all three forms are parsed
here -- the spec's, Blender 5.x's, and ours.
"""

import contextlib
import os
import re
import subprocess
import sys
import time

#: Marker lines render_job.py prints. Explicit, because relying on Blender's
#: own progress output turned out not to work (see the module docstring).
JOB_MARKER = "PT_JOB"
FRAME_MARKER = "PT_FRAME"
DONE_MARKER = "PT_DONE"
ERROR_MARKER = "PT_ERROR"

_FRAME_RE = re.compile(r"^PT_FRAME\s+(\d+)\s*/\s*(\d+)\s*$")
_DONE_RE = re.compile(r"^PT_DONE\s+frames=(\d+)")
_ERROR_RE = re.compile(r"^PT_ERROR\s+(.*)$")
#: The form section 7.6 documents. Kept because a future Blender may restore it.
_FRA_RE = re.compile(r"\bFra:(\d+)\b(?:.*?\bMem:([\d.]+)([KMG]))?")
#: What Blender 5.x actually prints when an image is written.
_SAVED_RE = re.compile(r"\|\s*Saved:\s*'(.+)'\s*$")

_MEMORY_UNITS = {"K": 1024, "M": 1024**2, "G": 1024**3}


class ProgressEvent:
    """One thing worth knowing that happened in the child process."""

    __slots__ = ("kind", "frame", "total", "memory_bytes", "path", "message")

    def __init__(self, kind, frame=None, total=None, memory_bytes=None, path=None, message=None):
        self.kind = kind
        self.frame = frame
        self.total = total
        self.memory_bytes = memory_bytes
        self.path = path
        self.message = message

    def __repr__(self):
        parts = [f"kind={self.kind!r}"]
        for name in ("frame", "total", "memory_bytes", "path", "message"):
            value = getattr(self, name)
            if value is not None:
                parts.append(f"{name}={value!r}")
        return "ProgressEvent(" + ", ".join(parts) + ")"

    def __eq__(self, other):
        if not isinstance(other, ProgressEvent):
            return NotImplemented
        return all(
            getattr(self, name) == getattr(other, name)
            for name in ("kind", "frame", "total", "memory_bytes", "path", "message")
        )


def parse_progress(line):
    """Turn one line of child output into a :class:`ProgressEvent`, or ``None``."""
    text = line.strip()
    if not text:
        return None

    match = _FRAME_RE.match(text)
    if match:
        return ProgressEvent("frame", frame=int(match.group(1)), total=int(match.group(2)))

    match = _DONE_RE.match(text)
    if match:
        return ProgressEvent("done", frame=int(match.group(1)))

    match = _ERROR_RE.match(text)
    if match:
        return ProgressEvent("error", message=match.group(1).strip())

    match = _FRA_RE.search(text)
    if match:
        memory = None
        if match.group(2) and match.group(3):
            memory = float(match.group(2)) * _MEMORY_UNITS[match.group(3)]
        return ProgressEvent("frame", frame=int(match.group(1)), memory_bytes=memory)

    match = _SAVED_RE.search(text)
    if match:
        return ProgressEvent("saved", path=match.group(1))

    return None


def build_command(
    blender, blend_file, script, shot, output_root, frame_start, frame_end, extra=None
):
    """The ``blender -b ... -P ... -- ...`` command line from SPEC.md section 7.6."""
    if frame_end < frame_start:
        raise ValueError("frame_end is before frame_start")
    command = [
        str(blender),
        "-b",
        str(blend_file),
        "-P",
        str(script),
        "--",
        "--shot",
        str(shot),
        "--out",
        str(output_root),
        "--start",
        str(int(frame_start)),
        "--end",
        str(int(frame_end)),
    ]
    if extra:
        command.extend(str(item) for item in extra)
    return command


def peak_working_set_bytes(pid):
    """Peak resident memory of a live process, or ``None`` if unavailable.

    Windows only, via ctypes -- the project has no third-party dependencies and
    SPEC.md section 9 asks for peak memory to be logged on every integration
    run. Must be sampled while the process is alive; once it exits the pid can
    be recycled.
    """
    if sys.platform != "win32":
        return None

    import ctypes
    import ctypes.wintypes

    class _Counters(ctypes.Structure):
        _fields_ = [
            ("cb", ctypes.wintypes.DWORD),
            ("PageFaultCount", ctypes.wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    kernel32 = ctypes.windll.kernel32
    psapi = ctypes.windll.psapi

    for access in (0x1000, 0x0400 | 0x0010):  # LIMITED_INFORMATION, then QUERY|VM_READ
        handle = kernel32.OpenProcess(access, False, int(pid))
        if handle:
            try:
                counters = _Counters()
                counters.cb = ctypes.sizeof(counters)
                if psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
                    return int(counters.PeakWorkingSetSize)
            finally:
                kernel32.CloseHandle(handle)
    return None


class RenderJob:
    """A running headless render.

    ``poll()`` is the pump: it reads whatever the child has written since last
    time and returns the events. Nothing blocks, so a Blender modal operator can
    call it from a timer.
    """

    def __init__(self, command, log_path, detached=False):
        self.command = list(command)
        self.log_path = str(log_path)
        self.detached = detached
        self.process = None
        self.events = []
        self.frame = None
        self.total = None
        self.peak_memory_bytes = 0
        self.error = None
        self._log_write = None
        self._log_read = None
        self._started_at = None

    # -- lifecycle ------------------------------------------------------------

    def start(self):
        if self.process is not None:
            raise RuntimeError("job already started")

        directory = os.path.dirname(self.log_path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        # Held open for the child's lifetime, so a context manager cannot own it.
        self._log_write = open(self.log_path, "wb")  # noqa: SIM115

        kwargs = {
            "stdout": self._log_write,
            "stderr": subprocess.STDOUT,
            "stdin": subprocess.DEVNULL,
        }
        if self.detached and sys.platform == "win32":
            # Survives this Blender exiting, which is the point of the milestone.
            kwargs["creationflags"] = 0x00000008 | 0x00000200  # DETACHED | NEW_PROCESS_GROUP

        self._started_at = time.monotonic()
        self.process = subprocess.Popen(self.command, **kwargs)
        return self.process

    @property
    def running(self):
        return self.process is not None and self.process.poll() is None

    @property
    def returncode(self):
        return None if self.process is None else self.process.poll()

    @property
    def elapsed_seconds(self):
        return 0.0 if self._started_at is None else time.monotonic() - self._started_at

    # -- progress -------------------------------------------------------------

    def poll(self):
        """Read newly written output. Returns the events found this call."""
        if self.process is not None:
            sampled = peak_working_set_bytes(self.process.pid)
            if sampled:
                self.peak_memory_bytes = max(self.peak_memory_bytes, sampled)

        found = []
        for line in self._read_new_lines():
            event = parse_progress(line)
            if event is None:
                continue
            found.append(event)
            self.events.append(event)
            if event.kind == "frame":
                self.frame = event.frame
                if event.total:
                    self.total = event.total
                if event.memory_bytes:
                    self.peak_memory_bytes = max(self.peak_memory_bytes, event.memory_bytes)
            elif event.kind == "error":
                self.error = event.message
        return found

    def _read_new_lines(self):
        if self._log_read is None:
            if not os.path.exists(self.log_path):
                return []
            # errors="replace": Blender writes console decoration that is not
            # valid in the Windows locale encoding.
            # Also long-lived: the read position is what makes polling incremental.
            self._log_read = open(  # noqa: SIM115
                self.log_path, encoding="utf-8", errors="replace"
            )
        return self._log_read.readlines()

    @property
    def progress_fraction(self):
        """0.0 to 1.0, or ``None`` when the frame count is not known yet."""
        if not self.total or self.frame is None:
            return None
        return max(0.0, min(1.0, self.frame / self.total))

    # -- shutdown -------------------------------------------------------------

    def cancel(self, timeout=10.0):
        """Ask the child to stop, then insist. Returns the exit code."""
        if self.process is None:
            return None
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=timeout)
        return self.close()

    def close(self):
        """Release the log handles. Safe to call more than once."""
        for attr in ("_log_write", "_log_read"):
            handle = getattr(self, attr)
            if handle is not None:
                with contextlib.suppress(OSError):
                    handle.close()
                setattr(self, attr, None)
        return self.returncode

    def wait(self, timeout=None, interval=0.05):
        """Block until the child exits, pumping progress as it goes."""
        deadline = None if timeout is None else time.monotonic() + timeout
        while self.running:
            self.poll()
            if deadline is not None and time.monotonic() > deadline:
                raise TimeoutError(f"render did not finish within {timeout}s")
            time.sleep(interval)
        self.poll()
        return self.close()


def format_bytes(count):
    """Human-readable size, for progress messages and the memory log."""
    if not count:
        return "0 B"
    for unit in ("B", "KB", "MB", "GB"):
        if count < 1024 or unit == "GB":
            return f"{count:.0f} {unit}" if unit == "B" else f"{count:.2f} {unit}"
        count /= 1024.0
    return f"{count:.2f} GB"
