"""Checks on blender_manifest.toml (SPEC.md sections 6 and 7.5).

`blender --command extension validate` is the real authority on manifest
correctness; these tests catch the mistakes that would otherwise only surface
at install time, and pin the values the spec fixes.
"""

import re
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
ADDON_DIR = REPO_ROOT / "blender_addon" / "passthrough"
MANIFEST_PATH = ADDON_DIR / "blender_manifest.toml"

REQUIRED_KEYS = (
    "schema_version",
    "id",
    "name",
    "tagline",
    "version",
    "type",
    "maintainer",
    "license",
    "blender_version_min",
)

VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


@pytest.fixture(scope="module")
def manifest():
    with MANIFEST_PATH.open("rb") as handle:
        return tomllib.load(handle)


def test_manifest_exists_next_to_the_package_init():
    assert MANIFEST_PATH.is_file()
    assert (ADDON_DIR / "__init__.py").is_file()


@pytest.mark.parametrize("key", REQUIRED_KEYS)
def test_required_key_is_present(manifest, key):
    assert key in manifest, f"blender_manifest.toml is missing {key!r}"


def test_id_matches_the_containing_folder(manifest):
    """The distributed zip must contain a folder named after the id (7.5)."""
    assert manifest["id"] == ADDON_DIR.name


def test_type_is_addon(manifest):
    assert manifest["type"] == "add-on"


@pytest.mark.parametrize("key", ["version", "blender_version_min"])
def test_versions_are_dotted_triples(manifest, key):
    assert VERSION_RE.match(manifest[key]), f"{key} must look like 1.2.3"


def test_blender_version_min_is_at_least_5_2(manifest):
    """The spec targets Blender 5.2 LTS (section 5)."""
    parts = tuple(int(p) for p in manifest["blender_version_min"].split("."))
    assert parts >= (5, 2, 0)


def test_licenses_are_spdx_identifiers(manifest):
    licenses = manifest["license"]
    assert isinstance(licenses, list) and licenses
    for entry in licenses:
        assert entry.startswith("SPDX:"), f"{entry!r} is not an SPDX identifier"


def test_tagline_fits_blenders_constraints(manifest):
    tagline = manifest["tagline"]
    assert len(tagline) <= 64
    assert tagline == tagline.strip()
    assert not tagline.endswith("."), "Blender rejects a tagline ending in a period"


def test_tags_are_the_ones_the_spec_pins(manifest):
    assert manifest["tags"] == ["Render", "Pipeline"]
