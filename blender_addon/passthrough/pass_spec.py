"""The pass manifest: what Passthrough renders, and where every file lands.

Pure Python, no ``bpy`` (SPEC.md section 6). ``passes.py`` builds the Blender
node tree from this table; ``jsx_writer.py`` will predict every import path from
the same table without inspecting the disk (section 7.3). Keeping both sides on
one source of truth is what makes those predictions safe.
"""

from dataclasses import dataclass

#: Blender substitutes the frame number for this token in an output file name.
FRAME_TOKEN = "####"

#: One image sequence per pass, never multi-layer EXR (section 7.3).
EXTENSION = ".exr"

#: Lossless. Never DWAA/DWAB here: they are lossy, and lossy cryptomatte IDs
#: are meaningless.
EXR_CODEC = "ZIP"

#: File Output items must be left UNNAMED. Blender uses the item name as an EXR
#: layer prefix, so an item called "beauty" writes channels ``beauty.R`` and
#: friends instead of plain ``R``/``G``/``B``/``A``. After Effects reads the
#: unprefixed channels, so a named item produces a file AE cannot see -- the
#: same trap section 7.3 is trying to avoid with multi-layer EXR. Verified by
#: reading the written EXR headers on Blender 5.1.2.
OUTPUT_ITEM_NAME = ""

#: Cryptomatte ranks. Each RGBA layer carries two ranks, so a depth of 2 is
#: exactly one ``CryptoObject00`` socket, which is what lets the crypto pass be
#: a single flat EXR per section 7.3 rather than a silently truncated slice of a
#: deeper matte. Verified against Blender 5.1.2: depth 2 -> 1 socket, 4 -> 2,
#: 6 -> 3.
CRYPTOMATTE_DEPTH = 2

_UNSAFE_NAME_CHARS = r'<>:"/\|?*'


@dataclass(frozen=True)
class PassSpec:
    """One render pass, from view layer flag through to its folder on disk."""

    key: str
    """Folder name and file stem, e.g. ``beauty`` -> ``beauty/beauty_0001.exr``."""

    socket: str
    """Output socket name on the Render Layers node."""

    view_layer_flag: str
    """``ViewLayer`` attribute that turns the pass on."""

    label: str
    """Human-readable name, used in the panel and later as the AE layer name."""

    color_depth: str = "16"
    """EXR bit depth. Half float halves disk and memory, which is the whole
    point of this project, and is plenty for colour and normals."""

    note: str = ""
    """What the pass is for, written into the After Effects layer's Comment.

    A disabled guide layer with no explanation is a puzzle. The cryptomatte one
    in particular renders black in After Effects, which looks like a broken
    export unless you already know why."""


#: v1 pass set, in the order section 7.3 lists them. Ambient Occlusion and
#: Vector are deliberately absent; the spec defers them.
PASSES = (
    PassSpec(
        "beauty",
        "Image",
        "use_pass_combined",
        "Beauty",
        note="The rendered image. This is your base layer.",
    ),
    PassSpec(
        "emission",
        "Emission",
        "use_pass_emit",
        "Emission",
        note="Glowing surfaces only. Try Add mode over Beauty for bloom you control.",
    ),
    PassSpec(
        "mist",
        "Mist",
        "use_pass_mist",
        "Mist",
        note="Distance from camera, white is far. Drives depth of field and haze.",
    ),
    PassSpec(
        "normal",
        "Normal",
        "use_pass_normal",
        "Normal",
        note="Surface direction as RGB. Relighting and direction-based masks.",
    ),
    # Cryptomatte stores object-id hashes as raw float bits. Rounding them to
    # half float destroys the ids, so this pass must stay 32-bit.
    PassSpec(
        "crypto",
        "CryptoObject00",
        "use_pass_cryptomatte_object",
        "Cryptomatte Object",
        color_depth="32",
        note=(
            "Object ID mattes, not a picture. Renders BLACK in After Effects: "
            "Blender writes lowercase r/g/b/a channels and AE reads uppercase. "
            "Needs a Cryptomatte plugin to be useful. Leave this layer off."
        ),
    ),
)

PASS_KEYS = tuple(spec.key for spec in PASSES)


def get_pass(key):
    """Return the :class:`PassSpec` for ``key``, or raise ``KeyError``."""
    for spec in PASSES:
        if spec.key == key:
            return spec
    raise KeyError(key)


def sanitize_shot_name(name):
    """Reduce ``name`` to something safe to use as a folder name.

    Falls back to ``shot`` rather than returning an empty string, because an
    empty shot name would silently write passes straight into the output root.
    """
    cleaned = "".join("_" if ch in _UNSAFE_NAME_CHARS else ch for ch in (name or "").strip())
    cleaned = cleaned.strip(" .")
    return cleaned or "shot"


def normalize_root(output_root):
    """Normalise separators and drop any trailing slash.

    Blender accepts forward slashes on Windows, so the whole pipeline uses them
    and stays comparable in tests.
    """
    return (output_root or "").replace("\\", "/").rstrip("/")


def shot_dir(output_root, shot_name):
    """``<output_root>/<shot_name>``."""
    return f"{normalize_root(output_root)}/{sanitize_shot_name(shot_name)}"


def pass_dir(output_root, shot_name, key):
    """``<output_root>/<shot_name>/<key>``."""
    return f"{shot_dir(output_root, shot_name)}/{key}"


def frame_pattern(key):
    """File name Blender is given, e.g. ``beauty_####``."""
    return f"{key}_{FRAME_TOKEN}"


def frame_filename(key, frame):
    """Concrete file name for one frame, e.g. ``beauty_0001.exr``."""
    return f"{key}_{frame:04d}{EXTENSION}"


def frame_path(output_root, shot_name, key, frame):
    """Full path of one rendered frame of one pass."""
    return f"{pass_dir(output_root, shot_name, key)}/{frame_filename(key, frame)}"


def expected_files(output_root, shot_name, frame_start, frame_end):
    """Every file a completed render should have written, keyed by pass.

    This is the prediction ``jsx_writer.py`` will import from, and what the
    integration test asserts against.
    """
    return {
        spec.key: [
            frame_path(output_root, shot_name, spec.key, frame)
            for frame in range(frame_start, frame_end + 1)
        ]
        for spec in PASSES
    }
