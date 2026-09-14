"""Preference collection keeps answers parseable, revisable and non-binding."""

import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "benchmarks"))
from rate import PREFERENCES, PROMPTS, apply_rating, parse_tiers, read


class ParseTests(unittest.TestCase):
    def test_tiers_and_combinations(self):
        self.assertEqual(parse_tiers("🧊💔🥶 > 🩵 ~ 🥶"), [["🧊💔🥶"], ["🩵", "🥶"]])
        self.assertEqual(parse_tiers("🤣>🥲"), [["🤣"], ["🥲"]])
        self.assertEqual(parse_tiers("🕺🍻🦥, 💃🍹👯"), [["🕺🍻🦥", "💃🍹👯"]])

    def test_rejects_prose_and_empty_tiers(self):
        for answer in ("", "no idea", "🤣 >", "> 🤣", "🤣 or 🥲"):
            with self.subTest(answer=answer), self.assertRaises(ValueError):
                parse_tiers(answer)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.preferences = {"schema_version": 2, "ratings": []}

    def test_revision_keeps_the_previous_answer(self):
        apply_rating(self.preferences, "cold heart", [["🧊💔"]], today="2026-01-01")
        apply_rating(self.preferences, "cold heart", [["🧊💔🥶"]], today="2026-02-02")
        rating = self.preferences["ratings"][0]
        self.assertEqual(len(self.preferences["ratings"]), 1)
        self.assertEqual(rating["tiers"], [["🧊💔🥶"]])
        self.assertEqual(rating["history"], [{"date": "2026-01-01", "tiers": [["🧊💔"]]}])
        self.assertTrue(rating["accept_better"])

    def test_unchanged_answer_adds_no_history(self):
        apply_rating(self.preferences, "happy tears", [["🤣"]], today="2026-01-01")
        apply_rating(self.preferences, "happy tears", [["🤣"]], today="2026-02-02")
        self.assertEqual(self.preferences["ratings"][0]["history"], [])

    def test_raters_are_kept_apart(self):
        apply_rating(self.preferences, "happy tears", [["🤣"]], rater="owner")
        apply_rating(self.preferences, "happy tears", [["🥲"]], rater="guest")
        self.assertEqual(len(self.preferences["ratings"]), 2)


class StoredFileTests(unittest.TestCase):
    def test_file_shape(self):
        preferences = read(PREFERENCES)
        self.assertEqual(preferences["schema_version"], 2)
        for rating in preferences["ratings"]:
            self.assertTrue(rating["prompt"] and rating["rater"] and rating["date"])
            versions = [rating["tiers"]] + [entry["tiers"] for entry in rating["history"]]
            for tiers in versions:
                self.assertTrue(tiers)
                for tier in tiers:
                    self.assertTrue(tier)
                    self.assertTrue(all(isinstance(glyph, str) and glyph.strip() for glyph in tier))

    def test_queue_offers_more_than_the_rated_phrases(self):
        pending = {row["prompt"] for row in read(PROMPTS)["prompts"]}
        rated = {row["prompt"] for row in read(PREFERENCES)["ratings"]}
        self.assertGreaterEqual(len(pending - rated), 20)

    def test_preferences_never_gate_a_release(self):
        sources = [(ROOT / name).read_text() for name in ("evaluation.py", "release_descriptions.py", "search.py")]
        self.assertFalse([text for text in sources if "human-preferences" in text])


if __name__ == "__main__":
    unittest.main()
