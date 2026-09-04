# Passthrough

A Blender → After Effects pass pipeline built for machines that don't have
enough RAM. Blender renders separated passes headlessly and exits; After
Effects then rebuilds the shot from a generated `.jsx`. The two applications
never hold memory at the same time.

Full design and rationale: [SPEC.md](SPEC.md).

## Status

**M4 — Full After Effects import.** Configure the EEVEE passes, render the
frame range in a *separate* background Blender — optionally quitting the UI as
it launches, which is the whole point of the project — then run one script in
After Effects to get the whole shot back. Passes land in the layout SPEC.md
§7.3 specifies:

```
<output_root>/<shot_name>/
├── beauty/     beauty_0001.exr ...
├── emission/   emission_0001.exr ...
├── mist/       mist_0001.exr ...
├── normal/     normal_0001.exr ...
└── crypto/     crypto_0001.exr ...
```

The `.jsx` is written to `<output_root>/<shot_name>/<shot_name>.jsx`. Running it
builds a comp matching the Blender scene, imports every pass as its own
sequence, stacks them with beauty visible at the bottom and the rest as disabled
guide layers, and adds the camera plus a null for every Blender empty.

The headless render peaks at **484 MB** on the fixture scene, against the 6 GB
budget M3 sets. Progress and cancellation are driven from `render.log` in the
shot folder, which outlives the Blender UI. Remaining milestones are in
SPEC.md §8.

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
- **§6 runtime location.** The layout puts `pt_runtime.jsx` in `ae_scripts/`
  at the repo root. Nothing outside `blender_addon/passthrough/` ends up in the
  built zip, so the runtime would not ship. It lives at
  `blender_addon/passthrough/ae_runtime/pt_runtime.jsx` instead, and a test
  asserts the built zip contains it.
- **§5 target version.** `blender_version_min` is `5.2.0` per the spec. On an
  older Blender the zip still *installs* — files are copied and the extension
  shows up in the add-on list — but it will not **enable**. The console reports
  `This Blender version (5.1.2) doesn't meet the minimum supported version
  (5.2.0)`, nothing registers, and no panel appears. The failure looks like a
  broken add-on rather than a version gate, so check the console first. The
  development machine currently has Blender 5.1.2.

## Camera conversion notes

SPEC.md §7.2 says to port Blender's `io_export_after_effects` rather than derive
the maths. That add-on is **no longer bundled** with Blender (it moved to
extensions.blender.org), so the reference was read from a source mirror. Porting
it surfaced three things:

- **The camera correction is −90° on X, not 180°.** §7.2 describes a "180 degree
  reconciliation". The reference subtracts 90 from X, because an AE layer stands
  upright while a Blender object lies in the XY plane.
- **After Effects composes orientation as `Rx @ Ry @ Rz`.** Determined
  empirically by projecting known points: of the six possible orders, only this
  one reproduces Blender's projection, and it does so to ~1e-4 px. The others
  are wrong by 519–1626 px.
- **`sensor_fit='AUTO'` must fit the larger image dimension.** The reference
  treats AUTO as horizontal. At this project's 1080×1920 target the sensor spans
  the *height*, so zoom is `50 × 1920 / 36 = 2666.67`, not `1500`. Following the
  reference would have given a 78% field-of-view error on every portrait shot.

Two further things this implementation adds:

- **Orientation tracks are unwrapped.** `atan2` wraps at ±180°, and After
  Effects interpolates that literally — a camera would spin 358° between two
  frames. Tracks are shifted by whole turns to stay continuous.
- **`mathutils` is never imported.** `camera_convert.py` does its own matrix and
  Euler arithmetic on plain tuples, because §6 requires it to be testable
  without Blender. The port is checked element-wise against
  `mathutils.Matrix.to_euler('ZYX')` in the integration tests.

## After Effects import notes

- **Everything is parented to one identity null, `PT World`.** The camera and
  the nulls all carry *world-space* baked transforms, so mirroring Blender's
  object hierarchy with AE parenting would apply each parent's transform twice.
  A single null whose transform is the identity gives you one handle on the
  whole 3D scene without disturbing anything. It is only the identity when
  `position` equals `anchorPoint`, and `addNull()` sets neither to zero — both
  are zeroed explicitly, and the camera's alignment depends on it.
- **Nulls are created from Blender empties, and only empties.** One predictable
  rule beats an option nobody asked for; to get a null on a mesh, parent an
  empty to it.
- **Imported sequences are conformed to the comp frame rate.** An image sequence
  otherwise takes its rate from the user's AE import preferences, so a 24 fps
  comp can silently end up holding 30 fps footage and every pass drifts out of
  sync with the camera.
- **Alpha is interpreted as premultiplied over black**, which is what Blender
  writes. The generated script exposes this as `PT_ALPHA_PREMULTIPLIED` so it is
  a one-word edit if a pass shows dark fringing.
- **Lights are deliberately not exported.** AE lights only affect 3D layers that
  accept them, and every pass here is a flat 2D footage layer, so they would be
  inert — and mapping Blender's watts onto AE's intensity percentage is a guess.
  §1 lists them; M4's acceptance criteria do not.

## Headless render notes

- **Blender 5.1 does not emit the progress lines §7.6 describes.** There is no
  `Fra:12 Mem:412.35M` anywhere in a background render's output — that is
  older-Blender/Cycles formatting. What Blender 5.1 prints is
  `00:02.125  render  | Saved: '<path>'`, one line per written image. So
  `render_job.py` emits its own `PT_FRAME n/total` markers, and `queue.py`
  parses all three forms.
- **Frames are rendered one at a time with `write_still=False`,** not as an
  animation. Blender still substitutes the `####` token in the File Output
  nodes, but writes no main render output — so the shot folder contains exactly
  the §7.3 tree and nothing else.
- **The child's output goes to a log file, not a pipe.** A pipe has to be
  drained by a reader thread or it fills and stalls the render, and it dies with
  the parent. A log file is non-blocking to poll and survives Blender closing,
  which is what M3 is for.
- **`view_transform` reports only `NONE` in its enum in background mode** while
  still accepting real values, so `render_job.py` assigns `Raw` rather than
  validating against the enum first.
- Peak memory is measured through `GetProcessMemoryInfo` via ctypes, so the
  §9 memory regression check needs no third-party dependency.

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
