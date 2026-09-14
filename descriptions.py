"""Versioned, offline description bundles; no generation or network code."""

import hashlib
import json
from pathlib import Path
import re
import unicodedata

SCHEMA = 1
MAX_CHARS = 1000
MAX_TOKENS = 256


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def catalogue_digest(entries):
    return digest(sorted((row["glyph"], row["label"]) for row in entries))


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=_unique)


def _text(value, field, maximum=MAX_CHARS):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"Invalid {field}")
    if any(unicodedata.category(c) == "Cc" for c in value):
        raise ValueError(f"Control character in {field}")
    return value


def _object(value, field):
    if not isinstance(value, dict):
        raise ValueError(f"Expected object: {field}")
    return value


def load_bundle(path, entries, release=False):
    bundle = _object(read_json(path), "bundle")
    if type(bundle.get("schema_version")) is not int or bundle["schema_version"] != SCHEMA:
        raise ValueError("Unsupported description schema")
    if not re.fullmatch(r"\d+\.\d+\.\d+", str(bundle.get("version", ""))):
        raise ValueError("Description version must be major.minor.patch")
    if bundle.get("catalogue_sha256") != catalogue_digest(entries):
        raise ValueError("Description catalogue mismatch")
    provenance = _object(bundle.get("provenance"), "provenance")
    for field in ("provider", "model", "revision", "generated_at"):
        _text(provenance.get(field), f"provenance.{field}")
    if not re.fullmatch(r"[0-9a-f]{64}", str(provenance.get("prompt_sha256", ""))):
        raise ValueError("Missing prompt hash")
    if not isinstance(provenance.get("parameters"), dict):
        raise ValueError("Missing generation parameters")
    sources = provenance.get("sources", [])
    if not isinstance(sources, list) or not sources:
        raise ValueError("Missing source provenance")
    for source in sources:
        _object(source, "source")
        for field in ("name", "version", "license", "url"):
            _text(source.get(field), f"source.{field}")
    redistribution = _object(bundle.get("redistribution"), "redistribution")
    for field in ("license", "terms_url"):
        _text(redistribution.get(field), f"redistribution.{field}")
    if redistribution.get("status") not in {"pending", "reviewed"}:
        raise ValueError("Invalid redistribution status")
    if redistribution["status"] == "reviewed":
        for field in ("reviewed_by", "reviewed_at", "evidence"):
            _text(redistribution.get(field), f"redistribution.{field}")
    elif release:
        raise ValueError("Redistribution review required before release")
    rows = bundle.get("entries")
    if not isinstance(rows, list):
        raise ValueError("Missing descriptions")
    descriptions = {}
    for row in rows:
        _object(row, "entry")
        glyph = _text(row.get("glyph"), "glyph", 64)
        if glyph in descriptions:
            raise ValueError(f"Duplicate glyph: {glyph}")
        descriptions[glyph] = _text(row.get("description"), "description")
    known = {row["glyph"] for row in entries}
    if set(descriptions) != known:
        raise ValueError(f"Coverage mismatch: {len(known - descriptions.keys())} missing, "
                         f"{len(descriptions.keys() - known)} unknown")
    enriched = [{**row, "text": descriptions[row["glyph"]]} for row in entries]
    return enriched, bundle


def check_token_lengths(entries, tokenizer):
    tokenizer.no_truncation()
    for row in entries:
        count = len(tokenizer.encode(row["text"]).ids)
        if count > MAX_TOKENS:
            raise ValueError(f"{row['glyph']}: {count} tokens exceeds {MAX_TOKENS}; shorten description")
