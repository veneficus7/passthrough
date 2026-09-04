# Passthrough — Project Specification

> A Blender → After Effects pass pipeline built for machines that don't have enough RAM.

**Handoff note for Claude Code:** Read this whole file before writing code. Build **one milestone at a time** and stop for review after each. Do not scaffold future milestones early. Every milestone has acceptance criteria — meet them, run the tests, then stop.

---

## 1. What this is

A Blender add-on (plus a generated After Effects script) that turns Blender into a **render-pass backend** for After Effects, so the user never has to do look-development inside Blender and never has to run both applications at once.

The user presses one button in Blender. The tool:

1. Configures the correct EEVEE render passes for the scene
2. Estimates whether the scene fits in the available memory, and offers to fix it if not
3. Renders headlessly in a background process, with Blender's UI closed
4. Writes a `.jsx` file that, when run in After Effects, rebuilds the whole shot — camera, nulls, lights, and every pass imported as a separate stacked layer

The compositing and the final look happen in After Effects, where the user is already skilled.

## 2. Who it is for and why it exists

The author edits short-form video in After Effects on a laptop with **16 GB of system RAM** and an **RTX 5060 (8 GB VRAM)**. Running After Effects and Blender simultaneously causes swap thrashing, multi-second UI freezes, and out-of-memory crashes. Adobe lists 16 GB as the *minimum* for After Effects alone.

Buying more RAM is not an option. The tool's entire reason to exist is to make a two-application 3D workflow fit inside a memory budget it does not naturally fit into.

This constraint is not a footnote. **It is the product.** Every design decision below is downstream of it.

## 3. Design principles

1. **Only one application holds significant memory at a time.** Blender renders headlessly and exits. Then After Effects opens. The tool enforces this ordering rather than trusting the user to remember it.
2. **Never render a finished frame.** Render separated passes and rebuild the look in After Effects. This is cheaper on the GPU, more flexible downstream, and requires far less Blender knowledge.
3. **Measure before you render.** The scene doctor reports projected memory cost before committing, because a failed 400-frame render is 40 minutes lost.
4. **Degrade, never crash.** Given a memory ceiling, reduce texture resolution, decimate geometry, and cap render resolution automatically rather than letting the render die.
5. **Everything free.** No paid plugins, no paid services, no paid assets. CC0 sources only.

## 4. Non-goals

Do not build these. They are explicitly out of scope:

- A general-purpose 3D asset browser. Blender 5.2 shipped Online Assets in July 2026, and manually downloading a model from Poly Haven takes thirty seconds. This is not a bottleneck.
- Cycles support. EEVEE only.
- A material or shader editor. Materials come from templates and CC0 libraries.
- Live link / real-time sync between Blender and After Effects. That would require both applications open, which defeats the entire purpose.
- macOS or Linux support in v1. After Effects is Windows-first here; keep paths platform-agnostic where free, but do not spend effort testing elsewhere.
- Video file output. Image sequences only (crash resilience).

## 5. Environment and target versions

| Thing | Version |
|---|---|
| Blender | 5.2 LTS (July 2026) |
| After Effects | 2025 or newer, Windows |
| Python | Blender's bundled interpreter (3.11+) for the add-on; system Python 3.11+ for tests |
| AE scripting | **ExtendScript (`.jsx`)** — UXP is still not available for After Effects as of 2026 |
| GPU | RTX 5060 laptop, 8 GB VRAM |
| System RAM | 16 GB — assume ~11 GB usable after the OS |

## 6. Repository layout

```
passthrough/
├── README.md
├── SPEC.md                          # this file
├── pyproject.toml                   # pytest + ruff config
├── blender_addon/
│   └── passthrough/                 # zip root MUST be named after the extension id
│       ├── blender_manifest.toml
│       ├── __init__.py              # registration only
│       ├── ui.py                    # panels + properties
│       ├── prefs.py                 # add-on preferences (AE project dir, px-per-unit, RAM budget)
│       ├── passes.py                # view layer pass config + compositor File Output tree
│       ├── camera_convert.py        # PURE PYTHON, no bpy import at module level
│       ├── scene_doctor.py          # PURE PYTHON where possible
│       ├── jsx_writer.py            # emits the .jsx, no bpy at module level
│       ├── render_job.py            # run inside `blender -b -P`
│       ├── queue.py                 # subprocess management + progress parsing
│       └── templates/               # M6: shot template .blend files + JSON schemas
├── ae_scripts/
│   └── runtime/
│       └── pt_runtime.jsx           # shared ExtendScript helpers, concatenated into output
├── tests/
│   ├── test_camera_convert.py
│   ├── test_scene_doctor.py
│   ├── test_jsx_writer.py
│   └── fixtures/
└── tools/
    └── build_extension.py           # wraps `blender --command extension build`
```

**Architectural rule:** `camera_convert.py`, `scene_doctor.py`, and `jsx_writer.py` must not import `bpy` at module scope. They take plain dicts and floats and return plain data. This is what makes the project unit-testable in ordinary pytest without launching Blender, and it is the single most important structural decision in the codebase. Pass `bpy` data *in*; do not reach *out* for it.

