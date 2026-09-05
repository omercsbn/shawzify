# Development

## Prerequisites

| Tool | Version | Needed for |
| --- | --- | --- |
| Python | 3.10+ (3.12 recommended) | The engine, the CLI, everything musical |
| Node | 18+ | The frontend |
| Rust | 1.77+ | The desktop shell (optional — the engine works without it) |
| FFmpeg | any recent | Compressed audio. `imageio-ffmpeg` supplies one automatically |

`scripts/setup.ps1` handles all of it and is safe to re-run.

Python 3.13+ works for the engine itself, but Demucs and Basic Pitch may not
have wheels yet. `uv` is used when present because it makes creating a 3.12
environment a one-liner regardless of what is on PATH.

## Layout

```
engine/
  shawzify_engine/
    common/           errors, structured logging, progress, cache, path safety
    music/            pitch, events, quantization, phrases, importance, key
    shawzin/          instrument model, song code codec, split, tab
      data/           the authoritative instrument definition (JSON)
    arrangement/      options, scale search, mapping, polyphony, density, report
    audio/            ffmpeg, decode, waveform, analysis
    stems/            separator interface + Demucs + pass-through
    transcription/    transcriber interface + Basic Pitch + CQT + pYIN
    sources/          provider interface + local + YouTube + Spotify metadata
    web/              the browser interface, bound to 127.0.0.1
    preview/          preview instrument interface + Karplus-Strong synth
    live/             scheduler, input sinks, keymap, player, microphone
    pipeline.py       stage orchestration and caching
    project.py        .shawzify files and recents
    server.py         the stdio JSON-RPC sidecar
    cli.py            the command line
    demo.py           the bundled demo melody
  tests/

apps/desktop/
  src/                React app
    components/       screens and views
    state/            the Zustand store
    lib/ipc.ts        the single door to everything native
  src-tauri/src/
    lib.rs            Tauri commands and app wiring
    engine.rs         sidecar process management
    warframe.rs       window detection and SendInput
    live.rs           the live playback scheduler

packages/shared-types/  TypeScript mirrors of the engine's JSON payloads
```

## Working on the engine alone

The engine has no dependency on Rust or Node.

```powershell
$py = "engine\.venv\Scripts\python.exe"

& $py -m shawzify_engine.cli convert assets\demo\demo.wav --tab --no-write
& $py -m shawzify_engine.cli scales
& $py -m pytest -q                                   # from engine/
& $py -m pytest -q -k songcode                       # one area
& $py -m pytest -q --cov=shawzify_engine
```

As a library:

```python
from shawzify_engine.pipeline import convert
from shawzify_engine.arrangement import ArrangementMode, ArrangementOptions

source, arrangement = convert("song.mp3", ArrangementOptions(mode=ArrangementMode.MELODY))
print(arrangement.to_code())
print(arrangement.report.compatibility_after.to_dict())
for decision in arrangement.decisions[:10]:
    print(decision.original.pitch_name, "->", decision.reason)
```

### Driving the sidecar by hand

```powershell
scripts\dev.ps1 -Engine
```

Then type requests, one JSON object per line:

```json
{"id":1,"method":"ping"}
{"id":2,"method":"environment"}
{"id":3,"method":"analyze","params":{"path":"assets/demo/demo.mid"}}
{"id":4,"method":"arrange","params":{"sourceId":"<from above>","options":{"mode":"chordal"}}}
```

## Working on the frontend

```powershell
cd apps\desktop
npm run dev        # Vite alone: the UI renders, native calls report "needs the desktop app"
npm run tauri:dev  # the desktop shell
npm run test
npx tsc --noEmit
```

The same app also runs against the Python web server, which is often the faster
loop because it skips the Rust build:

```powershell
cd apps\desktop; npm run build
scripts\dev.ps1 -Cli web
```

`lib/ipc.ts` picks its transport at runtime: Tauri commands when it is running
in the desktop shell, HTTP plus server-sent events when the page came from the
web server. Components never know which.

