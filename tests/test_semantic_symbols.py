"""Isolated native-addon tests; optional real-model retrieval tests."""

import os
from pathlib import Path
import shlex
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT


class NativeAddonTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("g++") and shutil.which("pkg-config"), "Fcitx5 build tools required")
    def test_native_input(self):
        flags = shlex.split(subprocess.check_output(
            ["pkg-config", "--cflags", "--libs", "Fcitx5Core", "Fcitx5Module"], text=True))
        with tempfile.TemporaryDirectory(prefix="semantic-symbols-test-") as directory:
            root = Path(directory)
            lib = root / "libsemantic-symbols.so"
            subprocess.run(["g++", "-std=c++20", "-Wall", "-Wextra", "-Werror", "-pthread", "-fPIC", "-shared",
                            str(PROJECT / "addon.cpp"), "-o", str(lib), *flags], check=True)
            binary = root / "integration"
            subprocess.run(["g++", "-std=c++20", "-Wall", "-Wextra", "-Werror", "-pthread",
                            str(Path(__file__).with_name("semantic_symbols_integration.cpp")),
                            "-o", str(binary), *flags], check=True)
            addons = root / "data/fcitx5/addon"
            addons.mkdir(parents=True)
            (addons / "semantic-symbols.conf").write_text(
                "[Addon]\nName=Semantic Symbols\nType=SharedLibrary\nCategory=Module\n"
                f"Library={lib.with_suffix('')}\nOnDemand=False\n[Addon/Dependencies]\n0=core:5.1.22\n")
            (addons / "testfrontend.conf").write_text(
                "[Addon]\nName=Test Frontend\nType=SharedLibrary\nCategory=Frontend\n"
                "Library=libtestfrontend\nOnDemand=False\n")
            runtime = root / "runtime/fcitx5-semantic-symbols"
            runtime.mkdir(parents=True, mode=0o700)
            server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            server.bind(str(runtime / "search.sock"))
            server.listen(8)
            server.settimeout(0.1)
            stop = threading.Event()

            def respond():
                while not stop.is_set():
                    try:
                        connection, _ = server.accept()
                    except socket.timeout:
                        continue
                    with connection:
                        connection.settimeout(1)
                        data = bytearray()
                        while b"\n" not in data:
                            data.extend(connection.recv(1024))
                        query = data.decode().strip()
                        if query == "slow":
                            time.sleep(0.15)
                        glyph = "✓" if query == "check mark" else "∞" if query == "forever" else "?"
                        # One selected glyph plus narrow fillers: two grid lines
                        # and a short third exercise wrapping and xy movement.
                        rows = [f"{glyph}\tresult"] + [f"{i}\tfiller {i}" for i in range(1, 16)]
                        connection.sendall("".join(row + "\n" for row in rows).encode())

            thread = threading.Thread(target=respond)
            thread.start()
            env = {**os.environ, "XDG_CONFIG_HOME": str(root / "config"), "XDG_DATA_HOME": str(root / "data"),
                   "XDG_CACHE_HOME": str(root / "cache"), "XDG_RUNTIME_DIR": str(root / "runtime"),
                   "FCITX_ADDON_DIRS": os.environ.get("FCITX_ADDON_DIRS", "/usr/lib/fcitx5"), "DISPLAY": "", "WAYLAND_DISPLAY": "",
                   "DBUS_SESSION_BUS_ADDRESS": "unix:path=/nonexistent"}
            try:
                subprocess.run([str(binary)], env=env, check=True, timeout=15)
            finally:
                stop.set()
                thread.join(timeout=3)
                server.close()


class RetrievalTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get("SEMANTIC_TEST_PYTHON"), "Set SEMANTIC_TEST_PYTHON to the prepared venv Python")
    def test_semantic_retrieval(self):
        script = '''
import sys, time
sys.path.insert(0, sys.argv[1])
from search import Search, catalogue
s = Search()
checks = {
    "not sure": {"🤔", "🤷", "😕", "❓"},
    "goes both ways": {"↔", "⇄"},
    "roughly the same": {"≈", "≅"},
    "I need a break": {"😫", "⏸️", "💤", "☕"},
    "celebrate our success": {"🎉", "🥳", "🙌"},
    "at most": {"≤"},
    "keep this confidential": {"🔒"},
    "that was a close call": {"😅"},
}
for query, expected in checks.items():
    started = time.monotonic()
    result = s.search(query, 6)
    assert expected.intersection(row["glyph"] for row in result), (query, result)
    print(query, round((time.monotonic() - started) * 1000), "ms", " ".join(row["glyph"] for row in result))
assert s.search("   ") == []
assert s.search("check mark")[0]["label"] == "check mark"
assert any(row["glyph"] == "👩‍💻" for row in catalogue())
assert all(not any(ord(c) < 32 for c in row["glyph"] + row["label"]) for row in catalogue())
'''
        subprocess.run([os.environ["SEMANTIC_TEST_PYTHON"], "-B", "-c", script, str(PROJECT)], check=True, timeout=120)


if __name__ == "__main__":
    unittest.main()
