"""Build a source release only after offline paired evaluation passes."""

import argparse
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parent
FILES = ("addon.cpp", "search.py", "descriptions.py", "install.sh", "pyproject.toml",
         "uv.lock", "README.md", "LICENSE", "DESCRIPTIONS.md", "evaluation.py",
         "prepare_descriptions.py", "release_descriptions.py", "benchmarks/queries.json",
         "tests/test_description_gates.py", "tests/test_semantic_symbols.py",
         "tests/semantic_symbols_integration.cpp", "demo/README.md", "demo/record.sh",
         "demo/demo.gif", "demo/demo.mp4", "demo/screenshot.png")


def package(candidate, output):
    if output.exists():
        raise ValueError("Refusing to overwrite a release archive")
    with tempfile.TemporaryDirectory(prefix="semantic-symbols-release-") as directory:
        stage = Path(directory)
        for name in FILES:
            target = stage / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, target)
        frozen = stage / "descriptions.json"
        shutil.copyfile(candidate, frozen)
        report = stage / "evaluation.json"
        subprocess.run([sys.executable, "-B", str(stage / "evaluation.py"),
                        "--candidate", str(frozen), "--output", str(report)], check=True, timeout=1200)
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix(output.suffix + ".tmp")
        try:
            with tarfile.open(temporary, "w:gz") as archive:
                for name in FILES:
                    archive.add(stage / name, arcname=f"fcitx5-semantic-symbols/{name}")
                archive.add(frozen, arcname="fcitx5-semantic-symbols/descriptions.json")
                archive.add(report, arcname="fcitx5-semantic-symbols/evaluation.json")
            temporary.replace(output)
        finally:
            temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    package(args.candidate, args.output)
