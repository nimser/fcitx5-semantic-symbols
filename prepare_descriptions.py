"""Export the catalogue with authoritative facts for a separate generation job."""

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import re
import shutil
import unicodedata
import urllib.request

from descriptions import catalogue_digest
from search import EXPLANATIONS, catalogue

CLDR_VERSION = "47.0.0"
SOURCES = {
    "NamesList.txt": {
        "url": f"https://www.unicode.org/Public/{unicodedata.unidata_version}/ucd/NamesList.txt",
        "name": "Unicode Character Database NamesList",
        "version": unicodedata.unidata_version,
        "license": "Unicode-3.0",
    },
    "cldr-annotations.json": {
        "url": ("https://raw.githubusercontent.com/unicode-org/cldr-json/"
                f"{CLDR_VERSION}/cldr-json/cldr-annotations-full/annotations/en/annotations.json"),
        "name": "CLDR English emoji annotations",
        "version": CLDR_VERSION,
        "license": "Unicode-3.0",
    },
    "cldr-annotations-derived.json": {
        "url": ("https://raw.githubusercontent.com/unicode-org/cldr-json/"
                f"{CLDR_VERSION}/cldr-json/cldr-annotations-derived-full/annotationsDerived/en/annotations.json"),
        "name": "CLDR English derived emoji annotations",
        "version": CLDR_VERSION,
        "license": "Unicode-3.0",
    },
}
PROMPT = """You write the text that sits behind a Unicode character in an offline emoji and symbol search.
Someone types what they mean in plain words and your text is what gets matched.

Write one paragraph of at most 350 characters: what the character shows, what people mean by it, and for
technical characters the fields that use it (mathematics, chemistry, physics, logic, music, chess,
typography, finance). Finish with a short comma-separated list of words someone would actually type.

The supplied facts are authoritative: use them, never contradict them, and never describe a different
character. Keep direction, negation and comparison exact. Describe emoji usage without claiming a
universal meaning, and never infer traits from flags, skin tone, gender or disability.

Plain prose, no bullet lists, no quoting of these instructions, no mention of searching or of glyphs.
Answer as JSON: {"description": "..."}
"""


def fetch(directory, filename, offline=False):
    target = directory / filename
    if not target.exists():
        cached = Path.home() / ".cache/fcitx5-semantic-symbols/sources" / filename
        if cached.exists():
            shutil.copyfile(cached, target)
        elif offline:
            raise SystemExit(f"Missing source and --offline given: {filename}")
        else:
            cached.parent.mkdir(parents=True, exist_ok=True)
            with urllib.request.urlopen(SOURCES[filename]["url"], timeout=120) as reply:
                cached.write_bytes(reply.read())
            shutil.copyfile(cached, target)
    return target


def annotations(path):
    """Aliases and usage notes the Unicode database keeps out of the character name."""
    found, code = {}, None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if re.match(r"^[0-9A-F]{4,6}\t", line):
            code = int(line.split("\t")[0], 16)
        elif code is not None and line.startswith("\t") and line[1:2] in {"=", "*"}:
            found.setdefault(code, []).append(line.strip()[2:].strip())
    return found


def facts(entry, notes, keywords):
    known = {"official_name": entry["label"]}
    alias = notes.get(ord(entry["glyph"][0]), [])[:4]
    if alias:
        known["unicode_annotations"] = alias
    words = keywords.get(entry["glyph"], {}).get("default", [])[:14]
    if words:
        known["cldr_keywords"] = words
    if entry["glyph"] in EXPLANATIONS:
        known["verified_meaning"] = EXPLANATIONS[entry["glyph"]]
    return known


def export(directory, offline=False):
    directory.mkdir(parents=True, exist_ok=True)
    entries = catalogue()
    notes = annotations(fetch(directory, "NamesList.txt", offline))
    keywords = {}
    for name in ("cldr-annotations.json", "cldr-annotations-derived.json"):
        payload = json.loads(fetch(directory, name, offline).read_text(encoding="utf-8"))
        root = payload.get("annotations") or payload["annotationsDerived"]
        keywords.update(root["annotations"])
    (directory / "prompt.txt").write_text(PROMPT, encoding="utf-8")
    with (directory / "catalogue.jsonl").open("w", encoding="utf-8") as stream:
        for entry in entries:
            row = {"glyph": entry["glyph"], "label": entry["label"], "facts": facts(entry, notes, keywords)}
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    manifest = {
        "schema_version": 1,
        "catalogue_sha256": catalogue_digest(entries),
        "prompt_sha256": hashlib.sha256(PROMPT.encode()).hexdigest(),
        "count": len(entries),
        "grounded": sum(1 for entry in entries if facts(entry, notes, keywords).keys() - {"official_name"}),
        "emoji_package_version": importlib.metadata.version("emoji"),
        "unicode_version": unicodedata.unidata_version,
        "sources": [
            {**{key: value for key, value in SOURCES[name].items() if key != "url"},
             "url": SOURCES[name]["url"],
             "sha256": hashlib.sha256((directory / name).read_bytes()).hexdigest()}
            for name in SOURCES
        ],
        "redistribution_status": "pending",
    }
    (directory / "input-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--offline", action="store_true", help="Use cached sources only")
    arguments = parser.parse_args()
    export(arguments.output, arguments.offline)
