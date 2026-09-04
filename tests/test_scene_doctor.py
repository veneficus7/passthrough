"""Unit tests for the memory estimator and the auto-fix planner.

The coefficients themselves were fitted against seventeen real renders; that
agreement is checked in test_doctor_integration.py. These tests cover the
arithmetic and the shape of the fix ladder.
"""

import pytest
from passthrough import scene_doctor as doctor

MB = 1024**2
GB = 1024**3


def scene(objects=(), textures=(), resolution=(1080, 1920), percentage=100):
    return {
        "resolution_x": resolution[0],
        "resolution_y": resolution[1],
        "resolution_percentage": percentage,
        "objects": list(objects),
        "textures": list(textures),
    }


def texture(name, size, channels=4, depth=8):
    return {"name": name, "width": size, "height": size, "channels": channels, "depth": depth}


# --- the arithmetic ----------------------------------------------------------


def test_image_bytes_of_an_8_bit_rgba_texture():
    assert doctor.image_bytes(4096, 4096) == 4096 * 4096 * 4


def test_image_bytes_of_a_float_texture():
    assert doctor.image_bytes(1024, 1024, channels=4, depth=32) == 1024 * 1024 * 16


def test_render_pixels_applies_the_resolution_percentage():
    assert doctor.render_pixels(1080, 1920, 100) == 1080 * 1920
    assert doctor.render_pixels(1080, 1920, 50) == 540 * 960


def test_an_empty_scene_costs_the_baseline_plus_its_pixels():
    estimate = doctor.estimate(scene())
    assert estimate.base == doctor.BASE_BYTES
    assert estimate.geometry == 0
    assert estimate.textures == 0
    assert estimate.pixels == int(doctor.BYTES_PER_PIXEL * 1080 * 1920)


def test_the_breakdown_sums_to_the_total():
    estimate = doctor.estimate(
        scene(objects=[{"name": "a", "triangles": 1_000_000}], textures=[texture("t", 2048)])
    )
    assert sum(estimate.breakdown().values()) == estimate.total


def test_geometry_scales_with_triangles():
    light = doctor.estimate(scene(objects=[{"name": "a", "triangles": 100_000}]))
    heavy = doctor.estimate(scene(objects=[{"name": "a", "triangles": 200_000}]))
    assert heavy.geometry == pytest.approx(light.geometry * 2, rel=1e-6)


def test_capping_textures_shrinks_them_proportionally():
    assert doctor.total_texture_bytes([texture("t", 4096)], limit=1024) == 1024 * 1024 * 4


def test_capping_leaves_small_textures_alone():
    assert doctor.total_texture_bytes([texture("t", 512)], limit=1024) == 512 * 512 * 4


def test_capping_a_non_square_texture_keeps_its_aspect():
    wide = [{"name": "w", "width": 4096, "height": 2048, "channels": 4, "depth": 8}]
    assert doctor.total_texture_bytes(wide, limit=1024) == 1024 * 512 * 4


# --- diagnosis ---------------------------------------------------------------


def test_a_small_scene_fits_and_gets_no_fixes():
    report = doctor.diagnose(scene(), budget=6 * GB)
    assert report.fits
    assert report.fixes == ()


def test_a_heavy_scene_does_not_fit():
    heavy = scene(
        objects=[{"name": "grid", "triangles": 40_000_000}],
        textures=[texture(f"t{i}", 4096) for i in range(8)],
        resolution=(2160, 3840),
    )
    report = doctor.diagnose(heavy, budget=2 * GB)
    assert not report.fits
    assert report.fixes


def test_fixes_are_offered_in_the_order_the_spec_lists():
    """Textures, then geometry, then render resolution (SPEC.md M5)."""
    heavy = scene(
        objects=[{"name": "grid", "triangles": 40_000_000}],
        textures=[texture(f"t{i}", 4096) for i in range(8)],
        resolution=(2160, 3840),
    )
    kinds = [fix.kind for fix in doctor.diagnose(heavy, budget=1 * GB).fixes]
    assert kinds == sorted(kinds, key=["texture_scale", "decimate", "resolution"].index)


