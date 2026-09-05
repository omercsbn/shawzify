# Architecture

## The shape of it

```
   ┌──────────────────────────────────────────────────┐
   │  React + TypeScript                              │   apps/desktop/src
   │  waveform · piano roll · controls · export       │
   └───────────────────────┬──────────────────────────┘
                           │  Tauri IPC (invoke / events)
   ┌───────────────────────┴──────────────────────────┐
   │  Rust                                            │   apps/desktop/src-tauri
   │  sidecar lifecycle · Windows input · scheduler   │
   │  window focus · clipboard · file IO              │
   └───────────────────────┬──────────────────────────┘
                           │  newline-delimited JSON over stdin/stdout
   ┌───────────────────────┴──────────────────────────┐
   │  Python                                          │   engine/shawzify_engine
   │  decode · stems · analyse · transcribe           │
   │  arrange · encode · preview                      │
   └──────────────────────────────────────────────────┘
```

Three languages, each doing what it is actually good at:

* **Python** has the audio and ML ecosystem. Everything musical lives here, and
  it is usable standalone as a library and a CLI with no desktop app involved.
* **Rust** owns the process, the Windows APIs, and — importantly — the live
  playback clock. Key timing must not be at the mercy of the GIL or IPC latency.
* **TypeScript** draws. It holds no musical logic; it renders what the engine
  reports and sends option changes back.

## Why a stdio sidecar rather than a local HTTP server

A localhost server needs a port, a bind address, and an authentication story,
and gets all three wrong eventually. A child process with piped stdin/stdout
has none of those: the pipe is only reachable by the parent, it dies with the
app, and there is nothing for another program on the machine to connect to.

The protocol is one JSON object per line:

```
→  {"id": 7, "method": "analyze", "params": {"path": "..."}}
←  {"id": 7, "type": "event", "event": "progress", "payload": {...}}
←  {"id": 7, "type": "result", "result": {...}}
```

Requests carry an id; results and progress events carry it back, so several
operations can be in flight and one can be cancelled without touching another.
Long methods run on a worker thread so progress keeps flowing and `cancel` stays
answerable.

### The stdio hazard, and how it is handled

Two real problems appear when a Python audio stack runs with piped stdio:

1. Libraries print to stdout. Basic Pitch writes `Predicting MIDI for ...`,
   which would land in the middle of a JSON response and corrupt the stream.
2. Libraries probe `sys.stdin.isatty()` at import time. `TextIOWrapper`
   serialises its methods, so that call blocks on the lock held by the main
   thread's in-flight `readline()` — a hard deadlock on the first heavy import
   from a worker thread.

`server.claim_channels()` solves both at startup: it duplicates the real file
descriptors for the protocol's own use, then points fd 1 at stderr and fd 0 at
the null device. After that, anything a library prints becomes a log line, and
anything it reads is immediately EOF. `test_server.py` asserts the channel stays
clean.

Relatedly, every subprocess SHAWZIFY spawns (FFmpeg, FFprobe) gets
`stdin=DEVNULL`. A child inheriting the sidecar's stdin pipe can block forever.

## The pipeline

```
file ─▶ decode ─▶ waveform ─┐
                            ├─▶ analyse (tempo, key, density)
        stems ──────────────┤
                            └─▶ transcribe ─▶ NoteEvent[]
                                                  │
                            options ─────────────▶├─▶ arrange ─▶ encode ─▶ song code
```

Everything left of `arrange` is cached by audio content hash. That is the split
that makes the arrangement controls feel instant: dragging the Complexity slider
re-runs `arrange` (tens of milliseconds) and nothing else.

Cache keys include the algorithm version and only the settings that stage
actually depends on, so changing the arrangement mode never invalidates stems.

## The arrangement engine

`engine/shawzify_engine/arrangement/` is the part worth reading.

### 1. Importance (`music/importance.py`)

Every source note gets a 0–1 score from six weighted factors: transcription
confidence, velocity, melodic prominence, duration, rhythmic salience and
position within its phrase. Melodic prominence knows about contour — a peak in
the top line scores higher than a passing note at the same pitch.

The weights are a starting point, not gospel. They are a parameter everywhere
they are used, and the tests assert on *relative* ordering (a melody peak beats
an inner voice) rather than on numbers.

