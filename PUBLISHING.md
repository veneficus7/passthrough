# Publishing to extensions.blender.org

SPEC.md M7 lists submission to the Blender extensions platform. **Nothing has
been submitted.** This is the checklist and, more importantly, the two decisions
that have to be made before anything leaves your machine.

---

## Read this before submitting

### 1. Submitting publishes the source code

The add-on is pure Python under GPL-3.0-or-later. The zip *is* the source — there
is nothing compiled and nothing hidden. Anyone who downloads the extension gets
every line of it.

That matters because the GitHub repository was deliberately kept **private**. If
you publish the extension, the code becomes public regardless of the repository's
visibility. The private repo would then be protecting nothing except the commit
history.

### 2. Submitting publishes your email address

`blender_manifest.toml` carries:

```toml
maintainer = "Bakhodir <321123292+veneficus7@users.noreply.github.com>"
```

The maintainer field is displayed on the extension's public listing. That is the
same address the repository was kept private to keep off the public index.

Options, in the order most people prefer them:

- Use a dedicated address, e.g. `passthrough@…`, or a forwarding alias
- Use a GitHub noreply address
- Accept it and publish as-is

**This needs your decision.** It is a one-line change to the manifest, but it is
not reversible once the listing is live and indexed.

---

## Checklist

### Ready

- [x] `blender_manifest.toml` — schema 1.0.0, valid id, tagline within limits,
      SPDX licence, tags from Blender's list
- [x] `LICENSE` — full GPL-3.0-or-later text, matching the manifest's SPDX id
- [x] Pure Python, no compiled binaries, no bundled wheels
- [x] No network access, no telemetry, no bundled assets
- [x] Builds with `blender --command extension build`
- [x] The built zip installs and runs on a machine that has never seen the
      source — verified by `tests/test_install_integration.py`
- [x] `README.md` with animated previews
- [x] `USAGE.md` for people who have never used it

### Needs a decision

- [ ] Maintainer email in the manifest (see above)
- [ ] Repository visibility — public repositories make review easier and let
      users file issues, but see above
- [ ] Version number. It is `0.1.0`. Both halves now work end to end on a real
      shot; whether that is a `0.1.0` or a `1.0.0` is a judgement call

### Needs doing at submission time

- [ ] A Blender ID account, if you do not have one
- [ ] Build the release zip: `python tools/build_extension.py`
- [ ] Upload at <https://extensions.blender.org/submit/>
- [ ] Fill in the listing: description, screenshots, a link to the repository
      if it is public by then
- [ ] Wait for moderator review

---

## Verified in After Effects

Run in **After Effects 2025 on Windows**, against a 32-frame orbiting-camera
shot at 1080 x 1920:

- the script runs with no errors and builds the comp
- comp settings match the Blender scene: 1080 x 1920, 24 fps, correct duration
- all five passes import, each conformed to **24 fps** rather than the import
  preference default
- layer order is right, with **Beauty visible at the bottom** and the other four
  as **disabled guide layers**
- every null lands on its predicted position to the pixel: `540, 960, 0` ·
  `800, 850, 120` · `540, 860, 0`
- **`PT World` reads `0, 0, 0`** -- the identity-parenting assumption holds, and
  the camera and all nulls are parented to it
- the camera orbits **smoothly and consistently** through a full 360 degrees,
  with no spin at the wrap point

That covers the coordinate conversion, the zoom derivation, the orientation
unwrapping, the layer treatment and the footage interpretation together.

Not yet exercised: alpha fringing on a shot with real edge transparency, and
running the same script twice in one session.

The one known-bad layer is **Cryptomatte Object**, which renders black. That is
expected and explained in the layer's own comment.

---

## After publishing

- Version bumps go in `blender_manifest.toml`; the build tool picks them up.
- The platform serves the zip you upload; there is no build step on their side,
  so whatever `tools/build_extension.py` verified is exactly what users get.
- Reports will arrive from people on Blender versions and After Effects versions
  you do not have. The Blender-version gate failure looks like a broken add-on
  rather than a version problem — see the note at the top of USAGE.md.
