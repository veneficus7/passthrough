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
- [ ] Version number. It is `0.1.0`. Nothing about the Blender side is
      provisional, but **the After Effects half has never been run in After
      Effects** — see the caveat below

### Needs doing at submission time

- [ ] A Blender ID account, if you do not have one
- [ ] Build the release zip: `python tools/build_extension.py`
- [ ] Upload at <https://extensions.blender.org/submit/>
- [ ] Fill in the listing: description, screenshots, a link to the repository
      if it is public by then
- [ ] Wait for moderator review

---

## The thing to weigh before publishing at all

Every Blender-side claim in this project is tested: 369 automated tests, camera
conversion verified against Blender's own projection to under a tenth of a pixel,
memory estimates measured against real renders.

**The After Effects half has never been run in After Effects.** The generated
`.jsx` is checked for valid ECMAScript 3, balanced delimiters and correct
structure, and the scripting behaviour is taken from Adobe's documentation — but
nobody has clicked *Run Script File* on a real installation. `guideLayer`,
`conformFrameRate`, `AlphaMode`, `addNull`'s anchor defaults, and the assumption
that parenting to an identity null changes nothing are all inference.

Publishing an add-on whose entire second half is unverified is a choice, not an
oversight. Run [MANUAL_CHECKS.md](MANUAL_CHECKS.md) §5 and §7 in real After
Effects first. It is an hour, and it is the difference between "tested" and
"believed to work".

---

## After publishing

- Version bumps go in `blender_manifest.toml`; the build tool picks them up.
- The platform serves the zip you upload; there is no build step on their side,
  so whatever `tools/build_extension.py` verified is exactly what users get.
- Reports will arrive from people on Blender versions and After Effects versions
  you do not have. The Blender-version gate failure looks like a broken add-on
  rather than a version problem — see the note at the top of USAGE.md.
