"""Unit tests for the ExtendScript emitter (SPEC.md sections 7.1 and 6)."""

import re

import pytest
from passthrough import jsx_writer

COMP = {
    "name": "hallway",
    "width": 1080,
    "height": 1920,
    "pixel_aspect": 1.0,
    "frame_rate": 24.0,
    "frame_start": 1,
    "frame_end": 3,
}

CAMERA = {
    "name": "Blender Camera",
    "position": [(1.0, 2.0, 3.0), (4.0, 5.0, 6.0), (7.0, 8.0, 9.0)],
    "orientation": [(0.0, 0.0, 0.0), (1.0, 2.0, 3.0), (4.0, 5.0, 6.0)],
    "zoom": [2666.0, 2666.0, 2700.0],
}


def strip_js_comments(source):
    """Remove // and /* */ comments, leaving string literals intact.

    Needed because the runtime's header comment names the very constructs the
    ES3 check forbids.
    """
    out = []
    i = 0
    n = len(source)
    while i < n:
        ch = source[i]
        if ch in ('"', "'"):
            quote = ch
            out.append(ch)
            i += 1
            while i < n:
                out.append(source[i])
                if source[i] == "\\":
                    i += 2
                    if i <= n:
                        out.append(source[i - 1])
                    continue
                if source[i] == quote:
                    i += 1
                    break
                i += 1
            continue
        if source.startswith("//", i):
            while i < n and source[i] != "\n":
                i += 1
            continue
        if source.startswith("/*", i):
            end = source.find("*/", i + 2)
            i = n if end == -1 else end + 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


#: Constructs ExtendScript does not have (section 7.1). Some fail silently,
#: which is why this is checked mechanically rather than by eye.
ES3_VIOLATIONS = {
    "let declaration": r"\blet\s+[A-Za-z_$]",
    "const declaration": r"\bconst\s+[A-Za-z_$]",
    "arrow function": r"=>",
    "template literal": r"`",
    "JSON": r"\bJSON\s*\.",
    "Array.forEach": r"\.forEach\s*\(",
    "Array.map": r"\.map\s*\(",
    "Array.filter": r"\.filter\s*\(",
    "Array.indexOf": r"\.indexOf\s*\(",
    "String.trim": r"\.trim\s*\(",
    "Object.keys": r"\bObject\s*\.\s*keys\b",
}


def assert_balanced(source, label):
    """Delimiters must balance outside strings and comments.

    Not a parser -- there is no JS engine on this machine -- but it catches the
    structural damage that matters: a truncated emit, a dropped brace, an
    unterminated string. ExtendScript reports such errors at a line number in a
    concatenated file, which is a miserable way to find them.
    """
    code = strip_js_comments(source)
    stack = []
    pairs = {")": "(", "]": "[", "}": "{"}
    in_string = None
    index = 0
    while index < len(code):
        ch = code[index]
        if in_string:
            if ch == "\\":
                index += 2
                continue
            if ch == in_string:
                in_string = None
        elif ch in ('"', "'"):
            in_string = ch
        elif ch in "([{":
            stack.append(ch)
        elif ch in pairs:
            if not stack or stack.pop() != pairs[ch]:
                raise AssertionError(f"{label}: unbalanced {ch!r} at offset {index}")
        index += 1
    assert in_string is None, f"{label}: unterminated string literal"
    assert not stack, f"{label}: {len(stack)} unclosed {''.join(stack)!r}"


def assert_es3(source, label):
    code = strip_js_comments(source)
    for name, pattern in ES3_VIOLATIONS.items():
        match = re.search(pattern, code)
        if match is not None:
            excerpt = code[max(0, match.start() - 40) : match.end() + 40]
            raise AssertionError(f"{label} uses {name}: {excerpt!r}")


# --- number and string formatting -------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [(0.0, "0"), (-0.0, "0"), (1.0, "1"), (1.5, "1.5"), (-2.25, "-2.25"), (1080, "1080")],
)
def test_format_number(value, expected):
    assert jsx_writer.format_number(value) == expected


def test_format_number_round_trips():
    value = 2666.6666666666665
    assert float(jsx_writer.format_number(value)) == value


@pytest.mark.parametrize("bad", [float("inf"), float("-inf"), float("nan")])
def test_format_number_rejects_non_finite(bad):
    with pytest.raises(ValueError):
        jsx_writer.format_number(bad)


