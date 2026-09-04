# Manual checks

SPEC.md §9 asks for a short written checklist for the half of testing that
cannot be automated. Run the relevant section once per milestone.

Everything here assumes the repo root as the working directory.

---

## 0. Automated checks (run these first)

```bash
.venv/Scripts/python -m pytest
```

Expect **187 passed** (147 unit, 40 integration). The integration tests launch
a real Blender; if Blender is not found they are skipped rather than failed, and
you would see `147 passed, 40 skipped` instead — which means the integration
half did **not** run.

To prove the integration tests really executed:

```bash
.venv/Scripts/python -m pytest -m integration -v
```

Lint and formatting:

```bash
.venv/Scripts/python -m ruff check . && .venv/Scripts/python -m ruff format --check .
```

---

## 1. Blender version gate (read before installing)

`blender_manifest.toml` sets `blender_version_min = "5.2.0"`.

On an older Blender the zip **installs but will not enable**. The extension
appears in the add-on list with its checkbox refusing to stay ticked, no panel
appears, and the console says:

```
ERROR passthrough: This Blender version (5.1.2) doesn't meet the minimum supported version (5.2.0)
```

This looks like a broken add-on and is not one. Either install Blender 5.2, or
build the relaxed dev zip below for GUI testing.

### Build the zips

```bash
blender --command extension build --source-dir blender_addon/passthrough --output-dir dist
```

For a dev zip that installs on Blender 5.1, copy the add-on to a scratch folder,
change `blender_version_min` to `5.1.0`, and build that copy instead.

---

## 2. M0 — the extension registers

1. *Edit ▸ Preferences ▸ Add-ons ▸ Install from Disk*, choose the zip.
2. The checkbox next to **Passthrough** stays ticked.
3. Open the *Render Properties* tab (the camera-back icon).
4. A **Passthrough** panel is present.

If the panel is missing, open *Window ▸ Toggle System Console* and read the
error — it is almost always the version gate above.

---

## 3. M1 — pass setup and File Output wiring

In Render Properties ▸ Passthrough:

1. Set **Output Root** to a folder you can find, and **Shot Name** to `test`.
2. Expand the **Passes** sub-panel. It lists all five passes and the resolved
   output folder.
3. Press **Set Up Passes**. The header reports how many passes were wired.
4. Switch to the *Compositing* workspace. The node group Passthrough created is
   assigned to the scene, so it should already be displayed — do **not** look
   for a "Use Nodes" checkbox, as Blender 5 replaced that mechanism and the
   add-on deliberately never touches the deprecated property. You should see:
   - one **Render Layers** node labelled *Passthrough Render Layers*
   - five **File Output** nodes, labelled *Passthrough Beauty*, *Emission*,
     *Mist*, *Normal*, *Cryptomatte Object*
   - exactly five links, one per pass
5. **Press Set Up Passes again.** The node count must not change. This is the
   idempotency requirement; a second set of nodes appearing is a failure.
6. Check View Layer Properties ▸ Passes: Combined, Mist, Normal, Emission and
   Cryptomatte Object are all ticked, and Cryptomatte **Levels is 2**.
7. Render one frame (F12).
8. On disk you should find exactly:

```
<output_root>/test/
├── beauty/     beauty_0001.exr
├── emission/   emission_0001.exr
├── mist/       mist_0001.exr
├── normal/     normal_0001.exr
└── crypto/     crypto_0001.exr
```

Blender also writes its normal render output to whatever `Output Properties ▸
Output Path` points at. That is expected at M1 — `render_job.py` takes ownership
of it in M3.

---

## 4. M1 — the After Effects half

There is no `.jsx` yet (that is M2/M4), so this is only a check that the EXRs
Blender wrote are readable. It is worth doing now, because the failure mode it
catches — a layer that imports as empty — looks identical to a failed render.

1. New project. *File ▸ Project Settings ▸ Color*: set **Depth** to
   *32 bits per channel*, working space linear.
2. *File ▸ Import ▸ File*, select `beauty/beauty_0001.exr`, tick
   **OpenEXR Sequence**, import.
