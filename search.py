"""Local semantic search over emoji and visible Unicode symbols."""

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import socket
import tempfile
import unicodedata

from descriptions import check_token_lengths, digest, load_bundle

MODEL = "BAAI/bge-small-en-v1.5"
MODEL_REPO = "qdrant/bge-small-en-v1.5-onnx-q"
MODEL_REVISION = "52398278842ec682c6f32300af41344b1c0b0bb2"
STATE = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "fcitx5-semantic-symbols"
EXPLANATIONS = {
    "🤔": "Thinking carefully, pondering a question, feeling uncertain or skeptical.",
    "🤷": "Shrugging with uncertainty, ignorance, indifference or lack of an answer.",
    "😕": "Feeling confused, puzzled, uncertain or disappointed.",
    "🫤": "Feeling doubtful, conflicted, ambivalent or dissatisfied.",
    "❓": "A question, doubt, uncertainty or request for clarification.",
    "🤨": "Skepticism, suspicion, disbelief or questioning a claim.",
    "😐": "A neutral expression, indifference or lack of enthusiasm.",
    "😑": "Being unimpressed, annoyed, exasperated or speechless.",
    "🙄": "Rolling eyes in annoyance, disbelief or impatience.",
    "😬": "An awkward, tense, uncomfortable or embarrassing situation.",
    "😅": "Nervous laughter, embarrassment or relief after a close call.",
    "😂": "Laughing so hard that tears flow; something is hilarious.",
    "🤣": "Uncontrollable laughter, rolling on the floor laughing.",
    "😀": "Happiness, joy, pleasure, delight and a cheerful greeting.",
    "😃": "Excitement, enthusiasm, delight and joyful anticipation.",
    "🥳": "Celebrating an achievement, birthday, victory or happy occasion at a party.",
    "🎉": "Celebration, congratulations, achievement and a successful happy occasion.",
    "🎊": "Festive celebration, congratulations and confetti at a party.",
    "🏆": "Winning a competition, achievement, excellence and a successful victory.",
    "👏": "Applause, congratulations, appreciation and praise for an achievement.",
    "🙌": "Celebrating good news, a victory or successful achievement with raised hands.",
    "👍": "Approval, agreement, encouragement, well done and a positive response.",
    "👎": "Disapproval, disagreement, rejection and a negative response.",
    "🙏": "Gratitude, thanks, a polite request, hope or prayer.",
    "🤝": "Agreement, cooperation, partnership and making a deal.",
    "💪": "Strength, determination, resilience and encouragement to persevere.",
    "🫶": "Love, affection, appreciation and heartfelt support.",
    "❤️": "Love, affection, caring and emotional warmth.",
    "💔": "Heartbreak, emotional pain, sadness and lost love.",
    "🥰": "Feeling loved, affectionate, cherished and warmly happy.",
    "😍": "Adoration, attraction and loving something wonderful.",
    "🥹": "Being emotionally moved, grateful or holding back happy tears.",
    "🥺": "Pleading, vulnerability, longing and asking for sympathy.",
    "😢": "Feeling sad, hurt, disappointed and quietly crying.",
    "😭": "Sobbing, intense sadness, grief or overwhelming emotion.",
    "😔": "Feeling down, regretful, dejected or disappointed.",
    "😞": "Disappointment, discouragement and unmet expectations.",
    "😡": "Intense anger, rage, frustration and outrage.",
    "😤": "Frustration, indignation, determination and huffing in anger.",
    "🤯": "Astonishment, amazement and having one's mind blown.",
    "😮": "Surprise, amazement and astonishment.",
    "😱": "Shock, horror, panic and extreme fear.",
    "😨": "Feeling scared, afraid, anxious or alarmed.",
    "😰": "Anxiety, stress, worry and nervous apprehension.",
    "😌": "Relief, calm, peace, relaxation and contentment.",
    "😴": "Sleeping, resting, tiredness and taking a nap.",
    "🥱": "Yawning, sleepiness, fatigue, boredom and needing rest.",
    "😫": "Exhaustion, frustration, being overwhelmed and needing rest.",
    "😮‍💨": "Sighing with relief, exhaustion, disappointment or fatigue.",
    "☕": "Coffee, a warm drink, a pause to relax and a refreshing rest.",
    "🏖️": "A vacation, holiday, beach relaxation and time away from work.",
    "🧘": "Meditation, mindfulness, relaxation, inner peace and calm.",
    "⏸️": "Pause an activity temporarily, stop for rest and resume later.",
    "🚀": "Launching a project, rapid progress, growth and ambitious exploration.",
    "🔥": "Fire, heat, something excellent, exciting, popular or impressive.",
    "💡": "An idea, insight, inspiration, discovery or creative solution.",
    "🔍": "Searching, investigating, inspecting and examining details.",
    "🐛": "A bug, software defect, error or crawling insect.",
    "🔧": "Repairing, fixing, configuring and maintaining equipment or software.",
    "🚧": "Construction, unfinished work, maintenance and work in progress.",
    "⚠️": "Warning of danger, caution, a risk or an important problem.",
    "🚨": "An urgent emergency, alarm, danger or critical alert.",
    "🛑": "Stop, halt an action, a prohibition or a firm boundary.",
    "🔒": "Security, privacy, protection, locked access and confidentiality.",
    "🔓": "Unlocked access, permission, openness and removal of restrictions.",
    "🔄": "Refreshing, reloading, repeating, synchronizing and starting again.",
    "⏳": "Waiting, time passing, pending work and patience.",
    "💤": "Sleep, rest, inactivity and taking a nap.",
    "✅": "A task is complete, successful, verified, correct or approved.",
    "❌": "An error, failure, rejection, cancellation or incorrect answer.",
    "✓": "yes correct done completed success check mark",
    "✔": "yes correct done completed success heavy check mark",
    "☑": "checked checkbox selected task complete",
    "✗": "no wrong incorrect failed cross mark",
    "✘": "no wrong incorrect failed heavy cross mark",
    "↔": "goes both ways bidirectional left and right arrow",
    "⇄": "goes both ways exchange swap opposite directions",
    "⇌": "reversible reaction equilibrium balance both directions",
    "→": "leads to next step right arrow implies",
    "←": "go back previous left arrow",
    "↑": "increase upward arrow",
    "↓": "decrease downward arrow",
    "⇒": "therefore implies leads to logical implication",
    "⇔": "if and only if equivalent logical equivalence",
    "≈": "approximately equal roughly about almost the same",
    "≠": "not equal different unequal",
    "≡": "identical equivalent congruent",
    "≤": "less than or equal at most upper bound",
    "≥": "greater than or equal at least lower bound",
    "±": "plus or minus uncertainty tolerance error margin",
    "∞": "infinity forever unlimited endless",
    "∅": "empty set nothing no elements",
    "∈": "belongs to member of element of set",
    "∉": "does not belong to not a member of set",
    "⊆": "subset included in contained within",
    "∪": "union combine sets either one or the other",
    "∩": "intersection overlap common members both",
    "∴": "therefore hence conclusion",
    "∵": "because since reason",
    "∀": "for all every universal quantifier",
    "∃": "there exists some existential quantifier",
    "¬": "not negation opposite logical denial",
    "∧": "logical and both conjunction",
    "∨": "logical or either disjunction",
    "×": "multiply multiplication times product",
    "÷": "divide division ratio",
    "°": "degrees temperature angle",
    "‰": "per thousand proportion rate",
    "•": "bullet point list item",
    "…": "ellipsis omitted text continuation more",
    "—": "em dash sentence break aside",
    "†": "dagger footnote deceased",
    "※": "reference mark note attention",
    "★": "star favourite favorite rating highlight",
    "☆": "empty outline star favourite rating",
    "♡": "outline heart love affection",
    "⚠": "warning caution danger attention",
    "☐": "unchecked checkbox empty task pending",
    "⏎": "return enter newline keyboard key",
    "⌘": "command key keyboard mac modifier",
    "⌥": "option alt key keyboard modifier",
    "⇧": "shift key keyboard modifier",
    "⎋": "escape key keyboard cancel",
}


