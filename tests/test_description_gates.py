"""Description and release-gate tests without downloads or desktop access."""

import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from descriptions import catalogue_digest, check_token_lengths, digest, load_bundle, read_json
from evaluation import load_cases, metrics, release_gate


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "descriptions.json"
        self.entries = [{"glyph": "⇌", "label": "rightleft harpoons", "text": "equilibrium"}]
        self.bundle = {
            "schema_version": 1, "version": "1.0.0",
            "catalogue_sha256": catalogue_digest(self.entries),
            "provenance": {"provider": "test", "model": "fixture", "revision": "1",
                           "generated_at": "2026-01-01T00:00:00Z", "prompt_sha256": "a" * 64,
                           "parameters": {"temperature": 0},
                           "sources": [{"name": "fixture", "version": "1", "license": "MIT",
                                        "url": "https://example.org/fixture"}]},
            "redistribution": {"license": "MIT", "terms_url": "https://example.org/terms",
                               "status": "pending"},
            "entries": [{"glyph": "⇌", "description": "A reversible chemical reaction at equilibrium."}],
        }

    def load(self, release=False):
        self.path.write_text(json.dumps(self.bundle))
        return load_bundle(self.path, self.entries, release=release)

    def test_valid_bundle_preserves_labels(self):
        enriched, _ = self.load()
        self.assertEqual(enriched[0]["label"], self.entries[0]["label"])
        self.assertEqual(enriched[0]["text"], self.bundle["entries"][0]["description"])
        self.assertNotEqual(digest(enriched), digest(self.entries))

    def test_release_requires_review_evidence(self):
        with self.assertRaisesRegex(ValueError, "review required"):
            self.load(release=True)
        self.bundle["redistribution"]["status"] = "reviewed"
        with self.assertRaises(ValueError):
            self.load(release=True)
        self.bundle["redistribution"].update(reviewed_by="Fixture reviewer", reviewed_at="2026-01-01",
                                             evidence="Fixture-only approval; not production permission.")
        self.load(release=True)

    def test_bad_bundles_fail_closed(self):
        changes = [
            lambda b: b.update(schema_version=2),
            lambda b: b.update(schema_version=True),
            lambda b: b.update(provenance=[]),
            lambda b: b.update(redistribution=[]),
            lambda b: b.update(version="latest"),
            lambda b: b.update(catalogue_sha256="b" * 64),
            lambda b: b["provenance"].pop("model"),
            lambda b: b["provenance"].update(sources=[]),
            lambda b: b["provenance"].update(prompt_sha256="unknown"),
            lambda b: b.update(entries=[]),
            lambda b: b.update(entries=[None]),
            lambda b: b["entries"].append(b["entries"][0]),
            lambda b: b["entries"][0].update(glyph="?"),
            lambda b: b["entries"][0].update(description="a" * 1001),
            lambda b: b["entries"][0].update(description=""),
            lambda b: b["entries"][0].update(description="hidden\ncontrol"),
        ]
        original = copy.deepcopy(self.bundle)
        for change in changes:
            with self.subTest(change=change):
                self.bundle = copy.deepcopy(original)
                change(self.bundle)
                with self.assertRaises(ValueError):
                    self.load()

    @unittest.skipUnless(os.environ.get("SEMANTIC_TEST_PYTHON"), "Prepared model cache required")
    def test_offline_index_rebuild_reopen_and_corruption(self):
        import numpy as np
        import search

        cache = Path(self.directory.name) / "cache"
        cache.mkdir()
        (cache / "models").symlink_to(search.STATE / "models", target_is_directory=True)
        self.load()
        with patch.object(search, "STATE", cache), patch.object(search, "catalogue", return_value=self.entries), \
             patch("socket.socket.connect", side_effect=AssertionError("Network forbidden")):
            first = search.Search(prepare=True, descriptions=self.path, offline=True, release=False)
            self.assertEqual(first.search("equilibrium")[0]["glyph"], "⇌")
            self.assertEqual(len(list(cache.glob("*.npy"))), 1)
            self.bundle["entries"][0]["description"] += " Reactants and products interconvert."
            self.load()
            second = search.Search(prepare=True, descriptions=self.path, offline=True, release=False)
            self.assertNotEqual(first.catalogue_sha256, second.catalogue_sha256)
            self.assertEqual(len(list(cache.glob("*.npy"))), 2)
            reopened = search.Search(descriptions=self.path, offline=True, release=False)
            np.testing.assert_array_equal(second.vectors, reopened.vectors)
            with self.assertRaisesRegex(ValueError, "review required"):
                search.Search(descriptions=self.path, offline=True)
            for index in cache.glob("*.npy"):
                np.save(index, np.zeros((1, 2)))
            with self.assertRaisesRegex(RuntimeError, "Invalid index"):
                search.Search(descriptions=self.path, offline=True, release=False)
            repaired = search.Search(prepare=True, descriptions=self.path, offline=True, release=False)
            self.assertEqual(repaired.vectors.shape, (1, 384))
            self.assertFalse(list(cache.glob("*.tmp")))

    def test_duplicate_json_keys(self):
        self.path.write_text('{"entries": [], "entries": []}')
        with self.assertRaisesRegex(ValueError, "Duplicate JSON"):
            read_json(self.path)

    def test_token_limit_disables_silent_truncation(self):
        class Tokenizer:
            truncated = True

            def no_truncation(self):
                self.truncated = False

            def encode(self, text):
                self.ids = list(range(257 if not self.truncated else 256))
                return self

        with self.assertRaisesRegex(ValueError, "257 tokens"):
            check_token_lengths(self.entries, Tokenizer())


