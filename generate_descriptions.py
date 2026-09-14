"""Generate description candidates with a local model; resumable, endpoint-local."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import queue
import re
import threading
import urllib.parse
import urllib.request

from descriptions import MAX_CHARS, SCHEMA, read_json

LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}


def local_endpoint(value):
    host = urllib.parse.urlparse(value).hostname
    if host not in LOCAL_HOSTS:
        raise argparse.ArgumentTypeError(f"Refusing a non-local endpoint: {host}")
    return value


def extract(content):
    """Models answer in prose often enough that losing the glyph over it is silly."""
    content = content.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    braced = re.search(r"\{.*\}", content, re.S)
    for candidate in filter(None, (content, braced.group(0) if braced else None)):
        try:
            return json.loads(candidate)["description"]
        except (json.JSONDecodeError, KeyError, TypeError):
            continue
    return content


def ask(endpoint, model, prompt, row, timeout=180):
    facts = "\n".join(f"{key}: {value if isinstance(value, str) else ', '.join(value)}"
                      for key, value in row["facts"].items())
    body = json.dumps({
        "model": model, "temperature": 0.2, "max_tokens": 260,
        "response_format": {"type": "json_object"},
        "messages": [{"role": "system", "content": prompt},
                     {"role": "user", "content": f"Character U+{ord(row['glyph'][0]):04X}\n{facts}"}],
    }).encode()
    request = urllib.request.Request(endpoint, body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as reply:
        payload = json.load(reply)
    text = " ".join(extract(payload["choices"][0]["message"]["content"]).split())
    if not text or len(text) > MAX_CHARS:
        raise ValueError(f"Unusable description of {len(text)} characters")
    return text, payload["timings"]["predicted_n"]


def generate(inputs, output, endpoint, model, workers, limit=None):
    prompt = (inputs / "prompt.txt").read_text(encoding="utf-8")
    rows = [json.loads(line) for line in (inputs / "catalogue.jsonl").read_text(encoding="utf-8").splitlines()]
    done = set()
    if output.exists():
        done = {json.loads(line)["glyph"] for line in output.read_text(encoding="utf-8").splitlines() if line}
    pending = [row for row in rows if row["glyph"] not in done][:limit]
    print(f"{len(done)} done, {len(pending)} to generate, {workers} workers")

    work, lock, counters = queue.Queue(), threading.Lock(), {"ok": 0, "failed": 0, "tokens": 0}
    for row in pending:
        work.put(row)

    def run():
        with output.open("a", encoding="utf-8") as stream:
            while True:
                try:
                    row = work.get_nowait()
                except queue.Empty:
                    return
                for attempt in range(3):
                    try:
                        text, tokens = ask(endpoint, model, prompt, row)
                        break
                    except Exception as error:  # noqa: BLE001 - a single glyph must never stop the batch
                        text, tokens, failure = None, 0, error
                with lock:
                    if text is None:
                        counters["failed"] += 1
                        print(f"  {row['glyph']} failed: {failure}")
                    else:
                        stream.write(json.dumps({"glyph": row["glyph"], "description": text},
                                                ensure_ascii=False) + "\n")
                        stream.flush()
                        counters["ok"] += 1
                        counters["tokens"] += tokens
                        if counters["ok"] % 200 == 0:
                            print(f"  {counters['ok'] + len(done)}/{len(rows)}")

    threads = [threading.Thread(target=run) for _ in range(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    print(f"generated {counters['ok']}, failed {counters['failed']}, {counters['tokens']} tokens")
    return counters


def bundle(inputs, generated, output, model, model_file, version):
    manifest = read_json(inputs / "input-manifest.json")
    rows = [json.loads(line) for line in generated.read_text(encoding="utf-8").splitlines() if line]
    seen, unique = set(), []
    for row in rows:  # A resumed run may have written a glyph twice; keep the last answer.
        if row["glyph"] in seen:
            unique = [kept for kept in unique if kept["glyph"] != row["glyph"]]
        seen.add(row["glyph"])
        unique.append(row)
    payload = {
        "schema_version": SCHEMA,
        "version": version,
        "catalogue_sha256": manifest["catalogue_sha256"],
        "provenance": {
            "provider": "local llama.cpp server",
            "model": model,
            "revision": hashlib.sha256(Path(model_file).read_bytes()).hexdigest() if model_file else "unknown",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "prompt_sha256": manifest["prompt_sha256"],
            "parameters": {"temperature": 0.2, "max_tokens": 260, "response_format": "json_object"},
            "sources": manifest["sources"],
        },
        "redistribution": {
            "license": "unreviewed",
            "terms_url": "https://github.com/nimser/fcitx5-semantic-symbols/blob/main/DESCRIPTIONS.md",
            "status": "pending",
        },
        "entries": unique,
    }
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{len(unique)} descriptions written to {output}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", type=Path)
    parser.add_argument("--generated", type=Path, required=True, help="Resumable JSONL of answers")
    parser.add_argument("--endpoint", type=local_endpoint, default="http://127.0.0.1:8077/v1/chat/completions")
    parser.add_argument("--model", default="local")
    parser.add_argument("--model-file", help="Weights to hash into the provenance record")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--bundle", type=Path, help="Assemble a candidate bundle and stop")
    parser.add_argument("--version", default="0.1.0")
    arguments = parser.parse_args()
    if arguments.bundle:
        bundle(arguments.inputs, arguments.generated, arguments.bundle,
               arguments.model, arguments.model_file, arguments.version)
        return
    generate(arguments.inputs, arguments.generated, arguments.endpoint,
             arguments.model, arguments.workers, arguments.limit)


if __name__ == "__main__":
    main()
