"""Estimate what a render will cost in memory, and how to make it fit.

Pure Python, no ``bpy`` (SPEC.md section 6). Takes a plain description of the
scene and returns an estimate, findings, and a list of fixes for the Blender
side to apply.

The coefficients are measured, not guessed. Seventeen scenes were built as
.blend files, rendered headlessly through ``render_job.py``, and their peak
working set sampled from the parent process. A least-squares fit over that set
lands within 5.7% on every scene; the constants below are that fit rounded
*upward*, which costs a little accuracy (worst case 16.1%) in exchange for
almost never claiming a scene fits when it does not. Under-estimating is the
dangerous direction: it ends in the out-of-memory crash this project exists to
avoid.

Measuring is also why the numbers look different from a first attempt: building
a 2M-triangle grid with a Blender operator spikes memory in ways that loading
the finished .blend never does. Construction has to be measured separately from
rendering, or the geometry term comes out three times too large.
"""

from dataclasses import dataclass, field

MB = 1024**2
GB = 1024**3

#: Blender itself, headless, with nothing in the scene.
BASE_BYTES = 480 * MB

#: Render buffers, per pixel of output. Five passes of RGBA float plus the
#: render result and the compositor's own buffers.
BYTES_PER_PIXEL = 175.0

#: Evaluated mesh, per triangle.
BYTES_PER_TRIANGLE = 135.0

#: Multiplier on the raw image byte count once Blender has it loaded.
TEXTURE_FACTOR = 1.45

#: M3's ceiling: 16 GB of RAM, roughly 11 GB usable, and After Effects wants
#: the rest (SPEC.md section 5).
DEFAULT_BUDGET_BYTES = 6 * GB

#: Ladders the auto-fix walks down, in the order SPEC.md M5 lists them.
TEXTURE_LIMITS = (2048, 1024, 512)
DECIMATE_RATIOS = (0.5, 0.25, 0.1)
RESOLUTION_PERCENTAGES = (75, 50, 25)

#: Objects below this are left alone; decimating them buys nothing.
DECIMATE_TRIANGLE_THRESHOLD = 50_000


@dataclass(frozen=True)
class Estimate:
    """Projected peak memory, and where it goes."""

    base: int
    pixels: int
    geometry: int
    textures: int

    @property
    def total(self):
        return self.base + self.pixels + self.geometry + self.textures

    def breakdown(self):
        return {
            "base": self.base,
            "pixels": self.pixels,
            "geometry": self.geometry,
            "textures": self.textures,
        }


@dataclass(frozen=True)
class Fix:
    """One change the Blender side can apply. Pure data; nothing is applied here."""

    kind: str
    description: str
    saves: int
    detail: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Report:
    estimate: Estimate
    budget: int
    fixes: tuple = ()

    @property
    def fits(self):
        return self.estimate.total <= self.budget

    @property
    def projected_after_fixes(self):
        return self.estimate.total - sum(fix.saves for fix in self.fixes)

    @property
    def fixable(self):
        return self.projected_after_fixes <= self.budget


def format_bytes(count):
    """Human-readable size. Mirrors queue.format_bytes so reports read alike."""
    count = float(count)
    for unit in ("B", "KB", "MB", "GB"):
        if count < 1024 or unit == "GB":
            return f"{count:.0f} {unit}" if unit == "B" else f"{count:.2f} {unit}"
        count /= 1024.0
    return f"{count:.2f} GB"