## 7. Technical gotchas — read this section twice

These are the things that will silently waste a day if you get them wrong.

### 7.1 ExtendScript is not modern JavaScript

The `.jsx` output runs in After Effects' ExtendScript engine, which is roughly **ECMAScript 3**. The following **do not exist** and will fail, sometimes silently:

- `let`, `const` — use `var`
- Arrow functions — use `function () {}`
- Template literals — use string concatenation
- `JSON.parse` / `JSON.stringify` — **not built in**; bundle a `json2.js` polyfill in `pt_runtime.jsx` or avoid JSON entirely on the AE side
- `Array.prototype.forEach` / `map` / `filter` / `indexOf` — unreliable; use indexed `for` loops
- `String.prototype.trim`, `Object.keys` — not present

Generate plain, boring ES3. Prefer emitting literal `var` declarations from Python over serialising JSON and parsing it in AE.

### 7.2 Blender → After Effects camera conversion

This is the hardest correctness problem in the project and the thing most likely to be subtly wrong.

**Coordinate systems.** Blender is Z-up, right-handed. After Effects is Y-**down**, with Z going into the screen. With `s` = pixels per Blender unit and comp size `W × H`:

```
ae_x = ( bx * s) + W / 2
ae_y = (-bz * s) + H / 2
ae_z = ( by * s)
```

**Camera zoom.** After Effects expresses camera FOV as a `zoom` value in pixels. For horizontal sensor fit:

```
zoom_px = comp_width * focal_length_mm / sensor_width_mm
```

