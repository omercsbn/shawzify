# Changelog

All notable changes to SHAWZIFY are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[semantic versioning](https://semver.org/spec/v2.0.0.html).

Algorithm versions are tracked separately in
`engine/shawzify_engine/version.py`: a bump there means identical input now
produces different output, which invalidates caches and marks stored projects
as no longer reproducible.

## [Unreleased]

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

[Unreleased]: https://github.com/omercsbn/shawzify/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/omercsbn/shawzify/releases/tag/v0.1.0