def test_js_string_escapes_quotes_and_backslashes():
    assert jsx_writer.js_string('a"b') == '"a\\"b"'
    assert jsx_writer.js_string("a" + chr(92) + "b") == '"a\\\\b"'


def test_js_string_escapes_newlines_and_non_ascii():
    assert jsx_writer.js_string("a\nb") == '"a\\nb"'
    assert jsx_writer.js_string("café") == '"caf\\u00e9"'


def test_js_arrays():
    assert jsx_writer.js_number_array([1.0, 2.5]) == "[1, 2.5]"
    assert jsx_writer.js_vector_array([(1.0, 2.0, 3.0)]) == "[[1, 2, 3]]"


# --- timing ------------------------------------------------------------------


def test_comp_duration_is_inclusive_of_both_ends():
    assert jsx_writer.comp_duration(1, 24, 24.0) == pytest.approx(1.0)
    assert jsx_writer.comp_duration(1, 1, 24.0) == pytest.approx(1 / 24.0)


def test_frame_times_start_at_zero():
    assert jsx_writer.frame_times(101, 103, 25.0) == pytest.approx([0.0, 0.04, 0.08])


# --- generated script --------------------------------------------------------


@pytest.fixture
def script():
    return jsx_writer.write_jsx(COMP, CAMERA)


def test_bundled_runtime_is_es3(script):
    assert_es3(jsx_writer.load_runtime(), "pt_runtime.jsx")


def test_generated_script_is_es3(script):
    assert_es3(script, "generated .jsx")


def test_generated_script_is_structurally_balanced(script):
    assert_balanced(script, "generated .jsx")


def test_bundled_runtime_is_structurally_balanced():
    assert_balanced(jsx_writer.load_runtime(), "pt_runtime.jsx")


def test_script_declares_the_comp_settings(script):
    assert 'var PT_COMP_NAME = "hallway";' in script
    assert "var PT_WIDTH = 1080;" in script
    assert "var PT_HEIGHT = 1920;" in script
    assert "var PT_FRAME_RATE = 24;" in script


def test_script_duration_covers_every_frame(script):
    assert f"var PT_DURATION = {jsx_writer.format_number(3 / 24.0)};" in script


def test_script_includes_the_runtime(script):
    assert "function ptEnsureComp(" in script
    assert "function ptAddCamera(" in script


def test_script_wraps_work_in_an_undo_group(script):
    assert "app.beginUndoGroup(" in script
    assert "app.endUndoGroup(" in script


def test_camera_tracks_have_one_entry_per_frame(script):
    times = re.search(r"var PT_TIMES = \[(.*?)\];", script).group(1).split(",")
    positions = re.search(r"var PT_CAM_POSITION = \[(.*?)\];", script).group(1)
    assert len(times) == 3
    assert positions.count("[") == 3


def test_a_static_track_collapses_to_one_value():
    """A camera that never moves should not produce a keyframe per frame."""
    static = dict(CAMERA, position=[(1.0, 2.0, 3.0)] * 3, orientation=[(0.0, 0.0, 0.0)] * 3)
    out = jsx_writer.write_jsx(COMP, static)
    assert "var PT_CAM_POSITION = [[1, 2, 3]];" in out
    assert "var PT_CAM_ORIENTATION = [[0, 0, 0]];" in out
    # zoom still varies, so it keeps all three
    assert out.count("2666") >= 2


def test_mismatched_track_length_is_rejected():
    bad = dict(CAMERA, position=[(0.0, 0.0, 0.0), (1.0, 1.0, 1.0)])
    with pytest.raises(ValueError, match="position"):
        jsx_writer.write_jsx(COMP, bad)


def test_reversed_frame_range_is_rejected():
    with pytest.raises(ValueError, match="frame_end"):
        jsx_writer.write_jsx(dict(COMP, frame_start=10, frame_end=2), CAMERA)


def test_comp_name_is_escaped_not_interpolated():
    out = jsx_writer.write_jsx(dict(COMP, name='evil");alert("x'), CAMERA)
    assert 'alert("x' not in out.split("// ---- generated data ----")[1].split("\n")[1]
    assert '\\"' in out


def test_runtime_can_be_supplied_for_testing():
    out = jsx_writer.write_jsx(COMP, CAMERA, runtime_source="// stub runtime")
    assert "// stub runtime" in out
    assert "function ptEnsureComp(" not in out


# --- M4: passes and nulls ----------------------------------------------------