class EvaluationTests(unittest.TestCase):
    def rows(self, rank=2):
        return [{"id": "1", "split": "heldout", "category": "symbols", "rank": rank, "latency_ms": 5},
                {"id": "2", "split": "dev", "category": "emoji", "rank": rank, "latency_ms": 5}]

    def test_metrics(self):
        result = metrics(self.rows())
        self.assertEqual(result["mrr28"], 0.5)
        self.assertEqual(result["recall1"], 0)
        self.assertEqual(result["recall7"], 1)

    def test_improvement_passes(self):
        self.assertTrue(release_gate(self.rows(2), self.rows(1), True)["passed"])

    def test_no_gain_missing_review_rank_and_latency_regressions_fail(self):
        self.assertFalse(release_gate(self.rows(), self.rows(), True)["passed"])
        self.assertFalse(release_gate(self.rows(2), self.rows(1), False)["passed"])
        self.assertFalse(release_gate(self.rows(1), self.rows(2), True)["passed"])
        slow = self.rows(1)
        slow[0]["latency_ms"] = 100
        self.assertFalse(release_gate(self.rows(2), slow, True)["passed"])

    def test_missing_result_ranks_last(self):
        self.assertFalse(release_gate(self.rows(28), self.rows(None), True)["passed"])

    def test_query_split_is_disjoint(self):
        cases = load_cases(ROOT / "benchmarks/queries.json")
        self.assertEqual(len(cases), 36)
        self.assertEqual(sum(row["split"] == "heldout" for row in cases), 24)


class PackageTests(unittest.TestCase):
    def test_failed_evaluation_never_produces_release(self):
        from release_descriptions import package

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = root / "candidate.json"
            candidate.write_text("{}")
            with patch("release_descriptions.subprocess.run", side_effect=subprocess.CalledProcessError(1, "gate")):
                with self.assertRaises(subprocess.CalledProcessError):
                    package(candidate, root / "release.tar.gz")
            self.assertFalse((root / "release.tar.gz").exists())

    def test_passed_evaluation_packages_offline_inputs(self):
        from release_descriptions import package

        def passed(command, **kwargs):
            Path(command[-1]).write_text('{"gate":{"passed":true}}')

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = root / "candidate.json"
            candidate.write_text("{}")
            output = root / "release.tar.gz"
            with patch("release_descriptions.subprocess.run", side_effect=passed):
                package(candidate, output)
            with tarfile.open(output) as archive:
                names = archive.getnames()
                self.assertIn("fcitx5-semantic-symbols/descriptions.json", names)
                self.assertIn("fcitx5-semantic-symbols/descriptions.py", names)
                self.assertIn("fcitx5-semantic-symbols/evaluation.json", names)
            with self.assertRaisesRegex(ValueError, "overwrite"):
                package(candidate, output)


class RecorderTests(unittest.TestCase):
    def test_shell_syntax(self):
        subprocess.run(["bash", "-n", str(ROOT / "demo/record.sh")], check=True)

    def test_stubborn_recorder_is_killed(self):
        script = (ROOT / "demo/record.sh").read_text()
        function = "stop_recorder() {" + script.split("stop_recorder() {", 1)[1].split("\ncleanup()", 1)[0]
        probe = function + '''
python3 -c 'import signal,time; signal.signal(signal.SIGINT, signal.SIG_IGN); signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)' &
recorder=$!
sleep 0.2
stop_recorder
[ -z "$recorder" ]
'''
        subprocess.run(["bash", "-c", probe], check=True, timeout=10)


if __name__ == "__main__":
    unittest.main()
