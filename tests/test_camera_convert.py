"""Unit tests for the Blender -> After Effects transform conversion.

Values here are hand-computed, as M2's acceptance criteria require. The
agreement with Blender's own maths is checked separately in
test_camera_integration.py.
"""

import math

import pytest
from passthrough import camera_convert as cc

IDENTITY = (
    (1.0, 0.0, 0.0, 0.0),
    (0.0, 1.0, 0.0, 0.0),
    (0.0, 0.0, 1.0, 0.0),
    (0.0, 0.0, 0.0, 1.0),
)


def matrix_from_3x3(rot, translation=(0.0, 0.0, 0.0)):
    return tuple(tuple(rot[r][c] for c in range(3)) + (translation[r],) for r in range(3)) + (
        (0.0, 0.0, 0.0, 1.0),
    )


ROT_X_90 = ((1, 0, 0), (0, 0, -1), (0, 1, 0))
ROT_Y_90 = ((0, 0, 1), (0, 1, 0), (-1, 0, 0))
ROT_Z_90 = ((0, -1, 0), (1, 0, 0), (0, 0, 1))


# --- translation, scale ------------------------------------------------------


def test_to_translation_reads_the_fourth_column():
    assert cc.to_translation(matrix_from_3x3(ROT_Z_90, (1.5, -2.0, 3.25))) == (1.5, -2.0, 3.25)


def test_to_scale_of_a_pure_rotation_is_unit():
    assert cc.to_scale(matrix_from_3x3(ROT_X_90)) == pytest.approx((1.0, 1.0, 1.0))


def test_to_scale_reads_column_lengths():
    scaled = ((2.0, 0, 0, 0), (0, 3.0, 0, 0), (0, 0, 4.0, 0), (0, 0, 0, 1.0))
    assert cc.to_scale(scaled) == pytest.approx((2.0, 3.0, 4.0))


# --- position ----------------------------------------------------------------


def test_position_mapping_is_the_section_7_2_formula():
    """ae_x = bx*s + W/2, ae_y = -bz*s + H/2, ae_z = by*s."""
    assert cc.convert_position((1.0, 2.0, 3.0), 1080, 1920, 100.0) == pytest.approx(
        (640.0, 660.0, 200.0)
    )


def test_origin_lands_at_the_comp_centre():
    assert cc.convert_position((0.0, 0.0, 0.0), 1080, 1920, 100.0) == pytest.approx(
        (540.0, 960.0, 0.0)
    )


def test_up_in_blender_is_up_on_screen():
    """Blender +Z is up; After Effects Y grows downwards, so it must decrease."""
    _, low, _ = cc.convert_position((0.0, 0.0, 0.0), 1080, 1920, 100.0)
    _, high, _ = cc.convert_position((0.0, 0.0, 1.0), 1080, 1920, 100.0)
    assert high < low


def test_pixels_per_unit_scales_position():
    assert cc.convert_position((1.0, 0.0, 0.0), 1000, 1000, 250.0)[0] == pytest.approx(750.0)


def test_pixel_aspect_divides_x_only():
    x, y, z = cc.convert_position((1.0, 1.0, 1.0), 1000, 1000, 100.0, aspect=2.0)
    assert x == pytest.approx(550.0)
    assert y == pytest.approx(400.0)
    assert z == pytest.approx(100.0)


# --- rotation ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("rot", "expected"),
    [
        (((1, 0, 0), (0, 1, 0), (0, 0, 1)), (0.0, 0.0, 0.0)),
        (ROT_X_90, (math.pi / 2, 0.0, 0.0)),
        (ROT_Y_90, (0.0, math.pi / 2, 0.0)),
        (ROT_Z_90, (0.0, 0.0, math.pi / 2)),
    ],
)
def test_euler_zyx_of_axis_rotations(rot, expected):
    assert cc.to_euler_zyx(matrix_from_3x3(rot)) == pytest.approx(expected, abs=1e-12)


def test_orientation_flips_y_and_z_signs():
    """AE's Y and Z run opposite to Blender's, so those two angles negate."""
    assert cc.convert_orientation((math.radians(10), math.radians(20), math.radians(30))) == (
        pytest.approx(10.0),
        pytest.approx(-20.0),
        pytest.approx(-30.0),
    )


