# SPDX-License-Identifier: GPL-3.0-or-later
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from whittle import models


class ParseTest(unittest.TestCase):
    def test_names(self):
        for model_id, family, version, name in (
                ("claude-opus-5-5", "opus", (5, 5), "Opus 5.5"),
                ("claude-opus-5", "opus", (5, 0), "Opus 5"),
                ("claude-fable-5-1", "fable", (5, 1), "Fable 5.1"),
                ("claude-opus-4-5-20251101", "opus", (4, 5), "Opus 4.5"),
                ("claude-sonnet-4-20250514", "sonnet", (4, 0), "Sonnet 4"),
                ("claude-3-5-haiku-20241022", "haiku", (3, 5), "Haiku 3.5"),
                ("claude-3-opus-20240229", "opus", (3, 0), "Opus 3")):
            with self.subTest(model_id):
                found = models.parse(model_id)
                self.assertEqual((found.family, found.version, found.name), (family, version, name))
        self.assertEqual(models.parse("claude-opus-4-5-20251101").date, "20251101")
        self.assertEqual(models.parse("claude-opus-5-5").full_name, "Claude Opus 5.5")

    def test_ids_that_are_not_versions(self):
        for text in ("opus", "default", "claude-opus-5-5[1m]", "gpt-5", "", "claude-instant-1-2",
                     "claude-v1"):
            with self.subTest(text):
                self.assertIsNone(models.parse(text))

    def test_short_name(self):
        self.assertEqual(models.short_name("claude-haiku-5-5"), "Haiku 5.5")
        self.assertEqual(models.short_name("my-proxy-model"), "my-proxy-model")
        self.assertEqual(models.short_name(""), "Opus 5.5")


class CatalogTest(unittest.TestCase):
    def test_the_bundled_list(self):
        found = models.catalog([])
        self.assertEqual(list(found.families), ["opus", "sonnet", "haiku", "fable"])
        self.assertEqual([m.name for m in found.latest()], ["Opus 5.5", "Sonnet 5.5", "Haiku 5.5", "Fable 5.1"])
        older = found.older()
        self.assertEqual([m.name for m in older["opus"]], ["Opus 5", "Opus 4.8", "Opus 4.7", "Opus 4.6", "Opus 4.5"])
        self.assertEqual([m.name for m in older["fable"]], ["Fable 5"])
        self.assertEqual(found.source, "")
        self.assertIn(models.DEFAULT_MODEL, models.KNOWN)

    def test_a_report_adds_newer_models_and_other_families(self):
        found = models.catalog(["claude-opus-6", "claude-mythos-5-1", "opus", "claude-sonnet-5-5[1m]"],
                               source="cli", fetched=12.0)
        self.assertEqual(found.latest()[0].id, "claude-opus-6")
        self.assertEqual(found.older()["opus"][0].id, "claude-opus-5-5")
        self.assertEqual(list(found.families)[-1], "mythos", "an unknown family comes after the known ones")
        self.assertEqual((found.source, found.fetched), ("cli", 12.0))

    def test_an_alias_wins_over_its_snapshots(self):
        found = models.catalog(["claude-opus-4-5-20251101", "claude-sonnet-4-20250514",
                                "claude-sonnet-4-20250601"], known=("claude-opus-4-5",))
        self.assertEqual(found.find("claude-opus-4-5").id, "claude-opus-4-5")
        self.assertIsNone(found.find("claude-opus-4-5-20251101"))
        self.assertEqual(found.latest()[1].id, "claude-sonnet-4-20250601", "the newest snapshot")


class ReportTest(unittest.TestCase):
    def test_ids_from_server_info(self):
        info = {"models": [
            {"value": "default", "resolvedModel": "claude-opus-5-5"},
            {"value": "claude-sonnet-5-5"},
            {"value": "opus", "resolvedModel": "claude-opus-5-5"},
            {"value": "fable", "resolvedModel": "claude-fable-5-1", "disabled": True},
            {"value": "custom-thing"},
            "junk"]}
        self.assertEqual(models.ids_from_server_info(info), ["claude-opus-5-5", "claude-sonnet-5-5"])
        self.assertEqual(models.ids_from_server_info(None), [])
        self.assertEqual(models.ids_from_server_info({"commands": []}), [])

    def test_ids_from_models_api(self):
        pages = [{"data": [{"id": "claude-opus-5-5"}, {"id": "claude-opus-4-6"}]},
                 {"data": [{"id": "claude-opus-5-5"}, {"nope": 1}]}, {}]
        self.assertEqual(models.ids_from_models_api(pages), ["claude-opus-5-5", "claude-opus-4-6"])


class CacheTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.mkdtemp(prefix="whittle-models-")
        self.addCleanup(shutil.rmtree, folder, True)
        self.path = Path(folder) / models.CACHE_NAME

    def test_round_trip(self):
        models.write_cache(self.path, ["claude-opus-6", "claude-opus-6"], "api", fetched=100.0)
        self.assertEqual(models.read_cache(self.path), (["claude-opus-6"], "api", 100.0))
        found = models.load(self.path)
        self.assertEqual((found.latest()[0].id, found.source, found.fetched), ("claude-opus-6", "api", 100.0))

    def test_a_missing_or_bad_cache_is_the_bundled_list(self):
        self.assertEqual(models.read_cache(self.path), ([], "", 0.0))
        self.path.write_text(json.dumps({"format": "other", "version": 1}))
        self.assertEqual(models.read_cache(self.path), ([], "", 0.0))
        self.path.write_text("{not json")
        found = models.load(self.path)
        self.assertEqual(found.latest()[0].id, models.DEFAULT_MODEL)


if __name__ == "__main__":
    unittest.main()
