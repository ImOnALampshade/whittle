#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Downloads the pinned Blender for this runner and unpacks it.

Nothing is unpacked before its SHA-256 matches the pin below, so a cached or
downloaded archive is never trusted on its own. To move to another Blender,
take the hashes from blender-<version>.sha256 beside the archives on
download.blender.org and change VERSION and ARCHIVES together.

Stdlib only: it runs on the runner's own Python, before any venv exists.
"""

import argparse
import hashlib
import http.client
import os
import platform
import shutil
import stat
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

VERSION = "5.2.3"
SERIES = VERSION.rsplit(".", 1)[0]
# What blender.org's 5.2 builds bundle on every platform. A distribution's
# package can differ: it may run on the system's Python instead.
PYTHON = "python3.13"
BASE_URL = f"https://download.blender.org/release/Blender{SERIES}"
# Blender publishes no Linux arm64 build, and Intel Macs are not supported.
ARCHIVES = {
    ("Linux", "x86_64"): (
        f"blender-{VERSION}-linux-x64.tar.xz",
        "78486c018b4443efe5e75ab54c290ed8c15abafd249b862c2c9ce2530a918eec"),
    ("Windows", "AMD64"): (
        f"blender-{VERSION}-windows-x64.zip",
        "723f08a4401502561eb763cdeacf8745b31e5f3f154d287d3830d97cf75dc2fb"),
    ("Darwin", "arm64"): (
        f"blender-{VERSION}-macos-arm64.dmg",
        "acc05374485a272342d4b323c15ac01953e7f697da2f1bad8af9c3bf087267a4"),
}
ATTEMPTS = 3
RETRY_WAIT = 5.0
SOCKET_TIMEOUT = 60.0
DOWNLOAD_DEADLINE = 900.0
UNPACK_TIMEOUT = 600.0
CHUNK = 1 << 20


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


class BadDownload(Exception):
    """A download that ended, but not with the pinned file."""


def download_once(url: str, part: Path, deadline: float) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "whittle-ci"})
    written = 0
    with urllib.request.urlopen(request, timeout=SOCKET_TIMEOUT) as response, open(part, "wb") as out:
        # read() just ends early when a connection with a length is cut.
        size = response.headers.get("Content-Length", "")
        while chunk := response.read(CHUNK):
            if time.monotonic() > deadline:
                raise TimeoutError(f"not finished after {DOWNLOAD_DEADLINE:g} s")
            out.write(chunk)
            written += len(chunk)
    if size.isdigit() and written != int(size):
        raise BadDownload(f"cut off after {written} of {size} bytes")


def download(url: str, target: Path, expected: str) -> None:
    """To target, through a .part file that only takes target's name once its
    hash matches, so a cut-off or wrong download leaves nothing that looks
    finished. Either is retried: both can be a network blip."""
    part = target.with_name(target.name + ".part")
    deadline = time.monotonic() + DOWNLOAD_DEADLINE
    for attempt in range(1, ATTEMPTS + 1):
        try:
            print(f"Downloading {url} (attempt {attempt})", flush=True)
            download_once(url, part, deadline)
            actual = sha256(part)
            if actual != expected:
                raise BadDownload(f"SHA-256 mismatch:\n  expected {expected}\n  got      {actual}")
            part.replace(target)
            return
        except (OSError, http.client.HTTPException, BadDownload) as exc:
            print(f"Download failed: {exc}", file=sys.stderr, flush=True)
            part.unlink(missing_ok=True)
            if attempt == ATTEMPTS or time.monotonic() > deadline:
                raise SystemExit(f"could not download {url}: {exc}\nNothing was unpacked.") from exc
            time.sleep(RETRY_WAIT * attempt)


def fetch(name: str, expected: str, archive_dir: Path) -> Path:
    """The verified archive. One already there (a cache hit) is only used if
    its hash matches; otherwise it is replaced."""
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive = archive_dir / name
    if archive.is_file():
        if sha256(archive) == expected:
            print(f"Using the cached {name}: SHA-256 matches", flush=True)
            return archive
        print(f"The cached {name} does not match its pin: downloading it again", flush=True)
        archive.unlink()
    download(f"{BASE_URL}/{name}", archive, expected)
    print(f"SHA-256 verified: {name} {expected}", flush=True)
    return archive


def unpack_linux(archive: Path, install_dir: Path) -> tuple[Path, Path]:
    subprocess.run(["tar", "-xJf", str(archive), "-C", str(install_dir), "--strip-components=1"],
                   check=True, timeout=UNPACK_TIMEOUT)
    return install_dir, install_dir / SERIES / "python" / "bin" / PYTHON


def unpack_windows(archive: Path, install_dir: Path) -> tuple[Path, Path]:
    with zipfile.ZipFile(archive) as bundle:
        bundle.extractall(install_dir)
    root = install_dir / archive.name.removesuffix(".zip")
    return root, root / SERIES / "python" / "bin" / "python.exe"


def unpack_macos(archive: Path, install_dir: Path) -> tuple[Path, Path]:
    mount = install_dir / "mount"
    mount.mkdir()
    subprocess.run(["hdiutil", "attach", "-nobrowse", "-readonly", "-noautoopen",
                    "-mountpoint", str(mount), str(archive)],
                   check=True, stdin=subprocess.DEVNULL, timeout=UNPACK_TIMEOUT)
    try:
        subprocess.run(["cp", "-R", str(mount / "Blender.app"), str(install_dir)],
                       check=True, timeout=UNPACK_TIMEOUT)
    finally:
        subprocess.run(["hdiutil", "detach", str(mount)], check=False, timeout=120)
    # A script, not a symlink: Blender finds its resources from the path it
    # was started by, and its binary is Blender, not blender.
    contents = install_dir / "Blender.app" / "Contents"
    bin_dir = install_dir / "bin"
    bin_dir.mkdir()
    launcher = bin_dir / "blender"
    launcher.write_text(f'#!/bin/sh\nexec "{contents / "MacOS" / "Blender"}" "$@"\n', encoding="utf-8")
    launcher.chmod(launcher.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return bin_dir, contents / "Resources" / SERIES / "python" / "bin" / PYTHON


UNPACK = {"Linux": unpack_linux, "Windows": unpack_windows, "Darwin": unpack_macos}


def publish(blender_dir: Path, python: Path) -> None:
    """Hands the results to the later steps of a GitHub Actions job."""
    print(f"Blender folder: {blender_dir}\nBlender's Python: {python}", flush=True)
    if path_file := os.environ.get("GITHUB_PATH"):
        with open(path_file, "a", encoding="utf-8") as f:
            f.write(f"{blender_dir}\n")
    if output_file := os.environ.get("GITHUB_OUTPUT"):
        with open(output_file, "a", encoding="utf-8") as f:
            f.write(f"python={python}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--archive-dir", type=Path, required=True,
                        help="where the archive is kept (the folder CI caches)")
    parser.add_argument("--install-dir", type=Path, required=True,
                        help="where to unpack; must not exist yet")
    args = parser.parse_args()

    system, machine = platform.system(), platform.machine()
    if (system, machine) not in ARCHIVES:
        print(f"No pinned Blender {VERSION} for {system} {machine}", file=sys.stderr)
        return 1
    if args.install_dir.exists():
        print(f"{args.install_dir} already exists", file=sys.stderr)
        return 1
    name, expected = ARCHIVES[system, machine]
    archive = fetch(name, expected, args.archive_dir)
    args.install_dir.mkdir(parents=True)
    try:
        blender_dir, python = UNPACK[system](archive, args.install_dir)
    except BaseException:
        shutil.rmtree(args.install_dir, ignore_errors=True)
        raise
    if not python.is_file():
        print(f"{name} has no Python at {python}", file=sys.stderr)
        return 1
    publish(blender_dir, python)
    return 0


if __name__ == "__main__":
    sys.exit(main())
