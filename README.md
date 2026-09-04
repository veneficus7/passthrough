# Passthrough

A Blender → After Effects pass pipeline built for machines that don't have
enough RAM. Blender renders separated passes headlessly and exits; After
Effects then rebuilds the shot from a generated `.jsx`. The two applications
never hold memory at the same time.

Full design and rationale: [SPEC.md](SPEC.md).

## Status

**M0 — Skeleton.** The extension registers and shows a panel. It does not
render anything yet. Milestones M1–M7 are listed in SPEC.md §8.

## Layout

```
blender_addon/passthrough/   the extension (zip root must match the manifest id)
tests/                       pytest suite, runs without Blender
```

## Running the tests

Requires system Python 3.11+ (separate from Blender's bundled interpreter).

```
python -m venv .venv
.venv\Scripts\python -m pip install pytest ruff
.venv\Scripts\python -m pytest
```

## Installing the add-on

Blender 5.2+ is required (see the note in SPEC.md §5).

Build a zip with `blender --command extension build --source-dir
blender_addon/passthrough`, then install it from
*Edit ▸ Preferences ▸ Add-ons ▸ Install from Disk*. The "Passthrough" panel
appears in Render Properties.

For development, point Blender at the source instead: add `blender_addon` as a
local extension repository in *Preferences ▸ Get Extensions ▸ Repositories*.

## Notes on the spec

Two things verified against a real Blender install that differ from SPEC.md:

- **§7.5 zip layout.** The spec says the distributed zip must contain a folder
  named after the `id`. That is the rule for legacy `bl_info` add-ons. Blender's
  own `--command extension build` emits a *flat* zip with
  `blender_manifest.toml` at the archive root, and creates the `passthrough/`
  directory at install time from the manifest `id`. Verified on 5.1.2: installs,
  enables, and registers. Do not hand-repack the zip into a folder.
- **§5 target version.** `blender_version_min` is `5.2.0` per the spec, so the
  extension will refuse to install on anything older. The development machine
  currently has Blender 5.1.2.

## License

GPL-3.0-or-later.
