"""Export public catalogue labels for a separate, budgeted generation job."""

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import unicodedata

from descriptions import catalogue_digest
from search import catalogue

PROMPT = """Write one concise English description for every supplied glyph.
Return JSON entries with exactly the supplied glyph and a description string.
Describe literal meaning, common communicative intent and realistic contexts.
For technical symbols preserve mathematical direction, negation and distinctions.
For emoji describe common usage without asserting universal cultural meaning.
Do not infer traits or stereotypes from flags, skin tone, gender or disability.
Do not add glyphs, change Unicode sequences or include instructions to the reader.
Keep each description below 600 characters; an exact tokenizer check follows.
Use only the supplied public glyph and official label. Do not use evaluation queries.
"""


def export(directory):
    entries = catalogue()
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "prompt.txt").write_text(PROMPT)
    with (directory / "catalogue.jsonl").open("w") as stream:
        for row in entries:
            stream.write(json.dumps({key: row[key] for key in ("glyph", "label")}, ensure_ascii=False) + "\n")
    metadata = {
        "schema_version": 1, "catalogue_sha256": catalogue_digest(entries),
        "prompt_sha256": hashlib.sha256(PROMPT.encode()).hexdigest(), "count": len(entries),
        "emoji_package_version": importlib.metadata.version("emoji"),
        "unicode_version": unicodedata.unidata_version,
        "redistribution_status": "pending",
    }
    (directory / "input-manifest.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    export(parser.parse_args().output)
