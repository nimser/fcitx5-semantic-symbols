# Description release gates

Generated descriptions are optional build inputs, never runtime LLM requests.
Without `descriptions.json` beside `search.py`, search uses the hand-written
baseline. An invalid bundled file fails closed rather than silently changing
rankings. `--baseline` explicitly selects the baseline for rollback.

## 1. Freeze evaluation before generation

`benchmarks/queries.json` contains 12 development cases and 24 held-out cases,
covering short emoji queries, ambiguous language and technical symbols. These
are a small initial benchmark, not proof of universal accuracy or unbiased
human relevance judgments. Have a human review the accepted glyphs before
making broad accuracy claims.

Do not send held-out queries to the generator or tune against their results.
If they are used for tuning, retire that split and add new held-out cases.
The exporter reads only catalogue glyphs and labels, not benchmark queries.

With the pinned embedding model already cached:

```sh
python evaluation.py --output /tmp/baseline.json
python prepare_descriptions.py /tmp/description-inputs
```

The baseline command never downloads a model. Its report records every rank,
result list, median of three warm query timings, model revision, benchmark hash,
and code/lockfile hash. Reindexing is excluded from query latency.

## 2. Generate a versioned, attributable bundle

Before calling any provider, verify model access, agree a maximum spend, and
review the provider's output redistribution terms and all source-data licenses.
Record the actual source versions and review evidence; a nonempty license field
is not legal verification. Do not copy competitor descriptions without permission.
Only public catalogue data should leave the machine during generation.

The exporter writes `prompt.txt`, `catalogue.jsonl`, and `input-manifest.json`.
Use resumable, bounded batches; review a sample covering confusable mathematical
symbols, flags, skin tones and colloquial emoji meanings before scaling up.
Do not fabricate provenance or mark a pending review as approved.

The candidate is a JSON object with these fields:

- `schema_version`: `1`.
- `version`: independent data version, e.g. `1.0.0`.
- `catalogue_sha256`: from the exported input manifest.
- `provenance`: `provider`, `model`, `revision`, `generated_at`, `prompt_sha256`
  (SHA-256 of the exact prompt bytes), `parameters` object, and `sources` array.
  Every source records `name`, `version`, `license`, and `url`.
- `redistribution`: `license`, `terms_url`, and `status` (`pending` or `reviewed`).
  A reviewed bundle must also record `reviewed_by`, `reviewed_at`, and `evidence`.
- `entries`: one `{ "glyph": "…", "description": "…" }` per exported glyph.

Preserve exact Unicode sequences, including variation selectors and joiners.
The validator rejects missing/unknown/duplicate glyphs, duplicate JSON keys,
blank text, control characters, missing provenance and unsupported schemas.
It preserves official labels separately for exact-name search and the name
preview; it does not automatically prepend them to embedding text.

## 3. Enforce bounded, offline embedding

Descriptions are limited to 1,000 characters and must fit 256 tokens with the
pinned tokenizer, including special tokens.
Truncation is explicitly disabled during validation; overflow requires editing,
not silent clipping. The prompt asks for less than 600 characters as headroom.

The index key includes the model revision and exact embedded catalogue text.
Changed descriptions create a distinct index. Writes use a per-index lock and
atomic replacement; preparation repairs malformed matrices. Existing baseline
indices remain available for rollback. Runtime never rebuilds an index or
fetches a model. Setup may fetch the pinned model; `--offline --prepare` forbids
that fetch and requires the cached files.

## 4. Compare and package only passing candidates

```sh
python evaluation.py --candidate /tmp/candidate.json --output /tmp/comparison.json
python release_descriptions.py /tmp/candidate.json /tmp/semantic-symbols.tar.gz
```

Evaluation accepts a pending-review candidate for measurement but exits nonzero
unless all release conditions pass:

- Complete catalogue coverage and valid provenance.
- No token overflow.
- Redistribution status reviewed, with reviewer/date/evidence present.
- No individual query's first acceptable rank worsens (missing results rank last).
- Held-out MRR@28 improves by at least 0.02 absolute.
- No category's MRR@28 worsens.
- Candidate p95 query latency is at most 50 ms and at most baseline × 1.5 + 2 ms.

Thresholds are fixed before candidate evaluation; do not lower them just to pass
a candidate. Investigate failures and repeat timing measurements on a quiet
machine rather than accepting noisy results selectively.

Packaging freezes a candidate copy, reruns the gate offline, and includes the
exact bundle and evaluation report with installable sources. It neither uploads
nor tags a release. Install builds the index locally; there is no precomputed
matrix tied to a developer's cache. Review the artifact and app acceptance
before publishing a new minor release. Never move an existing release tag.

No generated catalogue or redistribution approval is included with this tooling.