3. The footage interprets as **1080 × 1920**, and the frame is **not black**.
   This is the check that matters: if Blender had written layer-prefixed
   channels, AE would show an empty layer here.
4. Repeat for the other passes. Expected appearance:
   - `emission` — mostly black with one bright orange blob
   - `mist` — a near-white depth gradient
   - `normal` — the usual pastel normal colours on objects, black background
   - `crypto` — **expected to look wrong or black.** AE has no native
     cryptomatte support, and Blender writes this pass with lowercase
     `r/g/b/a` channel names while AE looks for uppercase. M4 imports it as a
     disabled guide layer.
5. Set the beauty layer's blend mode or check the Info panel to confirm values
   above 1.0 survive — the passes are linear HDR, not view-transformed.

If beauty imports black, check the EXR channel names before suspecting the
render:

```bash
.venv/Scripts/python -c "import sys; sys.path.insert(0,'tests'); import exr_header; print(exr_header.read_header(r'<path>'))"
```

Channels must be `A B G R` with no dotted prefix, `HALF`, and `ZIP`
compression. Cryptomatte is the exception: lowercase and `FLOAT`.

---

## 5. M2 — camera conversion and the .jsx

### In Blender

1. Set up a camera with some animation, then press **Export After Effects
   Script** in the Passthrough panel.
2. The header reports the path. The file lands at
   `<output_root>/<shot_name>/<shot_name>.jsx`, beside the pass folders.

### In After Effects

1. *File ▸ Scripts ▸ Run Script File…*, choose the `.jsx`.
2. It should run with **no error dialog**, and open a new comp.
3. Check the comp settings against Blender:
   - width × height match the render resolution
   - frame rate matches
   - duration is `(frame_end - frame_start + 1) / fps` seconds
4. There is one camera layer, **Blender Camera**, with Position, Orientation
   and Zoom keyframes.
5. Scrub the timeline. The camera should sweep smoothly. **A sudden 358° spin
   between two frames means orientation unwrapping has regressed.**
6. Run the same script a second time. It must reuse the comp and replace the
   camera rather than creating `orbit 2`.

### The alignment check (SPEC.md §7.2's visual half)

This is the one that catches everything, and only needs doing once.

1. Import `beauty/beauty_0001.exr` into the comp and note where a recognisable
   feature sits — a corner of the cube, say.
2. Add a 3D null. Set its position to the After Effects position of that same
   Blender world point: `x = bx*100 + width/2`, `y = -bz*100 + height/2`,
   `z = by*100`.
3. Looking through **Blender Camera**, the null must sit on top of that feature.

The numeric half of this is automated in
`tests/test_camera_integration.py::test_ae_camera_projects_points_where_blender_renders_them`,
which agrees with Blender's own projection to under a tenth of a pixel across a
full 360° orbit. The manual pass is confirming After Effects behaves the way
that model assumes.

---

## 6. M3 — headless render

### In Blender

1. Set the frame range and press **Render Headless**.
2. The status bar shows `Passthrough: n% frame x/y peak <memory>`. Blender's own
   UI stays responsive — the render is a separate process.
3. Press **Esc**. The render must stop, and the background `blender.exe` must
   disappear from Task Manager. A leftover process is a failure.
4. Press **Render Headless** again and let it finish. The report line gives the
   frame count and peak memory.

### The one that matters

5. Press **Render and Quit Blender**. Blender should close immediately and the
   render should keep going. Watch `blender.exe` in Task Manager: there should
   be exactly one, and its memory is the number this whole project exists to
   keep down.
6. While it runs, open `<output_root>/<shot_name>/render.log`. It fills with
   `PT_FRAME n/total` lines as frames complete.
7. When it finishes the log ends with `PT_DONE frames=n`, and the shot folder
   holds the §7.3 tree plus `render.log` and the `.blend` snapshot.

### Memory

The fixture scene peaks at about **484 MB**. On a real 1080×1920 shot, watch the
peak in Task Manager and compare against the 6 GB budget. If it climbs above
that, the project has failed at its one job (SPEC.md §9).

Note that pressing **Render Headless** saves a *copy* of the scene into the shot
folder rather than touching your own .blend, so unsaved edits are included and
your file is left alone.