**Camera rotation.** Blender cameras look down local −Z; After Effects cameras look down +Z, so there is a 180° reconciliation. **Do not derive this from scratch.** Blender ships a reference implementation that already solves it correctly — read the bundled `io_export_after_effects` add-on source (Blender's `scripts/addons_core/io_export_after_effects/`) and port its matrix conversion. Then unit test the port. Reinventing this will cost you a day and still be wrong at the edges.

**Verification test (do this, it catches everything):** place a cube at a known world position, render one frame, run the generated `.jsx`, and confirm an AE null at the converted position lands on the same pixel as the cube in the rendered image. Automate the numeric half in pytest; do the visual half once by hand.

### 7.3 Do not use multi-layer EXR

Multi-layer EXR extraction in After Effects historically depends on plugins that Adobe no longer reliably bundles. Sidestep it entirely:

**Write one image sequence per pass, into one folder per pass.** Predictable paths, works in every AE version, trivial to import.

```
<output_root>/<shot_name>/
├── beauty/     beauty_0001.exr ...
├── emission/   emission_0001.exr ...
├── mist/       mist_0001.exr ...
├── normal/     normal_0001.exr ...
└── crypto/     crypto_0001.exr ...
```

Achieve this with the **Compositor's File Output node**, wired up by `passes.py`. Give each node input a deterministic name so `jsx_writer.py` can predict every path without inspecting the disk.

### 7.4 Colour management

Render **linear EXR**, or set the view transform to **Standard** if writing PNG. If AgX is baked into the passes they will not composite correctly, and the symptom is "everything looks muddy and I don't know why." Set this explicitly in `render_job.py`; do not inherit whatever the scene had.

### 7.5 Blender extension packaging

Blender 4.2+ uses `blender_manifest.toml` rather than `bl_info`. Legacy `bl_info` add-ons still load, but write the manifest from day one — it costs nothing and is required to publish later.

```toml
schema_version = "1.0.0"
id = "passthrough"
name = "Passthrough"
tagline = "Render Blender passes straight into an After Effects comp"
version = "0.1.0"
type = "add-on"
maintainer = "Bakhodir <321123292+veneficus7@users.noreply.github.com>"
license = ["SPDX:GPL-3.0-or-later"]
blender_version_min = "5.2.0"
tags = ["Render", "Pipeline"]
```

The distributed zip must contain a **folder named after the `id`**, not loose files. Build with `blender --command extension build`.

### 7.6 Headless rendering

```
blender -b <scene.blend> -P render_job.py -- --shot <name> --out <dir> --start 1 --end 120
```

Arguments after `--` are yours; Blender ignores them. `render_job.py` configures passes, colour management, and resolution, then renders. Parse progress from Blender's stdout, which emits lines shaped like `Fra:12 Mem:412.35M ...`.

Rendering headlessly rather than from the Blender UI saves roughly 1–2 GB of RAM on its own. That is the point.

## 8. Milestones

Build in this order. Stop after each.

### M0 — Skeleton
Repo, `pyproject.toml`, manifest, empty add-on that registers cleanly.

**Acceptance:** extension installs in Blender 5.2 without errors; a "Passthrough" panel appears in Render Properties; `pytest` runs and collects zero failures.

### M1 — Pass setup and File Output wiring
`passes.py` enables the EEVEE passes and builds the compositor File Output node tree.

Passes for v1: **Combined (beauty), Mist, Normal, Emission, Cryptomatte Object.** (Ambient Occlusion and Vector come later.)

**Acceptance:** one button configures a fresh scene; rendering a single frame produces the exact folder structure in §7.3 with one image per pass; re-running the operator is idempotent and does not duplicate nodes.

### M2 — Camera conversion and `.jsx` generation
`camera_convert.py` (pure Python) plus `jsx_writer.py`.

**Acceptance:** unit tests cover position mapping, zoom derivation, and rotation against hand-computed values; a generated `.jsx` runs in After Effects without error and creates a comp of the right size, duration, and frame rate containing a camera whose animation matches Blender's.

### M3 — Headless render and queue
`render_job.py` and `queue.py`. Subprocess launch, stdout progress parsing, cancellation, completion notification.

**Acceptance:** a render launched from the Blender panel completes with the Blender UI closed; progress is reported; cancelling terminates the child process cleanly; peak system RAM stays under 6 GB for the test scene.

### M4 — Full After Effects import
Extend `jsx_writer.py` to import every pass sequence, stack the layers, and parent nulls.

Layer treatment: beauty is the visible base layer. Every other pass is imported, placed above it, set as a **guide layer** (`layer.guideLayer = true`), and **disabled by default**. Do not presume a look — give the user the ingredients, arranged and labelled, and let them build.

**Acceptance:** running the `.jsx` on a rendered shot produces a comp with all passes imported in the correct order, correctly named, camera and nulls parented, comp settings matching the Blender scene. No manual fixing required.

### M5 — Scene doctor
`scene_doctor.py`. Estimate memory cost from texture resolutions, mesh polycounts, and render resolution. Report before rendering. Offer auto-fix: cap texture size via Simplify, decimate above a polygon threshold, clamp render resolution.

**Acceptance:** given a deliberately heavy test scene, the doctor's estimate is within ±25% of Blender's actual reported peak; auto-fix brings a scene that OOMs at 16 GB down to one that renders successfully.

### M6 — Shot templates
Five parameterised `.blend` scenes with JSON parameter schemas: liminal corridor, volumetric light room, orbit/dolly/push-in camera rig, 3D text in space, debris field. The add-on builds and updates scenes from JSON.

**Acceptance:** a user with no Blender knowledge can produce a rendered, composited shot using only the Passthrough panel, without opening the shader editor or the node graph.

### M7 — Package and publish
`tools/build_extension.py`, README with GIFs, LICENSE, submission to extensions.blender.org.

**Acceptance:** a clean zip installs on a machine that has never seen the source.

## 9. Testing strategy

- **Unit (pytest, no Blender):** camera maths, memory estimation, `.jsx` string generation. This is the bulk of the coverage and it is fast because of the §6 architectural rule.
- **Integration (`blender -b`):** run a headless render of a fixture `.blend`, assert the output tree matches expectations.
- **Manual, once per milestone:** run the generated `.jsx` in real After Effects. Keep a short written checklist; there is no way to automate this half and pretending otherwise wastes time.
- **Memory regression:** log peak RSS for the fixture scene on every integration run. If it climbs, the project has failed at its one job.

## 10. Definition of done for v1

The author can select a shot template, adjust a handful of parameters, press one button, walk away while it renders with After Effects closed, then open After Effects, run one script, and find a complete comp with separated passes ready to grade — without opening Blender's node editor and without a single freeze or out-of-memory crash.

---

## Appendix A — Reference links

- [Blender 5.2 LTS release notes](https://www.blender.org/download/releases/5-2/)
- [How to Create Extensions — Blender Manual](https://docs.blender.org/manual/en/latest/advanced/extensions/getting_started.html)
- [Render Passes — Blender Manual](https://docs.blender.org/manual/en/latest/render/layers/passes.html)
- [Export: Adobe After Effects (.jsx) — reference implementation to port camera maths from](https://extensions.blender.org/add-ons/io-export-after-effects/)
- [After Effects Scripting Guide (ExtendScript)](https://ae-scripting.docsforadobe.dev/)
- [Memory and storage in After Effects — Adobe](https://helpx.adobe.com/after-effects/using/memory-storage1.html)
- [Poly Haven Public API](https://github.com/Poly-Haven/Public-API) — CC0, keyless, only if the asset fetcher is ever revisited

## Appendix B — Machine-specific settings to apply before starting

Not code, but the project is pointless without them:

- Work at 1080×1920, not 4K
- After Effects: disk cache maxed (100 GB) on the fastest drive with space
- After Effects: "RAM reserved for other applications" set to ~3 GB, since Blender is never open at the same time
- After Effects: raise "% CPU reserved for other applications" — Multi-Frame Rendering spawns a process per core and each one wants RAM; on 16 GB it is often net-negative
- Windows: fixed 24–32 GB page file. This does not make anything fast; it converts hard freezes and crashes into merely slow
- Close Chrome, Discord, Photoshop, and Premiere before editing. Photoshop and Premiere share one memory pool with After Effects
