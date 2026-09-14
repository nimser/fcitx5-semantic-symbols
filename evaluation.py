"""Paired, offline retrieval evaluation and fail-closed description release gates."""

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import statistics
import time

from descriptions import digest, read_json

ROOT = Path(__file__).resolve().parent


def load_cases(path):
    cases = read_json(path)
    ids, queries = set(), set()
    for case in cases:
        if case["id"] in ids or case["query"].casefold() in queries:
            raise ValueError("Duplicate benchmark ID or query")
        ids.add(case["id"])
        queries.add(case["query"].casefold())
        if case["split"] not in {"dev", "heldout"} or not case["expected"] or not case["query"].strip():
            raise ValueError("Invalid benchmark case")
    if not {"dev", "heldout"} <= {case["split"] for case in cases}:
        raise ValueError("Both development and held-out cases are required")
    return cases


def measure(engine, cases, repeats=3):
    known = {row["glyph"] for row in engine.entries}
    rows = []
    engine.search("warmup", 28)
    for case in cases:
        if not set(case["expected"]) <= known:
            raise ValueError(f"Unknown expected glyph: {case['id']}")
        times = []
        for _ in range(repeats):
            started = time.perf_counter()
            results = engine.search(case["query"], 28)
            times.append((time.perf_counter() - started) * 1000)
        glyphs = [row["glyph"] for row in results]
        rank = next((i + 1 for i, glyph in enumerate(glyphs) if glyph in case["expected"]), None)
        rows.append({**case, "rank": rank, "results": glyphs, "latency_ms": statistics.median(times)})
    return rows


def metrics(rows):
    if not rows:
        raise ValueError("Empty evaluation slice")
    latencies = sorted(row["latency_ms"] for row in rows)
    return {
        "count": len(rows),
        "mrr28": sum(1 / row["rank"] if row["rank"] else 0 for row in rows) / len(rows),
        **{f"recall{k}": sum(row["rank"] is not None and row["rank"] <= k for row in rows) / len(rows)
           for k in (1, 7, 28)},
        "p95_ms": latencies[math.ceil(0.95 * len(latencies)) - 1],
    }


def release_gate(baseline, candidate, reviewed):
    reasons = []
    if not reviewed:
        reasons.append("Redistribution review missing")
    if [row["id"] for row in baseline] != [row["id"] for row in candidate]:
        raise ValueError("Benchmark cases do not match")
    for old, new in zip(baseline, candidate):
        if (new["rank"] or 29) > (old["rank"] or 29):
            reasons.append(f"Rank regression: {old['id']} ({old['rank']} -> {new['rank']})")
    old = metrics([row for row in baseline if row["split"] == "heldout"])
    new = metrics([row for row in candidate if row["split"] == "heldout"])
    if new["mrr28"] < old["mrr28"] + 0.02:
        reasons.append("Held-out MRR@28 improvement below 0.02")
    for category in {row["category"] for row in baseline}:
        before = metrics([row for row in baseline if row["category"] == category])
        after = metrics([row for row in candidate if row["category"] == category])
        if after["mrr28"] < before["mrr28"]:
            reasons.append(f"Category regression: {category}")
    before, after = metrics(baseline), metrics(candidate)
    if after["p95_ms"] > 50 or after["p95_ms"] > before["p95_ms"] * 1.5 + 2:
        reasons.append("Query latency exceeds 50ms or paired baseline allowance")
    return {"passed": not reasons, "reasons": reasons}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=ROOT / "benchmarks/queries.json")
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    from search import MODEL, MODEL_REVISION, Search

    cases = load_cases(args.cases)
    baseline = Search(prepare=True, descriptions=False, offline=True)
    baseline_rows = measure(baseline, cases)
    report = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "benchmark_sha256": digest(cases),
        "model": MODEL, "model_revision": MODEL_REVISION,
        "code_sha256": digest({name: (ROOT / name).read_text() for name in
                               ("search.py", "descriptions.py", "evaluation.py", "uv.lock")}),
        "baseline_catalogue_sha256": baseline.catalogue_sha256,
        "baseline": {"metrics": metrics(baseline_rows), "queries": baseline_rows},
        "gate": {"passed": False, "reasons": ["No candidate supplied"]},
    }
    if args.candidate:
        candidate = Search(prepare=True, descriptions=args.candidate, offline=True, release=False)
        rows = measure(candidate, cases)
        report["candidate"] = {"description_sha256": candidate.description_sha256,
                               "catalogue_sha256": candidate.catalogue_sha256,
                               "metrics": metrics(rows), "queries": rows}
        report["gate"] = release_gate(baseline_rows, rows,
                                     candidate.bundle["redistribution"]["status"] == "reviewed")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"baseline": report["baseline"]["metrics"], "gate": report["gate"]}, indent=2))
    if args.candidate and not report["gate"]["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
