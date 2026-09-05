"""Record one real conversion so the website can replay it.

The engine is Python, so it cannot run on GitHub Pages. Rather than show
screenshots and claim the interface works, the site ships the interface itself
with the answers from a genuine run of the demo melody: the same payloads the
engine would send, produced by the engine, so the demo cannot drift from the
product by being written separately.

Nothing copyrighted goes in here — the demo melody is original to this project.

    engine/.venv/Scripts/python.exe scripts/build_demo_fixture.py
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine"))

OUT_DIR = ROOT / "site" / "public" / "demo"
MODES = ("melody", "balanced", "chordal", "virtuoso")


def _scrub(node: object) -> None:
    """Take this machine out of the recording before it is published.

    A recorded session carries whatever the engine reported here: the GPU in
    this box, the absolute path the demo audio was read from. None of it is
    true for a visitor, and the hardware is nobody else's business.
    """
    if isinstance(node, dict):
        for key, value in list(node.items()):
            if key == "device" and isinstance(value, str) and value:
                node[key] = "a CUDA GPU"
            elif key in {"path", "outputPath", "sourcePath", "logDir", "cacheDir"} and isinstance(
                value, str
            ):
                node[key] = Path(value).name if value else value
            else:
                _scrub(value)
    elif isinstance(node, list):
        for item in node:
            _scrub(item)


def main() -> int:
    from shawzify_engine.audio.ffmpeg import find_ffmpeg
    from shawzify_engine.demo import write_demo_files
    from shawzify_engine.server import METHODS

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    demo_dir = ROOT / "assets" / "demo"
    demo_dir.mkdir(parents=True, exist_ok=True)
    if not (demo_dir / "demo.wav").exists():
        write_demo_files(demo_dir)
    source_audio = demo_dir / "demo.wav"

    print("analysing", source_audio.name)
    source = METHODS["analyze"](
        {"path": str(source_audio), "options": {}, "useStems": False, "requestId": 1}, 1
    )
    source_id = source["sourceId"]

    arrangements = {}
    for mode in MODES:
        print("arranging as", mode)
        arrangements[mode] = METHODS["arrange"](
            {"sourceId": source_id, "options": {"mode": mode}, "requestId": 2}, 2
        )

    fixture = {
        "recordedFrom": source_audio.name,
        "environment": METHODS["environment"]({}, 3),
        "instrument": METHODS["instrument"]({"variant": "dax"}, 4),
        "keymap": METHODS["keymap"]({}, 5),
        "source": source,
        "arrangements": arrangements,
        "structure": METHODS["structure"]({"sourceId": source_id}, 6),
        "shawzins": METHODS["recommendShawzin"]({"sourceId": source_id}, 7),
        "sources": METHODS["sources"]({}, 8),
        "spotify": METHODS["spotifyCredentials"]({}, 9),
    }

    # A short preview so the play button is real too. MP3 keeps the page light;
    # without FFmpeg the WAV is used as-is rather than shipping nothing.
    preview = METHODS["preview"]({"sourceId": source_id}, 8)
    wav = Path(preview["path"])
    target = OUT_DIR / "preview.mp3"
    ffmpeg = find_ffmpeg()
    if ffmpeg.available and ffmpeg.ffmpeg:
        subprocess.run(
            [ffmpeg.ffmpeg, "-y", "-loglevel", "error", "-i", str(wav), "-b:a", "96k", str(target)],
            check=True,
            stdin=subprocess.DEVNULL,
        )
    else:
        target = OUT_DIR / "preview.wav"
        shutil.copyfile(wav, target)
    fixture["preview"] = {
        "file": target.name,
        "durationSeconds": preview["durationSeconds"],
        "sampleRate": preview["sampleRate"],
    }

    _scrub(fixture)

    payload = OUT_DIR / "session.json"
    payload.write_text(json.dumps(fixture, separators=(",", ":"), default=str), encoding="utf-8")

    print()
    print(f"  {payload.relative_to(ROOT)}  {payload.stat().st_size / 1024:.0f} KB")
    print(f"  {target.relative_to(ROOT)}  {target.stat().st_size / 1024:.0f} KB")
    print(f"  {source['noteCount']} source notes, {len(MODES)} arrangements")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
