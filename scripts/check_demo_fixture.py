"""Fail if the website's demo replays an engine that no longer exists.

The demo on the landing page is a recording of a real conversion, so that the
published interface cannot be written separately from the product. That holds
only while somebody re-records it. It did not: the fixture sat at arrangement
engine 1.0.0 through four changes to the arrangement search, so the demo showed
visitors a scale choice the engine had stopped making.

Nothing catches that by reading the code, so this compares the version stamped
into the recording against the version the engine reports now.

    engine/.venv/Scripts/python.exe scripts/check_demo_fixture.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine"))

FIXTURE = ROOT / "site" / "public" / "demo" / "session.json"

from shawzify_engine.version import (  # noqa: E402
    ARRANGEMENT_ENGINE_VERSION,
    ENCODER_VERSION,
    TRANSCRIPTION_VERSION,
)

EXPECTED = {
    "arrangement": ARRANGEMENT_ENGINE_VERSION,
    "encoder": ENCODER_VERSION,
    "transcription": TRANSCRIPTION_VERSION,
}


def main() -> int:
    if not FIXTURE.exists():
        print(f"no demo fixture at {FIXTURE.relative_to(ROOT)}")
        return 1

    session = json.loads(FIXTURE.read_text(encoding="utf-8"))
    arrangements = session.get("arrangements") or {}
    if not arrangements:
        print("the demo fixture has no arrangements in it")
        return 1

    stale: list[str] = []
    for preset, arrangement in arrangements.items():
        recorded = (arrangement.get("report") or {}).get("engineVersions") or {}
        for stage, expected in EXPECTED.items():
            found = recorded.get(stage)
            if found is not None and found != expected:
                stale.append(f"  {preset}: {stage} recorded {found}, engine is now {expected}")

    if stale:
        print("The demo on the website was recorded by an older engine:")
        print("\n".join(stale))
        print("\nRe-record it, then commit site/public/demo:")
        print("  engine/.venv/Scripts/python.exe scripts/build_demo_fixture.py")
        return 1

    versions = ", ".join(f"{k} {v}" for k, v in EXPECTED.items())
    print(f"demo fixture matches the current engine ({versions})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
