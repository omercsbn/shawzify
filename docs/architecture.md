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

## Two shells, one app

The React app runs unchanged in both:

```
  Tauri window                     Browser tab
       |                                |
   Tauri IPC                    HTTP + server-sent events
       |                                |
    Rust shell  --stdio-->  Python engine  <--in-process--  web server
```

`lib/ipc.ts` picks the transport at runtime by looking for `__TAURI_INTERNALS__`
or the marker the web server injects into the page (the token comes from the
page's own URL -- see below). Components never know which
one they are on. Two features are desktop-only and say so rather than failing:
live Warframe playback (Windows key injection, window focus) and native file
dialogs (a browser cannot hand over a real path).

The web server is the standard library — a threading HTTP server with SSE for
progress — so the browser interface adds no dependency. It binds 127.0.0.1,
refuses any other host at construction time, requires a startup token on every
API request, rejects cross-origin requests, and only serves media from inside
SHAWZIFY's own cache.

The page itself is *not* authorised, and cannot be: a browser fetches
`index.html` and its assets with no way to attach a token. So the document must
carry no secret — the page reads its token from its own URL, the one the CLI
printed. Injecting it into the HTML instead would hand it to anything on the
machine that can make an HTTP request.

The token is saved per user and reused, because a fresh one every run kills
every page left open — and a page whose token died looks exactly like a broken
app. `--new-token` rotates it. Refusals read their request body before
answering: on a kept-alive connection an unread body becomes the next request
line, so one unauthorised call would otherwise break every call after it.

A browser also cannot do two things the desktop shell takes for granted: hand
the engine a path, or write a file. So `/api/upload` takes the bytes and stores
them in the cache, and an export with no path is written into the cache and
fetched back through `/media`. Both stay inside the one directory the server
will serve from.

The browser transport also has a failure the desktop one does not: its server
can be stopped while a page stays open. `EventSource` would then retry the dead
port every few seconds forever, silently, so `lib/ipc.ts` owns the retry
instead — closing the failed stream, backing off to a 30 s ceiling, and probing
with a `ping` to tell the two cases apart. A stopped server may return, so it
keeps trying and reconnects; a *restarted* one has a new token, which makes this
page permanently unauthorised, so it stops and says to open the new link.

## Where music comes from

`sources/` is a provider interface with three implementations, all of which end
at the same place: a local audio file the normal pipeline decodes.

* **Local** — the primary input, always available.
* **YouTube** — optional (`yt-dlp`), downloads the best audio stream without
  re-encoding, caches by video id.
* **Spotify** — metadata only. Spotify does not permit audio downloads, and
  since November 2024 its `audio-features` and `audio-analysis` endpoints are
  closed to new apps. What it *is* good for is knowing exactly what a track is,
  so a Spotify link becomes: identify on Spotify, find the recording on YouTube,
  verify by duration.

That verification is the interesting part — a search returns the studio version
next to covers, live versions and hour-long loops. See
`docs/research/music-sources.md` for the scoring.

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

### 0. Structure (`music/structure.py`)

A self-similarity matrix over chroma *plus* register, density and energy
contours. Chroma alone cannot separate a verse from a chorus in a song that
stays in one key -- every frame looks alike and the track collapses into one
section. What actually distinguishes them is that a chorus sits higher, moves
faster and hits harder.

Checkerboard-kernel novelty finds the boundaries; the resulting segments are
clustered by similarity, so repeats share a label. Recognisability is then
mostly repetition -- the part of a song that comes back is the part people
remember -- plus energy, density and a mild preference for the middle.

It feeds two things: the Hook focus mode, and an importance multiplier so
density reduction sacrifices an intro before it touches a chorus.

### 0.5 Cleaning the transcription (`music/cleanup.py`)

A transcription is not a score. It reports notes that are not there:
harmonics an octave or two above the melody, rumble below it, fragments where a
sung note wavered. They are a small fraction of the total and they are ruinous,
because every decision that follows reads the *extremes* of the note set rather
than its body. On Rob Dougan's "Clubbed to Death", 135 notes out of 4829 --
under three percent -- stretched the apparent range by two octaves and took
pitch accuracy from 56% down to 4.6%.

Both rules are conservative, because discarding a real note is worse than
keeping an invented one. An outlying pitch is dropped only when the transcriber
was also unsure of it, so a real piccolo survives. A note shorter than one
Shawzin tick is merged into the note beside it where there is one, and dropped
only when it is alone. MIDI input never goes through this: a MIDI file is exact
and its extremes are the composer's.

### 0.75 Finding the melody (`music/melody.py`)

Taking the highest note sounding at each moment is the obvious way to find a
melody and it is wrong for anything with two hands in it. When the right hand
rests, the top note becomes the left hand, so the line drops two octaves and
climbs back: on Clubbed to Death that line leapt an octave or more between 55%
of consecutive notes, with a mean leap of 14.5 semitones.

A small dynamic program picks the line instead, preferring to continue where
the melody was, biased towards the upper voice and towards notes the importance
model rates highly -- and allowed to rest. That last part mattered most. A line
forced to pick a note from every moment abandons a resting tune and follows the
unbroken accompaniment, which is exactly what it did. With rests available the
same line leaps an octave 3.1% of the time and moves by 2.6 semitones on
average, which is what a melody looks like.

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

Interval fidelity is weighted as heavily as pitch-class accuracy, because
people recognise a tune by the distances between its notes. Without that term
the search took the Chromatic scale for a vocal line -- every pitch class, and
0.92 of an octave of range -- so half the melody was folded and every leap came
out 3.46 semitones wrong against 1.57 for the Minor scale. Every note correct,
the song gone.

An octave fold no longer counts as a perfect hit either. It used to, which is
how a scale that folded 61% of a piece could score 96.4% covered.

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

## Choosing an instrument

`shawzin/recommend.py` ranks the eleven variants for the arrangement in hand.
Polyphony and sustain dominate, because they change what is playable and what it
sounds like; a smaller character term separates variants that are otherwise
identical on those axes.

The sustain term is worth noting: every Shawzin rings for at least two seconds,
so comparing note length against the note gap in absolute terms rates them all
the same. The score is distance from an *ideal* length for this music -- about
four notes' worth of ring -- which is what makes a 28-second Lizzie rank below a
2-second Dax on fast material and above it on very slow material.

## What the compatibility score does not know

It measures how much of the note set the arranger was handed survived the
instrument. It never hears the recording. Feed it a transcription that missed
the music and it will report a high number with complete confidence: BFG
Division transcribed to 1.6 notes per second over a track whose riff runs at
eight to sixteen, and arranging that scored 88%.

`music/trust.py` states this on every audio source rather than trying to hide
it behind a single blended number, and marks a transcription that should not be
trusted. It deliberately does not claim to detect the BFG case; two ways of
doing that were measured and both failed, and the module records why.

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