PASSES = [
    {
        "key": "beauty",
        "label": "Beauty",
        "path": "C:/out/hall/beauty/beauty_0001.exr",
        "guide": False,
    },
    {
        "key": "emission",
        "label": "Emission",
        "path": "C:/out/hall/emission/emission_0001.exr",
        "guide": True,
    },
    {
        "key": "crypto",
        "label": "Cryptomatte Object",
        "path": "C:/out/hall/crypto/crypto_0001.exr",
        "guide": True,
    },
]

NULLS = [
    {
        "name": "Empty",
        "position": [(1.0, 2.0, 3.0), (4.0, 5.0, 6.0), (7.0, 8.0, 9.0)],
        "orientation": [(0.0, 0.0, 0.0), (0.0, 0.0, 10.0), (0.0, 0.0, 20.0)],
    },
    {
        "name": "Track.001",
        "position": [(0.0, 0.0, 0.0)] * 3,
        "orientation": [(0.0, 0.0, 0.0)] * 3,
    },
]


@pytest.fixture
def full_script():
    return jsx_writer.write_jsx(COMP, CAMERA, passes=PASSES, nulls=NULLS)


def test_full_script_is_es3_and_balanced(full_script):
    assert_es3(full_script, "M4 .jsx")
    assert_balanced(full_script, "M4 .jsx")


def test_passes_are_emitted_bottom_of_stack_first(full_script):
    """Beauty must be added first so everything else stacks above it."""
    table = re.search(r"var PT_PASSES = \[(.*?)\];", full_script, re.S).group(1)
    assert table.index('"Beauty"') < table.index('"Emission"') < table.index('"Cryptomatte Object"')


def test_beauty_is_visible_and_the_rest_are_guides(full_script):
    table = re.search(r"var PT_PASSES = \[(.*?)\];", full_script, re.S).group(1)
    rows = re.findall(r"\[([^\]]*)\]", table)
    assert rows[0].endswith("false"), "beauty must not be a guide layer"
    assert all(row.endswith("true") for row in rows[1:]), "every other pass is a disabled guide"


def test_pass_paths_are_emitted_as_escaped_strings(full_script):
    assert '"C:/out/hall/beauty/beauty_0001.exr"' in full_script


def test_windows_paths_with_backslashes_are_escaped():
    windows = [dict(PASSES[0], path="C:" + chr(92) + "out" + chr(92) + "beauty_0001.exr")]
    out = jsx_writer.write_jsx(COMP, CAMERA, passes=windows)
    assert chr(92) * 2 in out
    assert_balanced(out, "windows path .jsx")


def test_null_names_and_tracks_are_emitted(full_script):
    assert 'var PT_NULL_NAMES = ["Empty", "Track.001"];' in full_script
    positions = re.search(r"var PT_NULL_POSITION = \[(.*?)\];", full_script, re.S).group(1)
    assert positions.count("[[") >= 1


def test_a_static_null_collapses_to_one_keyframe(full_script):
    """The second null never moves, so it should not get three identical keys."""
    positions = re.search(r"var PT_NULL_POSITION = \[(.*)\];", full_script, re.S).group(1)
    tracks = re.findall(r"\[\[.*?\]\]", positions)
    assert tracks[-1] == "[[0, 0, 0]]"


def test_camera_and_nulls_are_parented_to_the_world_null(full_script):
    """M4 acceptance: camera and nulls parented."""
    assert "var world = ptEnsureWorldNull(" in full_script
    assert "PT_CAM_ZOOM, world" in full_script
    assert "PT_NULL_ORIENTATION[i], world" in full_script


def test_the_world_null_is_built_as_an_identity_transform():
    """Parenting to it must not move anything: position has to equal anchor."""
    runtime = jsx_writer.load_runtime()
    body = runtime.split("function ptEnsureWorldNull")[1].split("function ")[0]
    assert '"Anchor Point").setValue([0, 0, 0])' in body
    assert '"Position").setValue([0, 0, 0])' in body


def test_footage_is_conformed_to_the_comp_frame_rate():
    """An imported sequence otherwise takes the frame rate from AE preferences."""
    assert "conformFrameRate" in jsx_writer.load_runtime()


def test_script_without_passes_or_nulls_is_still_valid():
    out = jsx_writer.write_jsx(COMP, CAMERA)
    assert "var PT_PASSES = [];" in out
    assert "var PT_NULL_NAMES = [];" in out
    assert_es3(out, "camera-only .jsx")
    assert_balanced(out, "camera-only .jsx")
