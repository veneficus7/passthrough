"""Unit tests for the template parameter schemas (pure, no Blender)."""

import json

import pytest
from passthrough import template_spec

SPEC_KEYS = ("corridor", "light_room", "camera_move", "text_in_space", "debris_field")


@pytest.fixture(scope="module")
def templates():
    return template_spec.load_templates()


# --- the shipped schemas -----------------------------------------------------


def test_the_five_templates_the_spec_names_are_present(templates):
    assert set(templates) == set(SPEC_KEYS)


@pytest.mark.parametrize("key", SPEC_KEYS)
def test_each_template_has_a_name_and_a_description(templates, key):
    template = templates[key]
    assert template.name
    assert template.description


@pytest.mark.parametrize("key", SPEC_KEYS)
def test_each_template_has_parameters_with_unique_keys(templates, key):
    keys = [parameter.key for parameter in templates[key].parameters]
    assert len(keys) >= 5
    assert len(keys) == len(set(keys))


@pytest.mark.parametrize("key", SPEC_KEYS)
def test_every_parameter_declares_a_known_kind(templates, key):
    for parameter in templates[key].parameters:
        assert parameter.kind in template_spec.KINDS


@pytest.mark.parametrize("key", SPEC_KEYS)
def test_every_template_can_set_a_frame_count(templates, key):
    """Every template drives its own shot length."""
    assert templates[key].parameter("frames").kind == "int"


@pytest.mark.parametrize("key", SPEC_KEYS)
def test_defaults_survive_validation_unchanged(templates, key):
    """A user who touches nothing must get exactly the documented scene."""
    template = templates[key]
    assert template.validate(template.defaults()) == template.validate({})


@pytest.mark.parametrize("key", SPEC_KEYS)
def test_numeric_defaults_are_inside_their_own_range(templates, key):
    for parameter in templates[key].parameters:
        if parameter.kind not in ("float", "int"):
            continue
        if parameter.minimum is not None:
            assert parameter.default >= parameter.minimum, parameter.key
        if parameter.maximum is not None:
            assert parameter.default <= parameter.maximum, parameter.key


def test_enum_defaults_are_one_of_their_items(templates):
    for template in templates.values():
        for parameter in template.parameters:
            if parameter.kind == "enum":
                assert parameter.default in [item[0] for item in parameter.items]


def test_enum_items_are_blender_shaped(templates):
    """Blender wants (identifier, name, description) triples."""
    for template in templates.values():
        for parameter in template.parameters:
            if parameter.kind == "enum":
                for item in parameter.items:
                    assert len(item) == 3


# --- validation --------------------------------------------------------------


def test_missing_parameters_fall_back_to_defaults(templates):
    template = templates["corridor"]
    assert template.validate({})["length"] == template.parameter("length").default


def test_unknown_parameters_are_dropped_not_rejected(templates):
    """A scene saved before a parameter was renamed should still build."""
    result = templates["corridor"].validate({"length": 12.0, "gone_away": 3})
    assert result["length"] == 12.0
    assert "gone_away" not in result


def test_values_are_clamped_to_their_range(templates):
    template = templates["corridor"]
    assert template.validate({"length": 1e9})["length"] == template.parameter("length").maximum
    assert template.validate({"length": -50})["length"] == template.parameter("length").minimum


def test_numeric_strings_are_coerced(templates):
    assert templates["corridor"].validate({"frames": "48"})["frames"] == 48


def test_integers_round_rather_than_truncate(templates):
    assert templates["corridor"].validate({"frames": 47.6})["frames"] == 48


def test_colours_are_clamped_to_zero_one(templates):
    colour = templates["corridor"].validate({"light_color": (2.0, -1.0, 0.5)})["light_color"]
    assert colour == (1.0, 0.0, 0.5)


def test_a_bad_colour_is_rejected(templates):
    with pytest.raises(template_spec.TemplateError):
        templates["corridor"].validate({"light_color": (1.0, 0.0)})


def test_a_bad_enum_value_is_rejected(templates):
    with pytest.raises(template_spec.TemplateError):
        templates["camera_move"].validate({"move": "SPIRAL"})


def test_every_enum_value_is_accepted(templates):
    parameter = templates["camera_move"].parameter("move")
    for identifier, _name, _description in parameter.items:
        assert templates["camera_move"].validate({"move": identifier})["move"] == identifier


# --- schema loading ----------------------------------------------------------


def test_an_unknown_kind_is_rejected():
    with pytest.raises(template_spec.TemplateError):
        template_spec.template_from_json(
            {
                "key": "k",
                "name": "n",
                "parameters": [{"key": "p", "kind": "quaternion", "default": 0}],
            }
        )


def test_an_enum_without_items_is_rejected():
    with pytest.raises(template_spec.TemplateError):
        template_spec.template_from_json(
            {"key": "k", "name": "n", "parameters": [{"key": "p", "kind": "enum", "default": "A"}]}
        )


def test_a_schema_without_a_key_is_rejected():
    with pytest.raises(template_spec.TemplateError):
        template_spec.template_from_json({"name": "n"})


def test_load_templates_complains_about_an_empty_directory(tmp_path):
    with pytest.raises(template_spec.TemplateError):
        template_spec.load_templates(str(tmp_path))


def test_schemas_on_disk_are_valid_json():
    directory = template_spec.template_directory()
    import os

    for name in os.listdir(directory):
        if name.endswith(".json"):
            with open(os.path.join(directory, name), encoding="utf-8") as handle:
                json.load(handle)


def test_enum_items_for_blender_are_triples(templates):
    items = template_spec.enum_items(templates)
    assert len(items) == 5
    assert all(len(item) == 3 for item in items)
