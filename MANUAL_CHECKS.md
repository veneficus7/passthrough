# Manual checks

SPEC.md §9 asks for a short written checklist for the half of testing that
cannot be automated. Run the relevant section once per milestone.

Everything here assumes the repo root as the working directory.

---

## 0. Automated checks (run these first)

```bash
.venv/Scripts/python -m pytest
```

Expect **70 passed**. That figure includes 9 integration tests that launch a
real Blender; if Blender is not found they are skipped rather than failed, and
you would see `61 passed, 9 skipped` instead — which means the integration half
did **not** run.

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
