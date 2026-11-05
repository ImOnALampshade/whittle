#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Checks a release tag against the manifest: `release_tag.py TAG [MANIFEST]`.

v1.2.3 releases the manifest's 1.2.3. v1.2.3-rc1 is a prerelease of it, so
only the part before the hyphen is compared. Writes version= and prerelease=
to GITHUB_OUTPUT for the later jobs.
"""

import os
import sys
import tomllib
from pathlib import Path

MANIFEST = Path(__file__).resolve().parents[2] / "whittle" / "blender_manifest.toml"


def check(tag: str, manifest_version: str) -> tuple[str, bool]:
    """(version, is a prerelease), or ValueError saying what to fix."""
    if not tag.startswith("v"):
        raise ValueError(f"tag {tag!r} does not start with v")
    base, hyphen, suffix = tag[1:].partition("-")
    if hyphen and not suffix:
        raise ValueError(f"tag {tag!r} ends in a hyphen")
    if base != manifest_version:
        raise ValueError(f"tag {tag!r} is for version {base!r}, but whittle/blender_manifest.toml "
                         f"says {manifest_version!r}: bump the manifest or fix the tag")
    return manifest_version, bool(hyphen)


def main(argv: list[str]) -> int:
    if len(argv) not in (2, 3):
        print(__doc__, file=sys.stderr)
        return 2
    manifest = Path(argv[2]) if len(argv) == 3 else MANIFEST
    version = tomllib.loads(manifest.read_text(encoding="utf-8"))["version"]
    try:
        version, prerelease = check(argv[1], version)
    except ValueError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1
    print(f"Releasing {version}" + (" as a prerelease" if prerelease else ""))
    if output_file := os.environ.get("GITHUB_OUTPUT"):
        with open(output_file, "a", encoding="utf-8") as f:
            f.write(f"version={version}\nprerelease={str(prerelease).lower()}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
