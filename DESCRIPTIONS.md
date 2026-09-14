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
`benchmarks/human-preferences.json` records individual human picks as tiered
preference signals; the same no-tuning rule applies to them, and they never
gate a release. Collect more with `python benchmarks/rate.py`, which walks
`prompts-to-rate.json`, shows the current results for contrast and accepts
answers like `🧊💔🥶 > 🩵 ~ 🥶`. Raters change their minds: a new answer for a
phrase moves the old one into `history` instead of overwriting it. Three
ratings are far too few to conclude anything; treat them as examples of the
kind of judgement the pilot must respect, not as a target to hit.
The exporter reads only catalogue glyphs and labels, not benchmark queries.

With the pinned embedding model already cached:

```sh
python evaluation.py --output /tmp/baseline.json
python prepare_descriptions.py /tmp/description-inputs
```

The baseline command never downloads a model. Its report records every rank,
result list, median of three warm query timings, model revision, benchmark hash,
and code/lockfile hash. Reindexing is excluded from query latency.

## 2. Generate a grounded bundle with a local model

Generation runs against a local llama.cpp server; nothing is sent to a provider
and no account or budget is required. A 14B instruct model at Q4 answers about
80 glyphs a minute on an iGPU with Vulkan, so the full catalogue takes roughly
an hour and a half; a 7B on CPU works too, only slower. The model is needed
only to build the bundle. Installing it is unaffected: users get the 67 MB
embedding model plus a small JSON.

```sh
python prepare_descriptions.py /tmp/description-inputs
llama-server -m <model>.gguf -ngl 99 -c 16384 -np 8 --host 127.0.0.1 --port 8077
python generate_descriptions.py /tmp/description-inputs --generated /tmp/generated.jsonl --workers 8
python generate_descriptions.py /tmp/description-inputs --generated /tmp/generated.jsonl \
    --bundle /tmp/candidate.json --model <name> --model-file <model>.gguf --version 1.0.0
```

The exporter carries authoritative facts with every glyph, because an
ungrounded model invents them: it described U+2318 as a hand pointing at a
location rather than the Command key, and gave U+21CC a vague mapping instead
of chemical equilibrium. Each entry therefore ships its official name, the
Unicode NamesList aliases and usage notes, the CLDR English keywords, and the
hand-written meaning where one exists, marked as authoritative. Both source
files are pinned to a version and hashed into the manifest. No benchmark query
and no human rating is ever sent to the model.

Only public character data leaves the process, and only to `127.0.0.1`: the
generator refuses a non-local endpoint. Answers are appended to a JSONL file as
they arrive, so an interrupted run resumes where it stopped, and a glyph that
fails three times is reported and skipped rather than stopping the batch.
Review a sample covering confusable mathematical symbols, flags, skin tones and
colloquial emoji before trusting a full run.

The bundle written by `--bundle` records the provider, model name, a hash of
the weights, the prompt hash, the sampling parameters and every upstream source
with its licence. Redistribution starts as `pending`: a human has to review the
model licence and the Unicode terms and record the evidence before any release.

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
