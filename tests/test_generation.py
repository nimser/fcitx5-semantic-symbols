"""Grounding export and local generation: offline, resumable, provenance-complete."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import generate_descriptions as generation
import prepare_descriptions as preparation
from descriptions import SCHEMA, load_bundle


class ExportTests(unittest.TestCase):
    def test_facts_stay_authoritative_and_specific(self):
        notes = {ord("⌘"): ["command key (1.0)", "operating system key (ISO 9995-7)"]}
        keywords = {"🥲": {"default": ["grateful", "relieved", "tear"]}}
        command = preparation.facts({"glyph": "⌘", "label": "place of interest sign"}, notes, keywords)
        self.assertEqual(command["unicode_annotations"][0], "command key (1.0)")
        self.assertIn("command key", command["verified_meaning"])
        tear = preparation.facts({"glyph": "🥲", "label": "smiling face with tear"}, notes, keywords)
        self.assertEqual(tear["cldr_keywords"], ["grateful", "relieved", "tear"])
        plain = preparation.facts({"glyph": "⅊", "label": "property line"}, notes, keywords)
        self.assertEqual(list(plain), ["official_name"])

    def test_offline_export_refuses_to_download(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(preparation, "fetch", side_effect=SystemExit("Missing source")):
            with self.assertRaises(SystemExit):
                preparation.export(Path(directory) / "inputs", offline=True)

    def test_sources_are_pinned_to_versions(self):
        for source in preparation.SOURCES.values():
            self.assertIn(source["version"], source["url"])
            self.assertEqual(source["license"], "Unicode-3.0")


class AnswerTests(unittest.TestCase):
    def test_prose_and_fenced_answers_are_recovered(self):
        self.assertEqual(generation.extract('{"description": "A cat."}'), "A cat.")
        self.assertEqual(generation.extract('```json\n{"description": "A cat."}\n```'), "A cat.")
        self.assertEqual(generation.extract('Here it is: {"description": "A cat."}'), "A cat.")
        self.assertEqual(generation.extract("A cat, plainly."), "A cat, plainly.")

    def test_remote_endpoints_are_refused(self):
        generation.local_endpoint("http://127.0.0.1:8077/v1/chat/completions")
        for endpoint in ("https://api.example.com/v1/chat/completions", "http://10.0.0.5:8077/v1"):
            with self.subTest(endpoint=endpoint), self.assertRaises(Exception):
                generation.local_endpoint(endpoint)

    def test_oversized_answers_are_rejected(self):
        with patch.object(generation.urllib.request, "urlopen") as opened:
            opened.return_value.__enter__.return_value = self._reply("x" * 2000)
            with self.assertRaises(ValueError):
                generation.ask("http://127.0.0.1:1/v1", "local", "prompt",
                               {"glyph": "🎉", "facts": {"official_name": "party popper"}})

    @staticmethod
    def _reply(description):
        class Reply:
            def read(self):
                return json.dumps({"choices": [{"message": {"content": json.dumps({"description": description})}}],
                                   "timings": {"predicted_n": 10}}).encode()
        return Reply()


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.inputs = Path(self.directory.name) / "inputs"
        self.inputs.mkdir()
        (self.inputs / "prompt.txt").write_text("Describe it.")
        self.entries = [{"glyph": "🎉", "label": "party popper"}, {"glyph": "⇌", "label": "harpoons"}]
        with (self.inputs / "catalogue.jsonl").open("w") as stream:
            for entry in self.entries:
                stream.write(json.dumps({**entry, "facts": {"official_name": entry["label"]}}) + "\n")
        (self.inputs / "input-manifest.json").write_text(json.dumps({
            "catalogue_sha256": __import__("descriptions").catalogue_digest(self.entries),
            "prompt_sha256": "a" * 64,
            "sources": [{"name": "fixture", "version": "1", "license": "Unicode-3.0", "url": "https://example.org"}],
        }))
        self.generated = Path(self.directory.name) / "generated.jsonl"

    def run_batch(self, answers):
        calls = []

        def fake(endpoint, model, prompt, row, timeout=180):
            calls.append(row["glyph"])
            answer = answers[row["glyph"]]
            if isinstance(answer, Exception):
                raise answer
            return answer, 12

        with patch.object(generation, "ask", fake):
            counters = generation.generate(self.inputs, self.generated, "http://127.0.0.1:1/v1", "local", 1)
        return counters, calls

    def test_failures_never_stop_the_batch(self):
        counters, _ = self.run_batch({"🎉": "A party popper.", "⇌": RuntimeError("model hiccup")})
        self.assertEqual((counters["ok"], counters["failed"]), (1, 1))

    def test_resume_only_asks_for_what_is_missing(self):
        self.run_batch({"🎉": "A party popper.", "⇌": RuntimeError("model hiccup")})
        _, calls = self.run_batch({"⇌": "Reversible reaction at equilibrium."})
        self.assertEqual(calls, ["⇌"])

    def test_bundle_is_loadable_and_marked_unreviewed(self):
        self.run_batch({"🎉": "A party popper.", "⇌": "Reversible reaction at equilibrium."})
        output = Path(self.directory.name) / "candidate.json"
        generation.bundle(self.inputs, self.generated, output, "fixture-model", None, "1.0.0")
        payload = json.loads(output.read_text())
        self.assertEqual(payload["schema_version"], SCHEMA)
        self.assertEqual(payload["redistribution"]["status"], "pending")
        self.assertEqual(payload["provenance"]["sources"][0]["name"], "fixture")
        enriched, _ = load_bundle(output, self.entries)
        self.assertEqual(enriched[0]["text"], "A party popper.")
        with self.assertRaisesRegex(ValueError, "review required"):
            load_bundle(output, self.entries, release=True)

    def test_repeated_glyphs_keep_the_last_answer(self):
        self.generated.write_text('{"glyph": "🎉", "description": "First."}\n'
                                  '{"glyph": "⇌", "description": "Harpoons."}\n'
                                  '{"glyph": "🎉", "description": "Second."}\n')
        output = Path(self.directory.name) / "candidate.json"
        generation.bundle(self.inputs, self.generated, output, "fixture-model", None, "1.0.0")
        entries = json.loads(output.read_text())["entries"]
        self.assertEqual([row["glyph"] for row in entries], ["⇌", "🎉"])
        self.assertEqual(entries[1]["description"], "Second.")


class ShippedArtefactTests(unittest.TestCase):
    def test_no_generated_bundle_is_committed(self):
        self.assertFalse((ROOT / "descriptions.json").exists())

    def test_runtime_never_calls_a_model(self):
        source = (ROOT / "search.py").read_text()
        self.assertNotIn("chat/completions", source)
        self.assertNotIn("generate_descriptions", source)


if __name__ == "__main__":
    unittest.main()
