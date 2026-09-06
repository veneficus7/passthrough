# Using Passthrough

A guide for someone who has just installed this and wants to get a shot from
Blender into After Effects.

You do not need to know Blender's compositor, node editor, or render settings.
You do need to know After Effects — that is where the actual work happens.

---

## What this does, in one paragraph

Blender renders your shot as **separate passes** — the beauty, the emission, the
mist, the surface normals, an object matte — writes each one as its own image
sequence, and quits. Then you open After Effects, run one script, and get a comp
with the camera, the nulls and every pass already imported and stacked. You build
the look in After Effects, with real footage layers, instead of fighting Blender's
shader editor.

The reason it works this way is memory. Blender and After Effects together will
not fit in 16 GB. Passthrough makes sure only one of them is running at a time.

---

## Before you start

| You need | Notes |
|---|---|
| Blender 5.2 or newer | See the version note below if you have 5.1 |
| After Effects 2025 or newer | Windows |
| Disk space | EXR sequences are large. A 120-frame shot at 1080×1920 is roughly 1–2 GB |

**If Blender is older than 5.2**, the add-on will *install* and then refuse to
*enable*. The checkbox will not stay ticked and no panel appears. It looks like a
broken add-on and it is not — open *Window ▸ Toggle System Console* and you will
see:

```
ERROR passthrough: This Blender version (5.1.2) doesn't meet the minimum supported version (5.2.0)
```

Install Blender 5.2, or edit `blender_version_min` in the manifest if you want to
try it on an older build.

---

## Install

1. Build the add-on zip, or use one you were given:

   ```bash
   blender --command extension build --source-dir blender_addon/passthrough --output-dir dist
   ```

2. In Blender: *Edit ▸ Preferences ▸ Add-ons ▸ Install from Disk*, choose
   `dist/passthrough-0.1.0.zip`.
3. The **Passthrough** panel appears in **Render Properties** (the little camera
   back icon in the properties column).

### Set two things once

In *Edit ▸ Preferences ▸ Add-ons ▸ Passthrough*:

- **Pixels per Blender Unit** — leave at 100 unless you know you want otherwise.
  It decides how big your scene arrives in After Effects. 100 matches Blender's
  own AE exporter.
- **Memory Budget** — the ceiling the scene doctor checks against. 6 GB is right
  for a 16 GB machine.

---

## The workflow

Everything lives in **Render Properties ▸ Passthrough**.

### 0. Start from a template (optional, but the fastest way in)

Expand **Shot Templates**, pick one, and press **Build Scene**. You get a
complete lit scene with a camera and a move already animated, at 1080×1920.

| Template | What you get |
|---|---|
| **Liminal Corridor** | A long corridor receding into fog, ceiling panels overhead |
| **Volumetric Light Room** | A dark room cut by hard beams through slits |
| **Camera Move Rig** | An orbit, dolly or push-in aimed at a subject |
| **3D Text in Space** | Extruded text floating in the dark, slowly turning |
| **Debris Field** | Tumbling fragments, some of them glowing |

Every parameter above the button is yours to change — length, colours, fog,
frame count — then press **Build Scene** again. It replaces the previous build
rather than stacking a second copy.

**Build Scene deletes what is already in the scene** so the default cube does
not end up in your shot. Untick **Replace Scene** in the operator panel
(bottom-left after building) if you are adding a template to work you want to
keep.

If you have your own scene, skip this step entirely — nothing else depends on it.

### 1. Say where the render goes

- **Output Root** — a folder you can find. `//renders` puts it next to your
  `.blend`.
- **Shot Name** — becomes a subfolder. Use something per-shot, like `corridor`
  or `logo_spin`.

Everything for one shot ends up in `<Output Root>/<Shot Name>/`.

### 2. Check the scene will fit

Expand **Scene Doctor** and press **Check Scene**.

It projects what the render will cost from your texture sizes, polygon counts and
render resolution, and compares that against your budget. The breakdown goes to
the system console.

If it says you are over budget, a **Fit to Budget** button appears. Pressing it
degrades the scene until it fits, in this order, stopping as soon as it does:

1. **Caps oversized textures.** Usually invisible at 1080×1920 and usually
   enough on its own.
2. **Decimates heavy objects.** Adds a modifier called `PT Decimate`. Delete the
   modifier to undo.
3. **Clamps render resolution.** The last resort, because it changes what you
   are delivering.

This step is optional but cheap. A render that dies on frame 380 of 400 costs you
the whole evening.

### 3. Set up the passes

Press **Set Up Passes**. That is the whole step.

It turns on the right render passes and wires Blender's compositor to write each
one into its own folder. Pressing it again is safe — it updates what is there
rather than adding a second copy.

You never have to open the compositor. If you are curious, the *Compositing*
workspace will show one **Render Layers** node feeding five **File Output** nodes.

### 4. Render

Two buttons, and the difference matters:

- **Render Headless** — renders in a separate background Blender while this
  window stays open. The status bar shows progress. Press **Esc** to cancel.
- **Render and Quit Blender** — launches the render and closes Blender
  immediately. The render keeps going without it.

**Use the second one.** It frees roughly 1–2 GB, and it is the entire reason this
tool exists. Progress goes to `<Output Root>/<Shot Name>/render.log`, which you
can open in any text editor while it runs. Lines like `PT_FRAME 42/120` tell you
where it is; the last line is `PT_DONE`.

