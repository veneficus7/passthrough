# Passthrough

A Blender → After Effects pass pipeline built for machines that don't have
enough RAM. Blender renders separated passes headlessly and exits; After
Effects then rebuilds the shot from a generated `.jsx`. The two applications
never hold memory at the same time.

Full design and rationale: [SPEC.md](SPEC.md).

## Status

**M1 — Pass setup and File Output wiring.** One button configures the EEVEE
passes and builds a compositor tree that writes one EXR sequence per pass, in
the layout SPEC.md §7.3 specifies:

```
<output_root>/<shot_name>/
├── beauty/     beauty_0001.exr ...
├── emission/   emission_0001.exr ...
├── mist/       mist_0001.exr ...
├── normal/     normal_0001.exr ...
└── crypto/     crypto_0001.exr ...
```

Camera conversion, `.jsx` generation and headless rendering (M2–M7) are not
built yet. Milestones are listed in SPEC.md §8.

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
- **§5 target version.** `blender_version_min` is `5.2.0` per the spec. On an
  older Blender the zip still *installs* — files are copied and the extension
  shows up in the add-on list — but it will not **enable**. The console reports
  `This Blender version (5.1.2) doesn't meet the minimum supported version
  (5.2.0)`, nothing registers, and no panel appears. The failure looks like a
  broken add-on rather than a version gate, so check the console first. The
  development machine currently has Blender 5.1.2.

## Blender 5.x compositor notes

The compositor changed enough in Blender 5 that most tutorials and older add-on
code are wrong. All of the following was established by introspecting Blender
5.1.2 and by reading the bytes of the EXRs it wrote, not from documentation.

- The scene's tree is `scene.compositing_node_group`, a node group datablock.
  `scene.node_tree` no longer exists, and `scene.use_nodes` is deprecated for
  removal in 6.0.
- `CompositorNodeComposite` has been removed.
- **One File Output node writes exactly one file.** Its `file_output_items`
  become layers *inside* that file, and the node-level format enum accepts only
  `OPEN_EXR_MULTILAYER`. So one sequence per pass means one node per pass.
- `base_path` and `file_slots` are now `directory` and `file_output_items`.
- **`color_depth` and `exr_codec` are read from the node format, never from an
  item's** — even when the item overrides the file format. Setting them on the
  item is accepted, reported back correctly, and silently ignored at write
  time, producing 32-bit uncompressed files.
- **A named File Output item becomes an EXR layer prefix.** An item called
  `beauty` writes channels `beauty.R`, `beauty.G` and so on. After Effects
  reads the unprefixed names, so the item must be left unnamed to get plain
  `R`/`G`/`B`/`A`.
- The cryptomatte pass writes *lowercase* `r`/`g`/`b`/`a` channels while every
  other pass writes uppercase. It is also kept at 32-bit, because half float
  would round away the object-id hashes.

## License

GPL-3.0-or-later.
