"""Collect human glyph preferences; revisions keep the older answer in history."""

import argparse
from datetime import date
import json
from pathlib import Path
import unicodedata

HERE = Path(__file__).resolve().parent
PREFERENCES = HERE / "human-preferences.json"
PROMPTS = HERE / "prompts-to-rate.json"
COLUMNS = 7


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_tiers(text):
    """'AB > C ~ D' becomes [['AB'], ['C', 'D']]; a combination is typed unspaced."""
    tiers, tier, dangling = [], [], False
    for token in text.replace("≈", " ").replace("~", " ").replace(",", " ").replace(">", " > ").split():
        if token == ">":
            if not tier:
                raise ValueError("A tier is empty in front of '>'")
            tiers.append(tier)
            tier = []
            dangling = True
            continue
        dangling = False
        if any(ord(char) < 0x80 or unicodedata.category(char) in {"Cc", "Zs"} for char in token):
            raise ValueError(f"Not a glyph: {token!r}")
        tier.append(token)
    if dangling:
        raise ValueError("A tier is empty after '>'")
    if tier:
        tiers.append(tier)
    if not tiers:
        raise ValueError("No glyph given")
    return tiers


def apply_rating(preferences, prompt, tiers, rater="owner", today=None):
    today = today or date.today().isoformat()
    for rating in preferences["ratings"]:
        if rating["prompt"] == prompt and rating["rater"] == rater:
            if rating["tiers"] == tiers:
                return rating
            rating.setdefault("history", []).insert(0, {"date": rating["date"], "tiers": rating["tiers"]})
            rating["tiers"] = tiers
            rating["date"] = today
            return rating
    rating = {"prompt": prompt, "tiers": tiers, "rater": rater, "date": today,
              "accept_better": True, "history": []}
    preferences["ratings"].append(rating)
    return rating


def candidates(prompt, limit=28):
    import sys

    sys.path.insert(0, str(HERE.parent))
    from search import Search

    global _SEARCH
    try:
        _SEARCH
    except NameError:
        _SEARCH = Search(descriptions=False, offline=True)
    return [row["glyph"] for row in _SEARCH.search(prompt, limit)]


def show(prompt, glyphs):
    print(f"\n{prompt}")
    for start in range(0, len(glyphs), COLUMNS):
        print("  " + "  ".join(glyphs[start:start + COLUMNS]))
    print("  Answer with your own glyphs: combinations unspaced, '>' better than, '~' equal.")
    print("  Enter skips, 'q' quits.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rater", default="owner")
    parser.add_argument("--prompt", help="Rate one phrase instead of the queue")
    parser.add_argument("--no-candidates", action="store_true", help="Do not show current results")
    arguments = parser.parse_args()

    preferences = read(PREFERENCES)
    queue = [arguments.prompt] if arguments.prompt else [row["prompt"] for row in read(PROMPTS)["prompts"]]
    rated = {(row["prompt"], row["rater"]) for row in preferences["ratings"]}
    for prompt in queue:
        if not arguments.prompt and (prompt, arguments.rater) in rated:
            continue
        show(prompt, [] if arguments.no_candidates else candidates(prompt))
        try:
            answer = input("> ").strip()
        except EOFError:
            break
        if answer.lower() == "q":
            break
        if not answer:
            continue
        try:
            tiers = parse_tiers(answer)
        except ValueError as error:
            print(f"  {error}; skipped")
            continue
        apply_rating(preferences, prompt, tiers, arguments.rater)
        write(PREFERENCES, preferences)
        print(f"  Stored {tiers}")
    print(f"{len(preferences['ratings'])} ratings in {PREFERENCES.name}")


if __name__ == "__main__":
    main()