def image_bytes(width, height, channels=4, depth=8):
    """Raw bytes one image occupies, before Blender's overhead."""
    return int(width) * int(height) * int(channels) * (int(depth) // 8)


def render_pixels(resolution_x, resolution_y, resolution_percentage=100):
    """Output pixels, after the resolution percentage Blender applies."""
    scale = resolution_percentage / 100.0
    return int(round(resolution_x * scale)) * int(round(resolution_y * scale))


def total_triangles(objects):
    return sum(int(obj.get("triangles", 0)) for obj in objects)


def total_texture_bytes(textures, limit=None):
    """Bytes for every texture, optionally with each dimension capped at ``limit``."""
    total = 0
    for texture in textures:
        width = int(texture["width"])
        height = int(texture["height"])
        if limit:
            if width > limit:
                height = max(1, int(round(height * limit / width)))
                width = limit
            if height > limit:
                width = max(1, int(round(width * limit / height)))
                height = limit
        total += image_bytes(width, height, texture.get("channels", 4), texture.get("depth", 8))
    return total


def estimate(stats):
    """Projected peak memory for rendering ``stats``."""
    pixels = render_pixels(
        stats["resolution_x"], stats["resolution_y"], stats.get("resolution_percentage", 100)
    )
    triangles = total_triangles(stats.get("objects", ()))
    texture_bytes = total_texture_bytes(stats.get("textures", ()))
    return Estimate(
        base=int(BASE_BYTES),
        pixels=int(BYTES_PER_PIXEL * pixels),
        geometry=int(BYTES_PER_TRIANGLE * triangles),
        textures=int(TEXTURE_FACTOR * texture_bytes),
    )


def plan_fixes(stats, budget=DEFAULT_BUDGET_BYTES):
    """Greedy ladder of changes until the estimate fits, least harmful first.

    The order is the one SPEC.md M5 gives: textures, then geometry, then render
    resolution. It is also the order of least regret -- a smaller texture is
    rarely visible at 1080x1920, whereas clamping the render resolution changes
    the deliverable itself.
    """
    current = estimate(stats).total
    if current <= budget:
        return ()

    fixes = []
    textures = list(stats.get("textures", ()))
    objects = list(stats.get("objects", ()))

    original_texture_bytes = total_texture_bytes(textures)
    for limit in TEXTURE_LIMITS:
        if current <= budget:
            break
        capped = total_texture_bytes(textures, limit)
        saving = int(TEXTURE_FACTOR * (original_texture_bytes - capped))
        already = sum(fix.saves for fix in fixes if fix.kind == "texture_scale")
        gain = saving - already
        if gain <= 0:
            continue
        oversized = [t["name"] for t in textures if max(t["width"], t["height"]) > limit]
        fixes = [fix for fix in fixes if fix.kind != "texture_scale"]
        fixes.append(
            Fix(
                kind="texture_scale",
                description=(
                    f"Cap {len(oversized)} texture(s) at {limit}px, saving {format_bytes(saving)}"
                ),
                saves=saving,
                detail={"limit": limit, "images": oversized},
            )
        )
        current = estimate(stats).total - sum(fix.saves for fix in fixes)

    heavy = [obj for obj in objects if int(obj.get("triangles", 0)) >= DECIMATE_TRIANGLE_THRESHOLD]
    heavy_triangles = total_triangles(heavy)
    for ratio in DECIMATE_RATIOS:
        if current <= budget or not heavy:
            break
        saving = int(BYTES_PER_TRIANGLE * heavy_triangles * (1.0 - ratio))
        fixes = [fix for fix in fixes if fix.kind != "decimate"]
        fixes.append(
            Fix(
                kind="decimate",
                description=(
                    f"Decimate {len(heavy)} object(s) to {ratio:.0%}, saving {format_bytes(saving)}"
                ),
                saves=saving,
                detail={"ratio": ratio, "objects": [obj["name"] for obj in heavy]},
            )
        )
        current = estimate(stats).total - sum(fix.saves for fix in fixes)

    full_pixels = render_pixels(stats["resolution_x"], stats["resolution_y"], 100)
    for percent in RESOLUTION_PERCENTAGES:
        if current <= budget:
            break
        reduced = render_pixels(stats["resolution_x"], stats["resolution_y"], percent)
        saving = int(BYTES_PER_PIXEL * (full_pixels - reduced))
        fixes = [fix for fix in fixes if fix.kind != "resolution"]
        fixes.append(
            Fix(
                kind="resolution",
                description=(f"Render at {percent}% resolution, saving {format_bytes(saving)}"),
                saves=saving,
                detail={"percentage": percent},
            )
        )
        current = estimate(stats).total - sum(fix.saves for fix in fixes)

    return tuple(fixes)


def diagnose(stats, budget=DEFAULT_BUDGET_BYTES):
    """Estimate the render, and work out what would make it fit."""
    projected = estimate(stats)
    fixes = () if projected.total <= budget else plan_fixes(stats, budget)
    return Report(estimate=projected, budget=budget, fixes=fixes)


def summarise(report):
    """A few lines suitable for a panel or the console."""
    lines = [
        f"Projected peak: {format_bytes(report.estimate.total)} of {format_bytes(report.budget)}"
    ]
    for name, value in report.estimate.breakdown().items():
        lines.append(f"  {name}: {format_bytes(value)}")
    if report.fits:
        lines.append("Fits the budget.")
        return lines
    lines.append("Over budget. Suggested fixes:")
    for fix in report.fixes:
        lines.append(f"  - {fix.description}")
    lines.append(
        f"After fixes: {format_bytes(report.projected_after_fixes)}"
        + ("" if report.fixable else " (still over budget)")
    )
    return lines
