"""Unit tests for the pure pass manifest (SPEC.md sections 6 and 7.3)."""

import pytest
from passthrough import pass_spec


def test_pass_set_and_order_match_the_spec():
    """Section 7.3 lists beauty, emission, mist, normal, crypto, in that order."""
    assert pass_spec.PASS_KEYS == ("beauty", "emission", "mist", "normal", "crypto")


def test_deferred_passes_are_absent():
    """Ambient Occlusion and Vector are explicitly deferred by M1."""
    assert "ao" not in pass_spec.PASS_KEYS
    assert "vector" not in pass_spec.PASS_KEYS


def test_every_pass_has_a_distinct_socket_and_flag():
    sockets = [spec.socket for spec in pass_spec.PASSES]
    flags = [spec.view_layer_flag for spec in pass_spec.PASSES]
    assert len(set(sockets)) == len(sockets)
    assert len(set(flags)) == len(flags)


def test_socket_names_are_the_ones_blender_reports():
    """Verified against Blender 5.1.2's Render Layers node outputs."""
    by_key = {spec.key: spec.socket for spec in pass_spec.PASSES}
    assert by_key["beauty"] == "Image"
    assert by_key["emission"] == "Emission"  # the flag is use_pass_emit, the socket is not
    assert by_key["crypto"] == "CryptoObject00"


def test_cryptomatte_depth_yields_exactly_one_socket():
    """Depth 2 is one RGBA layer, which is what makes one flat crypto EXR honest."""
    assert pass_spec.CRYPTOMATTE_DEPTH == 2


def test_get_pass_round_trips():
    assert pass_spec.get_pass("mist").socket == "Mist"
    with pytest.raises(KeyError):
        pass_spec.get_pass("nope")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("hallway", "hallway"),
        ("  hallway  ", "hallway"),
        ("", "shot"),
        ("   ", "shot"),
        (None, "shot"),
        ("a/b", "a_b"),
        ("a" + chr(92) + "b", "a_b"),
        ('bad:name?"', "bad_name__"),
        ("trailing.", "trailing"),
    ],
)
def test_sanitize_shot_name(raw, expected):
    assert pass_spec.sanitize_shot_name(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("C:/renders", "C:/renders"),
        ("C:" + chr(92) + "renders", "C:/renders"),
        ("C:/renders/", "C:/renders"),
        ("//renders", "//renders"),
    ],
)
def test_normalize_root(raw, expected):
    assert pass_spec.normalize_root(raw) == expected


def test_directory_layout_matches_section_7_3():
    root, shot = "C:/renders", "hallway"
    assert pass_spec.shot_dir(root, shot) == "C:/renders/hallway"
    assert pass_spec.pass_dir(root, shot, "beauty") == "C:/renders/hallway/beauty"


def test_frame_pattern_uses_blenders_hash_token():
    assert pass_spec.frame_pattern("beauty") == "beauty_####"


@pytest.mark.parametrize(
    ("frame", "expected"),
    [
        (1, "beauty_0001.exr"),
        (12, "beauty_0012.exr"),
        (1234, "beauty_1234.exr"),
        (12345, "beauty_12345.exr"),
    ],
)
def test_frame_filename_pads_to_four_digits(frame, expected):
    assert pass_spec.frame_filename("beauty", frame) == expected


def test_frame_path_is_the_full_section_7_3_path():
    assert (
        pass_spec.frame_path("C:/renders", "hallway", "mist", 1)
        == "C:/renders/hallway/mist/mist_0001.exr"
    )


def test_expected_files_covers_every_pass_and_frame_inclusively():
    files = pass_spec.expected_files("C:/renders", "hallway", 1, 3)
    assert set(files) == set(pass_spec.PASS_KEYS)
    assert files["beauty"] == [
        "C:/renders/hallway/beauty/beauty_0001.exr",
        "C:/renders/hallway/beauty/beauty_0002.exr",
        "C:/renders/hallway/beauty/beauty_0003.exr",
    ]


def test_expected_files_sanitizes_the_shot_name():
    files = pass_spec.expected_files("C:/renders", "bad/name", 1, 1)
    assert files["beauty"] == ["C:/renders/bad_name/beauty/beauty_0001.exr"]


def test_cryptomatte_stays_full_float():
    """Half float would round away the object-id hashes cryptomatte encodes."""
    assert pass_spec.get_pass("crypto").color_depth == "32"


def test_other_passes_are_half_float():
    """Half is the memory/disk win; the project exists for that reason."""
    for spec in pass_spec.PASSES:
        if spec.key != "crypto":
            assert spec.color_depth == "16"


def test_output_items_must_be_unnamed():
    """A named File Output item becomes an EXR layer prefix AE cannot read."""
    assert pass_spec.OUTPUT_ITEM_NAME == ""


def test_codec_is_lossless():
    assert pass_spec.EXR_CODEC == "ZIP"