Go and do something else. Do not open After Effects yet.

### 5. Write the After Effects script

Press **Export After Effects Script**. It writes
`<Output Root>/<Shot Name>/<Shot Name>.jsx`, next to the pass folders.

You can do this before, during or after the render — it works out the file paths
rather than looking at the disk.

### 6. Build the comp

Now Blender can be closed.

In After Effects:

1. *File ▸ Project Settings ▸ Color* — set **Depth** to **32 bits per channel**.
   The passes are linear HDR; at 8 bpc you will clip everything above white and
   wonder where your highlights went.
2. *File ▸ Scripts ▸ Run Script File…* and pick the `.jsx`.

You get a comp matching your Blender scene — same size, same frame rate, same
duration — containing:

```
Blender Camera        ← animated to match Blender exactly
PT World              ← a null everything is parented to
your empties          ← one 3D null each, named as in Blender
Cryptomatte Object    ← guide layer, off
Normal                ← guide layer, off
Mist                  ← guide layer, off
Emission              ← guide layer, off
Beauty                ← visible. this is your image
```

Running the script again updates the same comp instead of making a second one.

---

## What the passes are for

Only **Beauty** is switched on. The rest are handed to you switched off, with no
blend modes and no effects, because guessing what look you want is not this
tool's job. Turn one on and it becomes an ordinary footage layer.

| Pass | What it is | What it is good for |
|---|---|---|
| **Beauty** | The finished render | Your base image |
| **Emission** | Only the glowing surfaces | Set to Add above beauty for bloom you control |
| **Mist** | Distance from camera, white = far | Drives depth of field, atmospheric haze, distance fades |
| **Normal** | Surface direction as RGB | Relighting, fake specular, direction-based masks |
| **Cryptomatte Object** | Per-object ID mattes | Nothing, without a plugin — see below |

**Cryptomatte renders black in After Effects, and that is expected.** It is not
a picture — each pixel encodes *which object is there*, as float ID hashes. Two
things stop AE showing it: AE has no native cryptomatte support, and Blender
writes that pass with lowercase `r`/`g`/`b`/`a` channel names while AE's EXR
reader looks for uppercase. Turning the layer on gives you a black frame.

It is imported anyway, switched off, so it is there if you ever add a plugin
that reads it. For simple object isolation a mist or normal-based mask is
easier. **Leave the layer off.**

Every pass layer carries this explanation in its **Comment** column in the
timeline, so you do not have to come back here.

---

## When something goes wrong

**A pass layer imports completely black.**
Check the project is at 32 bits per channel first. If beauty looks right and one
other pass is black, that pass genuinely has nothing in it — an emission pass with
no emissive materials is black, and that is correct.

**Everything looks washed out or muddy.**
Your project colour settings. The passes are written linear on purpose, with no
view transform baked in, so the grade stays yours.

**The camera does not line up with the render.**
Select `PT World` and confirm its **Position** and **Anchor Point** are both
`0,0,0`. Everything is parented to it, so if it has drifted the whole scene moves.

**A pass has dark fringes at its edges.**
Open the `.jsx` in a text editor and change `PT_ALPHA_PREMULTIPLIED = true;` to
`false`, then run it again.

**The passes drift out of sync with the camera.**
Select a pass in the project panel and check *Interpret Footage* — the frame rate
should match the comp, not 30. The script sets this, so if it is wrong, say so.

**No Passthrough panel in Blender.**
Almost always the version gate. Open the system console and read the error.

**The render stopped early.**
Open `render.log` in the shot folder. The last lines say what happened; a line
starting `PT_ERROR` is the reason.

---

## Getting the most out of 16 GB

None of this is Passthrough, but the tool is much less useful without it:

- Work at **1080×1920**, not 4K.
- After Effects: set the disk cache large (100 GB) on your fastest drive.
- After Effects: set **RAM reserved for other applications** to about 3 GB.
  Blender is never open at the same time, so it does not need a share.
- After Effects: raise **% CPU reserved for other applications**. Multi-Frame
  Rendering starts a process per core and each one wants memory; on 16 GB it is
  often a net loss.
- Windows: give yourself a fixed 24–32 GB page file. It will not make anything
  fast, but it turns hard crashes into merely slow.
- Close Chrome, Discord, Photoshop and Premiere before editing. Photoshop and
  Premiere share one memory pool with After Effects.

---

## What this does not do

- **Cycles.** EEVEE only.
- **Video files.** Image sequences only, so a crash on frame 300 costs you one
  frame instead of everything.
- **Live sync between Blender and After Effects.** That would need both open at
  once, which is the problem this exists to solve.
- **Lights.** They are not exported. AE lights only affect 3D layers that accept
  them, and every pass is a flat 2D footage layer, so they would do nothing.
- **Materials or look development.** That is what After Effects is for here.

---

## A caveat worth reading

The Blender half of this is tested hard: 244 automated tests, including ones that
render real frames and check the files on disk. The camera conversion is verified
against Blender's own projection maths to under a tenth of a pixel.

The **After Effects half has never been run in After Effects.** The scripts are
checked for valid ExtendScript and correct structure, and the AE scripting
behaviour is taken from the documentation, but nobody has yet clicked *Run Script
File* on a real installation. If something in step 6 does not behave as described
above, it is a genuine bug and worth reporting rather than working around.

[MANUAL_CHECKS.md](MANUAL_CHECKS.md) has a checklist for verifying it yourself.