def catalogue():
    import emoji

    entries = {}
    for glyph, data in emoji.EMOJI_DATA.items():
        if data.get("status") != emoji.STATUS["fully_qualified"]:
            continue
        label = data["en"].strip(":").replace("_", " ")
        aliases = " ".join(data.get("alias", [])).replace("_", " ").replace(":", "")
        entries[glyph] = {"glyph": glyph, "label": label, "text": f"{label} {aliases}"}
    for code in [*range(0x20, 0x100), *range(0x2000, 0x2C00)]:
        glyph = chr(code)
        if unicodedata.category(glyph) not in {"Sm", "Sc", "So", "Sk", "Pd", "Ps", "Pe", "Pi", "Pf", "Po"}:
            continue
        name = unicodedata.name(glyph, "").lower()
        if not name or glyph in entries or unicodedata.combining(glyph):
            continue
        kind = "Mathematical symbol: " if unicodedata.category(glyph) == "Sm" else "Unicode symbol: "
        entries[glyph] = {"glyph": glyph, "label": name, "text": kind + name}
    for glyph, text in EXPLANATIONS.items():
        if glyph in entries:
            entries[glyph]["text"] = text
    return sorted(entries.values(), key=lambda item: item["glyph"])


def load_vectors(path, np, count):
    try:
        vectors = np.load(path, allow_pickle=False)
        if vectors.shape != (count, 384) or not np.isfinite(vectors).all():
            raise ValueError("Invalid vector dimensions or values")
        return vectors
    except (OSError, ValueError, EOFError) as error:
        raise RuntimeError("Invalid index: rerun fcitx5-semantic-setup") from error


