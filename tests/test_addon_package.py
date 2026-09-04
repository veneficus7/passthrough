"""The add-on package must stay importable without Blender (SPEC.md section 6).

This is the structural rule the whole test strategy rests on: if importing
``passthrough`` pulls in ``bpy``, then none of the pure-Python modules added in
later milestones can be unit tested outside Blender.
"""

import importlib
import sys


def test_importing_the_package_does_not_pull_in_bpy():
    assert "bpy" not in sys.modules, "bpy leaked into the test session before import"
    importlib.import_module("passthrough")
    assert "bpy" not in sys.modules, "passthrough/__init__.py imported bpy at module scope"


def test_bpy_touching_submodules_are_not_imported_at_package_scope():
    package = importlib.import_module("passthrough")
    for name in ("ui", "passes"):
        assert f"passthrough.{name}" not in sys.modules
        assert not hasattr(package, name)


def test_pure_modules_import_without_bpy():
    """The section 6 payoff: these are testable in plain pytest."""
    for name in ("pass_spec",):
        importlib.import_module(f"passthrough.{name}")
    assert "bpy" not in sys.modules


def test_register_and_unregister_are_exposed():
    package = importlib.import_module("passthrough")
    assert callable(package.register)
    assert callable(package.unregister)