### 2. Quantization (`music/quantize.py`)

AUTO scores each candidate grid on two things: how well onsets line up with it,
and how many *distinct* onsets survive it. The second term is what stops a piece
being flattened onto quarter notes just because the survivors line up neatly.

Grids finer than 1.5 Shawzin ticks are excluded outright — they cannot survive
encoding at 16 ticks per second, so choosing one would be pretending.

### 3. Scale search (`arrangement/scale_optimizer.py`)

Nine scales × 25 transpositions, each scored on pitch-class coverage,
importance-weighted coverage, range fit, contour preservation and tonal
anchoring against the detected key. Near-ties prefer the transposition that
changes the music least: a whole-octave shift keeps the key, a semitone shift
does not, so they are penalised very differently.

This is a fast analytic model, not a trial arrangement. Only the winner is
arranged for real, but the shortlist is reported so the UI can offer the
alternatives.

### 4. Density (`arrangement/density.py`)

A sliding window finds the passages that actually exceed the budget and thins
only those. Removing globally-least-important notes would wreck quiet passages
to pay for loud ones. Beat anchors, phrase edges and (optionally) the melody get
an importance floor, so they go last.

### 5. Mapping (`arrangement/mapping.py`)

Each source note gets a *set* of playable candidates — every octave-equivalent
in the scale, plus near-miss neighbours when the pitch class is unavailable —
and a Viterbi pass picks the path minimising

```
per-note   pitch displacement + pitch-class mismatch + range-edge pressure
transition voice-leading distance + contour direction + interval distortion
```

Mapping each note independently is what makes naive converters sound wrong: the
line jumps octaves at range boundaries and the shape breaks. `O(N·K²)` with
K ≈ 3 costs nothing next to transcription.

### 6. Polyphony (`arrangement/polyphony.py`)

The fret constraint means the only notes playable with a given note are the two
others on its fret row. Survivors are ranked by harmonic function — root and
third before seventh before fifth — with the bass and the top voice both
protected. Where a source chord's pitch classes match one of the twelve
combined-fret chord positions well enough, that position is used instead, which
preserves far more harmony than two scale notes could.

### 7. Arpeggiation (`arrangement/arpeggio.py`)

Only when notes genuinely cannot sound together *and* there is time before the
next event. At sixteenths at 180 BPM there is no room, and forcing one there
would smear the rhythm rather than preserve the chord.

### 8. Encoding (`shawzin/songcode.py`)

`_build_song_events` is where the hard constraints stop being aspirational: one
fret state per tick (a conflicting event is nudged forward until it has a tick
to itself, or dropped with a recorded reason), no string re-plucked inside the
minimum gap, and events strictly ordered. `validate_events` then re-checks the
result against the instrument model before anything is emitted.

Every arranged note is verified playable in the tests, for every fixture and
every mode.

## Determinism

Same notes, same options, same engine version → byte-identical song code. There
is no randomness in the arrangement path; the one place a random generator
appears (the preview synthesiser's pluck excitation) is seeded per pitch.

Engine versions are recorded in `version.py`, in conversion reports, and in
project files, so a reopened project can say whether its stored arrangement is
still reproducible.

## Live playback

`src-tauri/src/live.rs` schedules against absolute target instants from a
monotonic start, so error never accumulates. Each wait sleeps coarsely down to a
1.5 ms margin and then spins — Windows' default timer granularity is around
15 ms, which is far too coarse for musical timing.

Fret keys are *held* between notes and only changed when the next event needs a
different position, exactly as a player holds them. That avoids a release/press
pair between every note of a run.

Python has a parallel implementation in `live/` used by the CLI's `--dry-run-live`
and by the tests, built around an `InputSink` interface: `RecordingInputSink`
lets the whole note-to-key layer be tested with no Warframe, no Windows API and
no real keyboard.

## Error handling

`common/errors.py` defines one exception hierarchy. Every error carries a
human-readable `message`, an optional actionable `hint`, and a `technical` field
holding the stack trace. The UI shows the message, puts the technical detail
behind a disclosure, and writes both to the local log. `RuntimeError: CUDA error
700` is never what a user sees; "GPU processing failed. SHAWZIFY switched to CPU
mode." is.
