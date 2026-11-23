"""Record the hashes of every version of the default prompts/curricula ever committed.

Run this BEFORE committing a change to parlera/defaults/prompts or parlera/defaults/curricula:

    python3 tools/update_default_hashes.py

At startup, a user's copy whose hash matches an old default was never edited, so it is
upgraded automatically to the new default. Copies the user edited are kept untouched.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULTS = "parlera/defaults"
OUT = ROOT / DEFAULTS / "known_hashes.json"


def sha(data: bytes) -> str:
    return hashlib.sha256(data.replace(b"\r\n", b"\n").strip()).hexdigest()


def git(*args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True).stdout


def main() -> None:
    known: dict[str, set[str]] = {}
    if OUT.exists():
        known = {k: set(v) for k, v in json.loads(OUT.read_text()).items()}
    commits = git("log", "--format=%H", "--", f"{DEFAULTS}/prompts", f"{DEFAULTS}/curricula").decode().split()
    for c in commits:
        files = git("ls-tree", "-r", "--name-only", c, "--", f"{DEFAULTS}/prompts", f"{DEFAULTS}/curricula").decode().split()
        for f in files:
            rel = f[len(DEFAULTS) + 1:]
            known.setdefault(rel, set()).add(sha(git("show", f"{c}:{f}")))
    OUT.write_text(json.dumps({k: sorted(v) for k, v in sorted(known.items())}, indent=1) + "\n")
    print(f"{OUT.relative_to(ROOT)}: {sum(len(v) for v in known.values())} hashes for {len(known)} files")


if __name__ == "__main__":
    main()
