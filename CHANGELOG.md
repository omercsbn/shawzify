# Changelog

All notable changes to SHAWZIFY are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[semantic versioning](https://semver.org/spec/v2.0.0.html).

Algorithm versions are tracked separately in
`engine/shawzify_engine/version.py`: a bump there means identical input now
produces different output, which invalidates caches and marks stored projects
as no longer reproducible.

## [Unreleased]

## [0.2.0] — 2026-09-06

Arrangement quality, driven by measuring real tracks rather than fixtures:
Clubbed to Death, BFG Division, a Turkish pop song, and Für Elise as a control.
The interesting part is that the twelve-note limit was not the problem in any
of them.

### Fixed

- **A handful of invented notes decided the whole arrangement.** Automatic
  transcription reports notes that are not there, and every decision that
  follows read the extremes of the note set rather than its body. On Clubbed to
  Death, 135 notes out of 4829 stretched the apparent range by two octaves and
  took pitch accuracy from 56% to 4.6%. Transcriptions are now cleaned first:
  pitch accuracy 4.6% → 58.9%, overall 63.2 → 80.1.
- **The scale search chose the least recognisable option.** It took Chromatic
  for a vocal line — every pitch class, 0.92 of an octave of range — folding
  half the melody so every leap was 3.46 semitones wrong against 1.57 for
  Minor. Interval fidelity is now scored directly, and an octave fold no longer
  counts as a perfect hit, which is how a scale that folded 61% of a piece used
  to score 96.4% covered. Interval error roughly halved on every track tested.
- **Scoring weights could saturate.** The caller normalised its own weights, so
  a term added later fell outside that sum, pushed candidates past 1.0, and the
  clamp flattened them into a tie broken by list order. On an eight-note C
  major scale a perfect mapping lost to one that bent a note.
- **The melody was "the highest note sounding".** For anything with two hands
  that is not a melody: when the right hand rests the top note becomes the left
  hand. That line leapt an octave or more between 55% of consecutive notes.
  It is now tracked as a line, and allowed to rest — 55% → 3.1% on that track,
  37.6% → 0.4% on Für Elise.
- **A Turkish filename killed a finished conversion.** Printing
  `şarkı — 音楽.mid` raised UnicodeEncodeError on a console using a legacy code
  page, after all the work was done. Also: `decode ""` died inside pathlib, and
  an unknown scale reached the user as `KeyError`.
- **The browser interface could not open or save files.** Every file button
  called a native dialog that returns null outside the desktop shell, so it did
  nothing at all, silently. Uploads and downloads now go through the local
  server, and drag and drop works.
- **A refused request broke every later request on the same connection.** The
  server answered 403 without reading the body, so the leftover bytes were
  parsed as the next request line.

### Added

- The compatibility score now says what it does not know: it measures the
  arrangement against the transcription and never hears the recording. Stated
  on every audio source, with an uncertain transcription marked in the
  interface.
- A recovery panel when the engine is missing, listing the interpreters found
  on the machine, with a picker that remembers the choice.


## [0.1.1] — 2026-09-05

### Fixed

- **The installer produced an app that could not start.** A downloaded copy has
  no source tree beside it, so the search for the engine fell through to
  whatever `python` was on PATH. On a stock Windows machine that is the
  Microsoft Store alias, a zero-length stub whose only job is to open the
  Store, and trying to run it reported "the directory name is invalid (os
  error 267)". Every candidate interpreter is now asked whether it can import
  `shawzify_engine` before being used, Store aliases are skipped, and a working
  directory that does not exist no longer reaches `spawn`.
- **A missing engine now explains itself.** Instead of an OS error in small
  grey text at the bottom of the window, the app shows what is missing, the one
  command that installs it, the interpreters it found on the machine, and a
  file picker to point at one. The choice is remembered.


## [0.1.0] — 2026-09-05

The first release. Everything below is new.

### The arrangement engine

- Song structure detection — self-similarity over chroma plus register, density
  and energy contours, with checkerboard novelty for the boundaries. Repeats
  share a label, and the section that repeats and hits hardest is the hook.
- Importance scoring over six weighted factors, feeding every reduction
  decision so an intro is sacrificed before a chorus.
- Scale and transposition search across all nine Shawzin scales, scored on
  pitch-class coverage, importance-weighted coverage, range fit, contour
  preservation and tonal anchoring. Runners-up are reported.
- Contour-preserving melody mapping: a Viterbi pass over octave-equivalent
  candidates weighing voice leading, direction and interval distortion.
- Polyphony reduction by harmonic function, using the instrument's twelve
  combined-fret chord positions where a source chord matches one.
- Windowed density reduction that thins only the passages that exceed the
  budget, with floors under beat anchors, phrase edges and the melody.
- Conditional arpeggiation — only when notes genuinely cannot sound together
  and there is time before the next event.
- Four modes (Melody, Balanced, Chordal, Virtuoso) and a Hook focus that
  arranges only the most recognisable window of a song.
- A compatibility score weighted by note importance across pitch error, timing
  shift, melody retention and harmony survival.
- A recorded reason for every changed note, surfaced per note in the interface.
- Automatic splitting at phrase boundaries for songs over the game's four
  minute or one thousand note limits. Nothing is ever truncated.

### Input

- Audio decoding via FFmpeg, plus WAV/FLAC/OGG through libsndfile.
- Stem separation with Demucs (CUDA with automatic CPU fallback).
- Transcription via Basic Pitch (ONNX), a constant-Q multi-pitch transcriber
  with iterative harmonic cancellation, and pYIN for monophonic material.
- MIDI import.
- YouTube fetching through yt-dlp, cached by video id.
- Spotify metadata resolution, with duration-verified matching to a recording.
  Spotify does not permit audio downloads and closed its analysis endpoints to
  new apps in November 2024; SHAWZIFY says so rather than pretending otherwise.

### The Shawzin

- A single authoritative instrument definition: nine scales, twelve chord
  positions each, eleven variants with their polyphony, sustain, chord type,
  clef and tuning.
- Byte-exact song code encoder and decoder, verified against a real published
  code.
- Per-variant recommendation for the arrangement in hand, with reasons.

### Interfaces

- A Tauri desktop app: waveform, piano roll coloured by what happened to each
  note, structure bar, compatibility breakdown, Shawzin picker, export.
- The same interface in a browser via `shawzify web`, bound to `127.0.0.1`
  with a token that survives restarts.
- A command line: `convert`, `analyze`, `fetch`, `shawzins`, `structure`,
  `decode`, `encode`, `scales`, `doctor`, `demo` and `web`.
- The engine is usable as a Python library.

### Live playback

- Windows `SendInput` playback of an arrangement into Warframe, scheduled
  against absolute instants on a monotonic clock so timing error never
  accumulates. Fret keys are held between notes as a player holds them.
- Focus-gated before every event, with Escape to stop. Ordinary user-space
  input only: no injection, no memory access, no hooking, nothing touching
  anti-cheat.
- Latency calibration and a dry-run mode that measures the scheduler without
  the game.

### Everything else

- Local-first: no account, no telemetry, no audio leaving the machine.
- Deterministic output — same notes, same options, same version, same code.
- Structured local logging, cached pipeline stages keyed by content hash and
  algorithm version, and project files that record what produced them.

[Unreleased]: https://github.com/omercsbn/shawzify/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/omercsbn/shawzify/releases/tag/v0.2.0
[0.1.1]: https://github.com/omercsbn/shawzify/releases/tag/v0.1.1
[0.1.0]: https://github.com/omercsbn/shawzify/releases/tag/v0.1.0
