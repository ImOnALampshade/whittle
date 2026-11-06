# SPDX-License-Identifier: GPL-3.0-or-later
"""The style guide a file or the preferences point at: resolving it from disk
and how the system prompt words it. Stdlib only: the add-on loads the guide
and hands over its text, the agent's prompt.build words it.

A guide is a text file that can import others, one `@path` per line, so a
project's files can share a base. The path to it is stored in the .blend, and
a file from someone else could name anything on this machine, so only text
files load and the total is capped: what loads goes to the API. For the same
reason this install is asked before it sends a guide it has not approved: the
paths it has are kept in its user folder, one per guide, so a repository of
.blend files sharing a few guides asks once for each guide on each machine,
and no .blend changes.

A guide and the .blend files naming it often live in one repository, shared
between Windows and Linux at different paths, so relative paths read the same
everywhere and Save As keeps a // path on the same file."""

import os
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from . import formats

MAX_GUIDE_BYTES = 128 * 1024
# Judged on the path with its symlinks resolved, so a notes.md link to a
# private key is refused.
GUIDE_SUFFIXES = (".md", ".txt")

# The user folder's record of the guides this install approved:
# {"format": "whittle.guides", "version": 1, "guides": [key, ...]}, each key a
# guide_key.
APPROVALS_FORMAT = "whittle.guides"
APPROVALS_NAME = "guides.json"

NO_STYLE_GUIDE = "No style guide is set for this file, so the look is yours to choose from the object and the prompt."
GUIDE_INCOMPLETE = ("Part of the user's style guide could not be loaded and is missing here. Decide what it would "
                    "have settled yourself, and if that shows in the result say so in a few words in your reply.")

# Any indent and list or quote markers before it: a fence inside a list item
# is still a fence, and guides show the import syntax in lists.
_FENCE = re.compile(r"\s*(?:(?:[-*+]|\d+[.)])\s+|>\s*)*(`{3,}|~{3,})(.*)")
_GUIDE_TAG = re.compile(r"<(?=\s*/?\s*style_guide\b)", re.IGNORECASE)
# C:\x.md, and C:x.md, which Windows reads against that drive's current folder.
_DRIVE = re.compile(r"[A-Za-z]:")


@dataclass(frozen=True)
class Guide:
    """A style guide as read from disk: the combined text, the files it came
    from (resolved, in the order read) and what went wrong, for the user."""
    text: str = ""
    files: tuple[str, ...] = ()
    problems: tuple[str, ...] = ()

    def names(self) -> list[str]:
        """The files for the user: relative to the first one's folder where
        they are inside it, so a file from elsewhere stands out in full, and
        those from elsewhere first, so a list cut short cannot hide one.
        Otherwise in the order read, which files and the text always keep."""
        if not self.files:
            return []
        folder = os.path.join(os.path.dirname(self.files[0]), "")
        inside = [path.removeprefix(folder) for path in self.files if path.startswith(folder)]
        return [path for path in self.files if not path.startswith(folder)] + inside


def portable_path(path: str) -> str:
    r"""A path with the backslashes of a relative one made forward slashes, so
    what was written on Windows reads on Linux and macOS: a // path, one
    relative to an importing file, one under ~. A rooted path stays as it is,
    since C:\x.md, \server\share and \x.md mean something on Windows only and
    \server made //server would read as relative to the .blend. The same on
    every platform, so a relative path cannot name a file with a backslash in
    its name."""
    return path if is_absolute(path) else path.replace("\\", "/")


def is_absolute(path: str) -> bool:
    """Whether a Style Notes path is rooted on some platform, whichever this
    one is: it then names one machine's folders, unlike a // path or one under ~."""
    return not path.startswith("//") and (path[:1] in ("/", "\\") or bool(_DRIVE.match(path)))


def absolute_path(path: str, flavour=os.path) -> str:
    """Where a path with its // already resolved leads, for the user to read:
    ~ expanded and normalised, or nothing if it is not absolute here, which
    load_guide refuses without looking. Only strings, as with rebased_path:
    real paths touch the disk, and on Windows a UNC path would reach the
    network before anyone has said it may."""
    expanded = flavour.expanduser(portable_path(path))
    return flavour.normpath(expanded) if flavour.isabs(expanded) else ""


def guide_key(path: str, flavour=os.path) -> str:
    """What an approval is kept under: absolute_path, in one case where the
    platform ignores case."""
    return flavour.normcase(absolute_path(path, flavour))


def rebased_path(path: str, old_folder: str, new_folder: str, flavour=os.path) -> str:
    """A // path written from old_folder, as new_folder has to say it to name
    the same file: forward slashes, so it stays portable, or the absolute path
    if there is no way there, as from one Windows drive to another, or if a
    folder on the way has a backslash in its name, which portable_path would
    read as a separator. The text is unchanged when the folder is, and flavour
    is ntpath or posixpath in the tests. Only strings: the path comes from the
    file, and saving it is no reason to go and look at what it names."""
    same = [flavour.normcase(flavour.normpath(folder)) for folder in (old_folder, new_folder)]
    if same[0] == same[1]:
        return path
    return _from_folder(flavour.normpath(flavour.join(old_folder, portable_path(path)[2:])), new_folder, flavour)


def relative_path(path: str, folder: str, flavour=os.path) -> str:
    """An absolute path as a // path from folder, by rebased_path's rules, or
    the text as it was if it is not absolute or has no way there. Only strings."""
    # A // path is absolute to the platform on Linux and macOS.
    if path.startswith("//") or not flavour.isabs(path):
        return path
    found = _from_folder(flavour.normpath(path), folder, flavour)
    return found if found.startswith("//") else path


