"""Build and verify the Passthrough extension zip.

Wraps ``blender --command extension build`` (SPEC.md section 6) and then checks
the result, because the build command happily produces a zip that is missing
data files: it only complains about the manifest. The ExtendScript runtime and
the template schemas are data, and nothing would notice their absence until a
user pressed a button and got nothing.

    python tools/build_extension.py
    python tools/build_extension.py --dev-version 5.1.0
    python tools/build_extension.py --check-only

No third-party dependencies, and no ``bpy`` -- it shells out to Blender.
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ADDON_DIR = REPO_ROOT / "blender_addon" / "passthrough"
DEFAULT_OUTPUT = REPO_ROOT / "dist"

#: Everything the add-on needs at runtime that is not a Python module. These are
#: the files a build can silently drop.
REQUIRED_DATA = ("blender_manifest.toml", "ae_runtime/pt_runtime.jsx")

#: Windows install locations to try when Blender is not on PATH.
WINDOWS_BLENDER_GLOB = "C:/Program Files/Blender Foundation/Blender */blender.exe"


class BuildError(RuntimeError):
    pass


def find_blender(explicit=None):
    """Locate a Blender executable, preferring the newest installed."""
    if explicit:
        if not Path(explicit).is_file():
            raise BuildError(f"no Blender executable at {explicit}")
        return explicit

    from_env = os.environ.get("PASSTHROUGH_BLENDER")
    if from_env and Path(from_env).is_file():
        return from_env

    on_path = shutil.which("blender")
    if on_path:
        return on_path

    candidates = sorted(Path("/").glob(WINDOWS_BLENDER_GLOB.lstrip("C:/")), reverse=True)
    candidates += sorted(Path("C:/").glob(WINDOWS_BLENDER_GLOB[3:]), reverse=True)
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    raise BuildError(
        "could not find Blender. Put it on PATH, set PASSTHROUGH_BLENDER, or pass --blender"
    )


def expected_contents():
    """Every file the built zip must contain, as archive-relative paths."""
    names = set(REQUIRED_DATA)
    names.update(module.name for module in ADDON_DIR.glob("*.py"))
    names.update(f"templates/{schema.name}" for schema in (ADDON_DIR / "templates").glob("*.json"))
    return names


def verify_zip(path):
    """Check a built zip has everything, and the flat layout Blender wants.

    SPEC.md section 7.5 says the zip must contain a folder named after the id.
    It must not: Blender's own build emits a flat archive with the manifest at
    the root and creates that folder at install time. A nested one does not
    install.
    """
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())

    missing = sorted(expected_contents() - names)
    if missing:
        raise BuildError(f"{path.name} is missing: {', '.join(missing)}")

    nested = sorted(name for name in names if name.startswith("passthrough/"))
    if nested:
        raise BuildError(f"{path.name} is nested inside a folder; it should be flat")

    return sorted(names)


def build(blender, source_dir, output_dir, suffix=""):
    """Build into a scratch directory, then move the result into place.

    Building straight into the output directory looked fine until a dev build
    followed a release build: Blender names the zip from the manifest, so the
    second one silently overwrote the first, and "what is new in here" then
    found nothing. The release zip ended up carrying the dev minimum version.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as scratch:
        proc = subprocess.run(
            [
                blender,
                "--command",
                "extension",
                "build",
                "--source-dir",
                str(source_dir),
                "--output-dir",
                scratch,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,
        )
        produced = sorted(Path(scratch).glob("*.zip"))
        if proc.returncode != 0 or not produced:
            raise BuildError(
                "extension build failed\n"
                f"--- stdout ---\n{proc.stdout[-3000:]}\n"
                f"--- stderr ---\n{proc.stderr[-2000:]}"
            )
        source_zip = produced[0]
        destination = output_dir / (source_zip.stem + suffix + source_zip.suffix)
        shutil.copyfile(source_zip, destination)
    return destination


def staged_copy(destination, minimum_version=None):
    """Copy the add-on, optionally relaxing ``blender_version_min``.

    A dev build is the only way to exercise the add-on on a Blender older than
    the manifest allows -- it installs but refuses to enable otherwise.
    """
    staged = Path(destination) / ADDON_DIR.name
    shutil.copytree(ADDON_DIR, staged)
    if minimum_version:
        manifest = staged / "blender_manifest.toml"
        lines = []
        for line in manifest.read_text(encoding="utf-8").splitlines():
            if line.startswith("blender_version_min"):
                line = f'blender_version_min = "{minimum_version}"'
            lines.append(line)
        manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return staged


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build the Passthrough extension zip")
    parser.add_argument("--blender", default=None, help="path to the Blender executable")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT), type=Path)
    parser.add_argument(
        "--dev-version",
        default=None,
        metavar="X.Y.Z",
        help="relax blender_version_min, for testing on an older Blender",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="verify an already built zip in the output directory and stop",
    )
    args = parser.parse_args(argv)

    output_dir = Path(args.output_dir)

    if args.check_only:
        zips = sorted(output_dir.glob("*.zip"))
        if not zips:
            raise BuildError(f"no zip to check in {output_dir}")
        for path in zips:
            verify_zip(path)
            print(f"ok  {path}")
        return 0

    blender = find_blender(args.blender)
    print(f"blender: {blender}")

    if args.dev_version:
        with tempfile.TemporaryDirectory() as staging:
            source = staged_copy(staging, args.dev_version)
            built = build(blender, source, output_dir, suffix=f"-blender{args.dev_version}")
        print(f"built dev zip (blender_version_min {args.dev_version})")
    else:
        built = build(blender, ADDON_DIR, output_dir)

    contents = verify_zip(built)
    print(f"built:  {built}  ({built.stat().st_size:,} bytes)")
    print(f"checked {len(contents)} files, all expected data present")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BuildError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
