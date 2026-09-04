"""Passthrough — a Blender to After Effects render-pass pipeline.

Registration only.

SPEC.md section 6 requires that this package stay importable *without* ``bpy``,
so that the pure-Python modules living beside this file can be unit tested in
ordinary pytest. Importing ``passthrough.camera_convert`` imports this module
first, so any submodule that touches ``bpy`` is imported inside
:func:`register` rather than at module scope.
"""

from importlib import import_module

#: Submodules exposing ``register()`` / ``unregister()``, in registration order.
_SUBMODULE_NAMES = ("prefs", "passes", "scene_capture", "ui")

_registered = []


def register():
    for name in _SUBMODULE_NAMES:
        module = import_module(f".{name}", __package__)
        module.register()
        _registered.append(module)


def unregister():
    while _registered:
        _registered.pop().unregister()