Outside a Tauri window `lib/ipc.ts` falls back to a clearly labelled unavailable
bridge rather than throwing at import time, so component work does not require
the full stack.

## Working on the Rust shell

```powershell
cd apps\desktop\src-tauri
cargo test         # unit tests, including the scheduler drift test
cargo clippy
cargo build
```

`cargo test` does not need the frontend built, but `cargo build` does — the
Tauri build step embeds `apps/desktop/dist`. Run `npm run build` first, or just
use `npm run tauri:dev`.

## Testing philosophy

* **Assert on musical outcomes, not tuning constants.** `test_arrangement.py`
  checks that a melody keeps its contour and that Chordal mode uses chord
  positions — not that a weight equals 0.15. The weights should be tunable
  without breaking the suite.
* **One invariant runs on everything.** `assert_playable()` re-validates every
  arrangement against the instrument model: valid positions, ordered ticks, one
  fret per instant, every output pitch producible by the chosen scale, and the
  code decodes. It runs for every fixture in every mode.
* **Property tests where the property is real.** `transpose(n, 12)` preserves
  pitch class; `decode(encode(song))` preserves every event; full-strength
  quantization lands exactly on the grid; every emitted code is `3n+1`
  characters of the alphabet.
* **One golden fixture pins reality.** `1BAACAIEAQJAYKAgMAo` is a real published
  song code. Decoding it must give an ascending C pentatonic minor run, and
  re-encoding must be byte-identical. That single test pins the alphabet, the
  bit layout, the tick rate and the scale indexing at once.
* **No committed audio.** Every WAV the tests use is synthesised in
  `conftest.py`.
* **The sidecar is tested as a subprocess.** `test_server.py` spawns the real
  process with piped stdio, because the failures that matter there only happen
  in that configuration.

## Benchmarking

```powershell
scripts\dev.ps1 -Cli convert assets\demo\demo.wav --no-write --json |
  ConvertFrom-Json |
  Select-Object -ExpandProperty report |
  Select-Object -ExpandProperty stageTimings
```

Every conversion reports per-stage timings; the Advanced view in the app shows
the same numbers. The arrangement stage is the one that must stay fast, since it
re-runs on every control change.

## Latency calibration

Live playback timing is measured, not guessed:

```powershell
scripts\dev.ps1 -Cli convert assets\demo\demo.mid --no-write --dry-run-live
```

That runs the scheduler and the whole key-mapping layer against a recording sink
with a virtual clock, and reports mean and maximum timing error. The Rust
scheduler has an equivalent test (`scheduler_does_not_accumulate_drift`) that
fires 40 events over a second with a deliberately overshooting sleep and asserts
the error stays per-event rather than cumulative.

The in-game offset is a separate matter — it depends on the machine and the
display path — which is why Settings has a Playback Offset slider rather than a
hard-coded constant.

## Adding things

**A transcription backend** — implement `Transcriber` in
`transcription/base.py`, add it to `available_transcribers()` in priority order.
`available()` must be cheap and must never raise.

**An audio source** — implement `AudioSourceProvider` in `sources/base.py` and
add it to `SourceResolver`. `available()` returns `(usable, reason)` and the
reason is shown to the user, so make it actionable.

**A stem separator** — implement `StemSeparator` in `stems/base.py`.

**A preview instrument** — implement `PreviewInstrument` in `preview/synth.py`.
Real Shawzin samples would drop straight in here.

**An arrangement mode** — add a `ModeProfile` to `MODE_PROFILES` in
`arrangement/options.py`. The profile alone reshapes the optimizer; no other
file needs to change.

**An engine method** — add a function to `METHODS` in `server.py`, a wrapper in
`lib/ipc.ts`, and a type in `packages/shared-types`.

## Versioning

`engine/shawzify_engine/version.py` holds a version per algorithm. Bump the
relevant one whenever a change alters output for identical input — cache keys and
project files both depend on them, and a project records the versions that
produced it so a reopened project can say whether it is still reproducible.
