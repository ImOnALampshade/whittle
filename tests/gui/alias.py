# SPDX-License-Identifier: GPL-3.0-or-later
"""Imports one package under another name. The GUI checks run Whittle as an
installed extension (bl_ext.<repository>.whittle), while the checks and the
screenshot stage they build on import it as `whittle`: with the alias, those
imports give the installed extension's own modules, never a second copy
from the repository.

Under the alias, sys.modules holds stand-ins with no __file__ that pass every
attribute on to the real module. Blender lists a module from an
extension's folder under any name but bl_ext's as a policy violation in the
Preferences; the stand-ins keep the checks from causing one there. Stdlib
only."""

import importlib
import importlib.abc
import importlib.util
import sys
import types


class _Stand(types.ModuleType):
    """A module's stand-in under the alias."""

    def __init__(self, name: str, real):
        super().__init__(name)
        types.ModuleType.__setattr__(self, "_real", real)

    def __getattr__(self, attr):
        # Where the real module was loaded from stays its own; its __path__
        # is passed on, so its submodules import under the alias.
        if attr in ("__file__", "__cached__"):
            raise AttributeError(attr)
        return getattr(self._real, attr)

    def __setattr__(self, attr, value):
        if attr.startswith("__") and attr.endswith("__"):
            # The import system describing the stand-in itself.
            types.ModuleType.__setattr__(self, attr, value)
        elif not isinstance(value, _Stand):
            # A stand-in linked as a submodule is skipped: the real
            # submodule is linked to the real package already.
            setattr(self._real, attr, value)


class Alias(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """`from name.x import y` gives target.x's y, the same object."""

    def __init__(self, name: str, target: str):
        self.name = name
        self.target = target

    def _ours(self, fullname: str) -> bool:
        return fullname == self.name or fullname.startswith(self.name + ".")

    def find_spec(self, fullname, path=None, target=None):
        return importlib.util.spec_from_loader(fullname, self) if self._ours(fullname) else None

    def create_module(self, spec):
        real = importlib.import_module(self.target + spec.name[len(self.name):])
        return _Stand(spec.name, real)

    def exec_module(self, module):
        pass

    def install(self) -> "Alias":
        """First in line, so the repository's package on sys.path is never
        found under the name. Refuses when the name was already imported."""
        taken = sorted(m for m in sys.modules if self._ours(m))
        if taken:
            raise RuntimeError(f"{self.name} was imported before the alias: {', '.join(taken)}")
        sys.meta_path.insert(0, self)
        return self

    def remove(self) -> None:
        if self in sys.meta_path:
            sys.meta_path.remove(self)
        for name in [m for m in sys.modules if self._ours(m)]:
            del sys.modules[name]