def _from_folder(target: str, folder: str, flavour) -> str:
    """The // path naming target from folder, or target if there is none."""
    try:
        relative = flavour.relpath(target, folder).replace(flavour.sep, "/")
    except ValueError:
        return target
    return target if "\\" in relative else "//" + relative


def read_approved(user_dir) -> set[str]:
    """The guides this install approved. A record that cannot be read, or from
    a later version, approves nothing: the user is asked again."""
    try:
        found = formats.read_json(Path(user_dir) / APPROVALS_NAME)
    except (formats.FormatError, OSError):
        return set()
    guides = found.get("guides")
    if found.get("format") != APPROVALS_FORMAT or found.get("version") != 1 or not isinstance(guides, list):
        return set()
    return {key for key in guides if isinstance(key, str) and key}


def write_approved(user_dir, keys) -> None:
    """Writes the record through a temp file, so a crash leaves the old one."""
    formats.write_json_atomic(Path(user_dir) / APPROVALS_NAME,
                              {"format": APPROVALS_FORMAT, "version": 1, "guides": sorted(keys)})


def _import_target(line: str) -> str | None:
    """What a line imports: it holds only @path. A path with a space in it
    has to end like a guide file, so a line of prose starting with a handle
    stays prose."""
    line = line.strip()
    if not line.startswith("@") or line[1:2].isspace() or len(line) == 1:
        return None
    path = line[1:]
    if any(c.isspace() for c in path) and not path.lower().endswith(GUIDE_SUFFIXES):
        return None
    return path


def _lines(text: str) -> Iterator[tuple[str, str | None]]:
    """Each line of a file and what it imports, if anything. Lines in a
    fenced code block never import: a guide can show the syntax."""
    fence = None
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        found = _FENCE.match(line)
        if fence is not None:
            if found and found[1].startswith(fence) and not found[2].strip():
                fence = None
            yield line, None
        elif found and not (found[1][0] == "`" and "`" in found[2]):
            fence = found[1]
            yield line, None
        else:
            yield line, _import_target(line)


def _identity(real: str) -> object:
    """What makes a file the same file: a hard link, or another case of its
    name on a case-insensitive volume, is a second path to it. Paths where
    the file is gone, or where its volume gives no file ids."""
    try:
        found = os.stat(real)
    except (OSError, ValueError):
        return os.path.normcase(real)
    return (found.st_dev, found.st_ino) if found.st_ino else os.path.normcase(real)


def load_guide(path: str) -> Guide:
    """Reads the guide at an absolute path (or one starting with ~), with
    its imports in place of their @ lines. Import paths are relative to the
    file importing them, and portable_path reads them. A file reached twice counts the first time only,
    which also ends import loops. Nothing here fails: what cannot load is a
    problem in the result, and the rest of the guide still counts, up to
    MAX_GUIDE_BYTES. There the walk stops: what came before stays, and the
    file over the limit and all that follows are left out."""
    out: list[str] = []
    files: list[str] = []
    problems: list[str] = []
    seen: set[object] = set()
    room = MAX_GUIDE_BYTES
    # The files being read, innermost last: their paths and remaining lines.
    # A list rather than recursion, since a chain of imports can be deep.
    stack: list[tuple[str, Iterator]] = []

    def visit(target: str, shown: str) -> None:
        nonlocal room
        real = os.path.realpath(target)
        key = _identity(real)
        if key in seen:
            return
        seen.add(key)
        if os.path.splitext(real)[1].lower() not in GUIDE_SUFFIXES:
            problems.append(f"{shown} was refused: only .md and .txt files load.")
            return
        # A regular file only: reading a pipe called notes.md would never end.
        if not os.path.isfile(real):
            problems.append(f"{shown} was not found.")
            return
        try:
            with open(real, "rb") as f:
                data = f.read(room + 1)
        except OSError as exc:
            problems.append(f"{shown} cannot be read: {exc.strerror or exc}.")
            return
        if len(data) > room:
            problems.append(f"{shown} passes the {MAX_GUIDE_BYTES // 1024} KiB limit: "
                            "it and the rest of the guide were left out.")
            room = -1
            return
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = "\0"
        if "\0" in text:
            problems.append(f"{shown} cannot be read: it is not UTF-8 text.")
            return
        room -= len(data)
        files.append(real)
        stack.append((real, _lines(text)))

    expanded = os.path.expanduser(portable_path(path))
    if os.path.isabs(expanded):
        visit(expanded, path)
    else:
        problems.append(f"{path} is not an absolute path.")
    # The cap ends the walk: what follows was written to follow what is gone.
    while stack and room >= 0:
        importer, lines = stack[-1]
        found = next(lines, None)
        if found is None:
            stack.pop()
        elif found[1] is None:
            out.append(found[0])
        else:
            target = os.path.join(os.path.dirname(importer), os.path.expanduser(portable_path(found[1])))
            visit(target, f"@{found[1]} in {os.path.basename(importer)}")
    return Guide("\n".join(out).strip(), tuple(files), tuple(problems))


def guide_section(text: str, incomplete: bool = False) -> str:
    """The guide for the system prompt: its text in tags, so its own headings
    stay inside it, and a line if part of it is missing. A tag of the same
    name in the text is defused: closing the block early would make what
    follows read as Whittle's own prompt."""
    text = _GUIDE_TAG.sub("&lt;", text.strip())
    if not text and not incomplete:
        return NO_STYLE_GUIDE
    parts = [GUIDE_INCOMPLETE] if incomplete else []
    if text:
        parts.append(f"<style_guide>\n{text}\n</style_guide>")
    return "\n\n".join(parts)
