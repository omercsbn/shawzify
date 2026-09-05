"""Assert that a `shawzify convert --json` report describes a real conversion.

CI runs this after a conversion so a release cannot ship an engine that
produces a plausible-looking report with nothing playable in it. Kept as a file
rather than a one-liner in the workflow: a shell-quoted Python snippet is
unreadable, and this one is worth reading.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ALPHABET = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/")


def main(path: str) -> int:
    report = json.loads(Path(path).read_text(encoding="utf-8"))

    code = report["code"]
    if len(code) % 3 != 1:
        print(f"song code is {len(code)} characters, which is not 3n+1", file=sys.stderr)
        return 1
    stray = set(code) - ALPHABET
    if stray:
        print(f"song code contains characters outside the alphabet: {sorted(stray)}", file=sys.stderr)
        return 1

    notes = (len(code) - 1) // 3
    after = report["report"]["compatibilityAfter"]["overall"]
    before = report["report"]["compatibilityBefore"]["overall"]
    if notes < 1:
        print("the conversion produced no notes at all", file=sys.stderr)
        return 1
    if after < before:
        print(f"arranging made the piece less playable: {before} -> {after}", file=sys.stderr)
        return 1

    print(f"code: {code[:48]}{'...' if len(code) > 48 else ''}")
    print(f"{notes} notes, compatibility {before:.1f} -> {after:.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "conversion.json"))
