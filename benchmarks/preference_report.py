"""Informational: how baseline and candidate results line up with human picks."""

import argparse
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))


def engines(candidate):
    from search import Search

    baseline = Search(prepare=True, descriptions=False, offline=True)
    return baseline, Search(prepare=True, descriptions=candidate, offline=True, release=False) if candidate else None


def report(candidate=None, rows=7):
    preferences = json.loads((HERE / "human-preferences.json").read_text(encoding="utf-8"))
    baseline, trial = engines(candidate)
    for rating in preferences["ratings"]:
        wanted = [glyph for tier in rating["tiers"] for glyph in tier]
        singles = {glyph for glyph in wanted if len(glyph) <= 4}
        print(f"\n{rating['prompt']}  (wanted: {' > '.join(' ~ '.join(tier) for tier in rating['tiers'])})")
        for name, engine in (("baseline", baseline), ("candidate", trial)):
            if not engine:
                continue
            glyphs = [row["glyph"] for row in engine.search(rating["prompt"], rows)]
            hit = next((f"#{i + 1}" for i, glyph in enumerate(glyphs) if glyph in singles), "absent")
            print(f"  {name:9} {' '.join(glyphs)}   single-glyph pick: {hit}")
    print("\nCombinations cannot appear in these results: the catalogue holds one glyph per entry.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--rows", type=int, default=7)
    arguments = parser.parse_args()
    report(arguments.candidate, arguments.rows)