class Search:
    def __init__(self, prepare=False, descriptions=None, offline=False, release=True):
        import numpy as np
        from fastembed import TextEmbedding
        from huggingface_hub import snapshot_download

        self.np = np
        self.entries = catalogue()
        self.bundle = None
        if descriptions is None:
            bundled = Path(__file__).with_name("descriptions.json")
            descriptions = bundled if bundled.exists() else False
        if descriptions is not False:
            self.entries, self.bundle = load_bundle(descriptions, self.entries, release=release)
        self.description_sha256 = digest(self.bundle) if self.bundle else None
        self.catalogue_sha256 = digest(self.entries)
        fingerprint = hashlib.sha256(json.dumps([MODEL, MODEL_REVISION, self.entries], ensure_ascii=False).encode()).hexdigest()[:16]
        STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
        index = STATE / f"index-{fingerprint}.npy"
        model_path = snapshot_download(
            MODEL_REPO, revision=MODEL_REVISION, cache_dir=STATE / "models", local_files_only=offline or not prepare,
            allow_patterns=["config.json", "model_optimized.onnx", "special_tokens_map.json", "tokenizer_config.json", "tokenizer.json"],
        )
        if self.bundle:
            from tokenizers import Tokenizer

            check_token_lengths(self.entries, Tokenizer.from_file(str(Path(model_path) / "tokenizer.json")))
        self.model = TextEmbedding(MODEL, specific_model_path=model_path, threads=2, local_files_only=True)
        if not index.exists() and not prepare:
            raise RuntimeError("Index missing: run fcitx5-semantic-setup first")
        if prepare:
            with index.with_suffix(".lock").open("w") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                rebuild = not index.exists()
                if not rebuild:
                    try:
                        load_vectors(index, np, len(self.entries))
                    except RuntimeError:
                        rebuild = True
                if rebuild:
                    vectors = np.array(list(self.model.embed([entry["text"] for entry in self.entries])), dtype=np.float32)
                    vectors /= np.maximum(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-12)
                    temporary = None
                    try:
                        with tempfile.NamedTemporaryFile(dir=STATE, suffix=".tmp", delete=False) as stream:
                            temporary = Path(stream.name)
                            np.save(stream, vectors, allow_pickle=False)
                        temporary.replace(index)
                    finally:
                        if temporary:
                            temporary.unlink(missing_ok=True)
        self.vectors = load_vectors(index, np, len(self.entries))

    def search(self, query, limit=28):
        query = " ".join(query.split())[:256]
        if not query:
            return []
        vector = next(self.model.query_embed(query))
        vector /= max(float(self.np.linalg.norm(vector)), 1e-12)
        scores = self.vectors @ vector
        folded = query.casefold()
        for i, item in enumerate(self.entries):
            if folded == item["label"].casefold() or query == item["glyph"]:
                scores[i] += 1
        results, seen = [], set()
        for i in self.np.argsort(-scores, kind="stable"):
            item = self.entries[i]
            family = "".join(c for c in item["glyph"] if not 0x1F3FB <= ord(c) <= 0x1F3FF)
            if family in seen:
                continue
            seen.add(family)
            results.append(item)
            if len(results) == limit:
                break
        return results


def serve(search):
    runtime = Path(os.environ["XDG_RUNTIME_DIR"]) / "fcitx5-semantic-symbols"
    runtime.mkdir(mode=0o700, exist_ok=True)
    if runtime.stat().st_uid != os.getuid() or runtime.stat().st_mode & 0o077:
        raise RuntimeError("Unsafe runtime directory permissions")
    path = runtime / "search.sock"
    with (runtime / "server.lock").open("w") as lock, socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        path.unlink(missing_ok=True)
        server.bind(str(path))
        path.chmod(0o600)
        server.listen(8)
        while True:
            connection, _ = server.accept()
            with connection:
                connection.settimeout(1)
                try:
                    data = bytearray()
                    while b"\n" not in data and len(data) <= 1024:
                        part = connection.recv(1025 - len(data))
                        if not part:
                            break
                        data.extend(part)
                    if len(data) > 1024 or b"\n" not in data:
                        continue
                    query = bytes(data).split(b"\n", 1)[0].decode("utf-8")
                    results = search.search(query)
                    reply = "".join(f"{row['glyph']}\t{row['label']}\n" for row in results)
                    connection.sendall(reply.encode())
                except (OSError, UnicodeError, ValueError):
                    continue


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--query")
    parser.add_argument("--descriptions", type=Path)
    parser.add_argument("--baseline", action="store_true", help="Ignore bundled descriptions")
    parser.add_argument("--offline", action="store_true", help="Reindex using cached model files only")
    args = parser.parse_args()
    if args.baseline and args.descriptions:
        parser.error("--baseline and --descriptions are mutually exclusive")
    search = Search(prepare=args.prepare, descriptions=False if args.baseline else args.descriptions,
                    offline=args.offline)
    if args.query:
        print(json.dumps(search.search(args.query), ensure_ascii=False, indent=2))
    elif not args.prepare:
        serve(search)


if __name__ == "__main__":
    main()