def test_camera_correction_is_minus_90_not_180():
    """Section 7.2 says 180; Blender's own exporter subtracts 90 from X.

    An AE layer stands upright while a Blender object lies in the XY plane. The
    reference implementation is what this ports, and the projection test in
    test_camera_integration.py is what proves it.
    """
    assert cc.convert_orientation((0.0, 0.0, 0.0), x_rot_correction=True) == (
        pytest.approx(-90.0),
        pytest.approx(0.0),
        pytest.approx(0.0),
    )


def test_gimbal_lock_still_returns_a_usable_triple():
    rx, ry, rz = cc.to_euler_zyx(matrix_from_3x3(ROT_Y_90))
    assert ry == pytest.approx(math.pi / 2)
    assert rz == 0.0


# --- scale -------------------------------------------------------------------


def test_scale_remaps_axes_and_becomes_a_percentage():
    assert cc.convert_scale((1.0, 2.0, 3.0)) == pytest.approx((100.0, 300.0, 200.0))


# --- zoom --------------------------------------------------------------------


def test_zoom_is_lens_over_sensor_times_the_spanned_dimension():
    assert cc.zoom_from_lens(50.0, "HORIZONTAL", 36.0, 24.0, 1080, 1920) == pytest.approx(1500.0)


def test_auto_fit_spans_the_larger_dimension_on_a_portrait_render():
    """The bug in the reference implementation, and it matters at 1080x1920.

    Blender's AUTO applies sensor_width to whichever image dimension is larger.
    Treating AUTO as horizontal would give 1500 here instead of 2666.67 -- a 78%
    field-of-view error on the resolution this project targets.
    """
    assert cc.zoom_from_lens(50.0, "AUTO", 36.0, 24.0, 1080, 1920) == pytest.approx(
        50.0 * 1920 / 36.0
    )


def test_auto_fit_spans_width_on_a_landscape_render():
    assert cc.zoom_from_lens(50.0, "AUTO", 36.0, 24.0, 1920, 1080) == pytest.approx(
        50.0 * 1920 / 36.0
    )


def test_vertical_fit_uses_sensor_height():
    assert cc.zoom_from_lens(50.0, "VERTICAL", 36.0, 24.0, 1080, 1920) == pytest.approx(
        50.0 * 1920 / 24.0
    )


@pytest.mark.parametrize(
    ("fit", "res_x", "res_y", "expected"),
    [
        ("AUTO", 1920, 1080, (36.0, "HORIZONTAL")),
        ("AUTO", 1080, 1920, (36.0, "VERTICAL")),
        ("AUTO", 1000, 1000, (36.0, "HORIZONTAL")),
        ("HORIZONTAL", 1080, 1920, (36.0, "HORIZONTAL")),
        ("VERTICAL", 1920, 1080, (24.0, "VERTICAL")),
    ],
)
def test_effective_sensor(fit, res_x, res_y, expected):
    assert cc.effective_sensor(fit, 36.0, 24.0, res_x, res_y) == expected


# --- angle unwrapping --------------------------------------------------------


def test_unwrap_crosses_the_180_boundary_without_a_full_turn():
    assert cc.unwrap_degrees(179.0, -179.0) == pytest.approx(181.0)
    assert cc.unwrap_degrees(-179.0, 179.0) == pytest.approx(-181.0)


def test_unwrap_leaves_a_small_step_alone():
    assert cc.unwrap_degrees(10.0, 12.0) == pytest.approx(12.0)


def test_unwrap_track_keeps_an_orientation_continuous():
    track = [(0.0, 0.0, 178.0), (0.0, 0.0, -179.0), (0.0, 0.0, -176.0)]
    unwrapped = cc.unwrap_track(track)
    assert [round(o[2], 6) for o in unwrapped] == [178.0, 181.0, 184.0]


def test_unwrap_track_preserves_the_first_entry():
    track = [(1.0, 2.0, 3.0), (1.0, 2.0, 3.0)]
    assert cc.unwrap_track(track)[0] == (1.0, 2.0, 3.0)


def test_unwrap_track_of_empty_is_empty():
    assert cc.unwrap_track([]) == []


# --- whole transform ---------------------------------------------------------


def test_convert_transform_of_identity_camera():
    position, orientation, scale = cc.convert_transform(
        IDENTITY, 1080, 1920, 100.0, x_rot_correction=True
    )
    assert position == pytest.approx((540.0, 960.0, 0.0))
    assert orientation == pytest.approx((-90.0, 0.0, 0.0))
    assert scale == pytest.approx((100.0, 100.0, 100.0))
