# SPDX-License-Identifier: GPL-3.0-or-later
"""The Claude models a chat can run on: reading model ids into families and
versions, the list the model menu draws ("Opus 5.5", then the older ones by
family) and the cache of what the account offers. Stdlib only, so the agent
tests cover it; addon/models.py does the Blender side.

Where the list comes from (architecture §15): every agent session reports
the models the bundled CLI offers (its initialize response), plus the
Models API's list when an API key is set. Blender keeps the last report in
<user dir>/models.json; the bundled KNOWN list fills in whatever no report
named, so the menu works before the agent ever ran and offline."""

import re
import time
from dataclasses import dataclass

from . import formats

CACHE_FORMAT = "whittle.models"
CACHE_NAME = "models.json"
DEFAULT_MODEL = "claude-opus-5-5"
# The menu's family order; other families follow by name.
FAMILIES = ("opus", "sonnet", "haiku", "fable")
# Served models as of this release, newest first in each family. A report
# from the agent adds any newer one, so a new model needs no update.
KNOWN = (
    "claude-opus-5-5", "claude-opus-5", "claude-opus-4-8", "claude-opus-4-7", "claude-opus-4-6",
    "claude-opus-4-5",
    "claude-sonnet-5-5", "claude-sonnet-5", "claude-sonnet-4-6", "claude-sonnet-4-5",
    "claude-haiku-5-5", "claude-haiku-4-5",
    "claude-fable-5-1", "claude-fable-5",
)

# claude-opus-5-5, claude-opus-5, claude-opus-4-5-20251101, claude-sonnet-4-20250514
_NEW_STYLE = re.compile(r"^claude-(?P<family>[a-z]+)-(?P<major>\d+)(?:-(?P<minor>\d{1,2}))?"
                        r"(?:-(?P<date>\d{8}))?$")
# claude-3-5-haiku-20241022, claude-3-opus-20240229
_OLD_STYLE = re.compile(r"^claude-(?P<major>\d+)(?:-(?P<minor>\d{1,2}))?-(?P<family>[a-z]+)"
                        r"(?:-(?P<date>\d{8}))?$")


@dataclass(frozen=True)
class Model:
    id: str
    family: str
    version: tuple[int, int]
    # A dated snapshot's date (yyyymmdd); "" for an alias.
    date: str = ""

    @property
    def name(self) -> str:
        """"Opus 5.5", "Sonnet 5", "Haiku 4.5"."""
        major, minor = self.version
        return f"{self.family.title()} {major}.{minor}" if minor else f"{self.family.title()} {major}"

    @property
    def full_name(self) -> str:
        return f"Claude {self.name}"


def parse(model_id: str) -> Model | None:
    """A model id as family and version; None for an id that is not one
    (an alias like "opus", a [1m] variant, a custom endpoint's name)."""
    text = (model_id or "").strip()
    match = _NEW_STYLE.match(text) or _OLD_STYLE.match(text)
    if match is None or match["family"] in ("v", "instant"):
        return None
    return Model(id=text, family=match["family"], version=(int(match["major"]), int(match["minor"] or 0)),
                 date=match["date"] or "")


def short_name(model_id: str) -> str:
    """What the composer's model button says: "Opus 5.5", or the id itself
    for one Whittle cannot read."""
    text = (model_id or "").strip() or DEFAULT_MODEL
    found = parse(text)
    return found.name if found is not None else text


def _family_key(family: str) -> tuple:
    return (FAMILIES.index(family), "") if family in FAMILIES else (len(FAMILIES), family)


@dataclass
class Catalog:
    """Every model the menu offers, by family (in FAMILIES order, then by
    name), each family newest first."""
    families: dict[str, list[Model]]
    # Where the list came from: "api" (the Models API), "cli" (the CLI's
    # own list, when the Models API could not be reached), or "" for the
    # bundled list alone; and when, in seconds.
    source: str = ""
    fetched: float = 0.0

    def latest(self) -> list[Model]:
        """The newest model of each family: the menu's first rows."""
        return [models[0] for models in self.families.values() if models]

    def older(self) -> dict[str, list[Model]]:
        """The rest of each family, for the Older Models submenu."""
        return {family: models[1:] for family, models in self.families.items() if len(models) > 1}

    def find(self, model_id: str) -> Model | None:
        for models in self.families.values():
            for model in models:
                if model.id == model_id:
                    return model
        return None


def catalog(ids, *, source: str = "", fetched: float = 0.0, known=KNOWN) -> Catalog:
    """The menu's models from the ids an account reported and the bundled
    ones. Ids Whittle cannot read are left out, and a dated snapshot is left
    out when its alias (same family and version) is there."""
    found: dict[tuple[str, tuple[int, int]], Model] = {}
    for model_id in [*ids, *known]:
        model = parse(model_id)
        if model is None:
            continue
        key = (model.family, model.version)
        have = found.get(key)
        # The alias wins over a snapshot, and the newest snapshot over older ones.
        if have is None or (have.date and (not model.date or model.date > have.date)):
            found[key] = model
    families: dict[str, list[Model]] = {}
    for model in found.values():
        families.setdefault(model.family, []).append(model)
    ordered = {family: sorted(families[family], key=lambda m: m.version, reverse=True)
               for family in sorted(families, key=_family_key)}
    return Catalog(families=ordered, source=source, fetched=fetched)


# -- what the agent reports ------------------------------------------------------

def ids_from_server_info(info) -> list[str]:
    """The model ids in the CLI's initialize response: each row's
    resolvedModel (an alias row like "opus" names the id it stands for),
    else its value when that is an id."""
    rows = (info or {}).get("models") if isinstance(info, dict) else None
    out = []
    for row in rows or []:
        if not isinstance(row, dict) or row.get("disabled"):
            continue
        for key in ("resolvedModel", "value"):
            value = row.get(key)
            if isinstance(value, str) and parse(value) is not None:
                out.append(value)
                break
    return list(dict.fromkeys(out))


def ids_from_models_api(pages) -> list[str]:
    """The ids in the Models API's pages (GET /v1/models: {"data": [{"id"}]})."""
    out = []
    for page in pages:
        for row in (page or {}).get("data") or []:
            if isinstance(row, dict) and isinstance(row.get("id"), str):
                out.append(row["id"])
    return list(dict.fromkeys(out))


# -- the cache --------------------------------------------------------------------

def read_cache(path) -> tuple[list[str], str, float]:
    """(ids, source, fetched) from the cache; nothing when it is missing or
    cannot be read."""
    try:
        obj = formats.read_json(path)
        formats._check_header(obj, str(path), CACHE_FORMAT)
        formats._check(obj, str(path), {"source": str, "fetched": (int, float), "models": list})
    except formats.FormatError:
        return [], "", 0.0
    ids = [m for m in obj["models"] if isinstance(m, str)]
    return ids, obj["source"], float(obj["fetched"])


def write_cache(path, ids, source: str, fetched: float | None = None) -> None:
    formats.write_json_atomic(path, {"format": CACHE_FORMAT, "version": 1, "source": source,
                                     "fetched": time.time() if fetched is None else fetched,
                                     "models": list(dict.fromkeys(ids))})


def load(path) -> Catalog:
    ids, source, fetched = read_cache(path)
    return catalog(ids, source=source, fetched=fetched)