def test_only_one_fix_of_each_kind_is_returned():
    heavy = scene(
        objects=[{"name": "grid", "triangles": 40_000_000}],
        textures=[texture(f"t{i}", 4096) for i in range(8)],
        resolution=(2160, 3840),
    )
    kinds = [fix.kind for fix in doctor.diagnose(heavy, budget=1 * GB).fixes]
    assert len(kinds) == len(set(kinds))


def test_the_ladder_stops_as_soon_as_it_fits():
    """A scene that only slightly overshoots should not be gutted."""
    slightly_over = scene(textures=[texture("t", 4096) for _ in range(4)])
    budget = doctor.estimate(slightly_over).total - 50 * MB
    report = doctor.diagnose(slightly_over, budget=budget)
    assert [fix.kind for fix in report.fixes] == ["texture_scale"]
    assert report.fixable


def test_fixes_actually_bring_the_projection_under_budget():
    heavy = scene(
        objects=[{"name": "grid", "triangles": 8_000_000}],
        textures=[texture(f"t{i}", 4096) for i in range(4)],
        resolution=(2160, 3840),
    )
    report = doctor.diagnose(heavy, budget=2 * GB)
    assert report.fixable
    assert report.projected_after_fixes <= report.budget


def test_a_scene_that_cannot_be_saved_says_so():
    """Base cost alone can exceed a silly budget; the report must admit it."""
    report = doctor.diagnose(scene(), budget=100 * MB)
    assert not report.fits
    assert not report.fixable


def test_small_objects_are_not_decimated():
    """Decimating a 2k-triangle prop buys nothing and damages it for free."""
    many_small = scene(
        objects=[{"name": f"o{i}", "triangles": 2_000} for i in range(50)],
        textures=[texture("t", 4096) for _ in range(4)],
        resolution=(2160, 3840),
    )
    kinds = [fix.kind for fix in doctor.diagnose(many_small, budget=1 * GB).fixes]
    assert "decimate" not in kinds


def test_decimate_names_the_objects_it_would_touch():
    heavy = scene(
        objects=[{"name": "big", "triangles": 8_000_000}, {"name": "small", "triangles": 10}],
        resolution=(2160, 3840),
    )
    fixes = {fix.kind: fix for fix in doctor.diagnose(heavy, budget=1 * GB).fixes}
    assert fixes["decimate"].detail["objects"] == ["big"]


def test_texture_fix_names_only_the_oversized_images():
    heavy = scene(
        textures=[texture("big", 4096), texture("small", 256)],
        resolution=(2160, 3840),
    )
    budget = doctor.estimate(heavy).total - 300 * MB
    fixes = {fix.kind: fix for fix in doctor.diagnose(heavy, budget=budget).fixes}
    assert fixes["texture_scale"].detail["images"] == ["big"]


# --- reporting ---------------------------------------------------------------


def test_summary_reports_the_breakdown_and_the_verdict():
    lines = doctor.summarise(doctor.diagnose(scene(), budget=6 * GB))
    assert any("Projected peak" in line for line in lines)
    assert any("Fits the budget" in line for line in lines)


def test_summary_lists_the_fixes_when_over_budget():
    heavy = scene(
        objects=[{"name": "grid", "triangles": 8_000_000}],
        textures=[texture("t", 4096)],
        resolution=(2160, 3840),
    )
    lines = doctor.summarise(doctor.diagnose(heavy, budget=1 * GB))
    assert any("Over budget" in line for line in lines)
    assert any("Decimate" in line for line in lines)


@pytest.mark.parametrize(
    ("count", "expected"), [(0, "0 B"), (1536, "1.50 KB"), (6 * GB, "6.00 GB")]
)
def test_format_bytes(count, expected):
    assert doctor.format_bytes(count) == expected


def test_the_default_budget_is_the_one_m3_sets():
    assert doctor.DEFAULT_BUDGET_BYTES == 6 * GB
