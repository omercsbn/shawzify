# Existing Shawzin tools

What already exists, what each does well, and where SHAWZIFY differs. This is
also the credit list: several of these projects are why the format research in
`shawzin-format.md` was possible.

## The landscape

Almost every existing tool takes **MIDI in**. That is a reasonable place to
stop — MIDI already contains discrete notes with pitches and times, so the
remaining work is a lookup table plus timing. It also means the hard part is
left to the user: finding or making a MIDI file that already fits a twelve-note
instrument.

| Project | Input | Output | Licence |
| --- | --- | --- | --- |
| [buff0000n/shawzinscore](https://github.com/buff0000n/shawzinscore) | Song code, MIDI | Viewer, editor, player | MIT |
| [ianespana/ShawzinBot](https://github.com/ianespana/ShawzinBot) | MIDI file / device | Live key presses | MIT |
| [Empyrrhus/MIDI-To-Shawzin](https://github.com/Empyrrhus/MIDI-To-Shawzin) | MIDI | Song code | GPL-3.0 |
| [slimepaws/Midi-To-Shawzin](https://github.com/slimepaws/Midi-To-Shawzin) | USB MIDI | Live key presses | none stated |
| [DANser-freelancer/Warframe-shawzin](https://github.com/DANser-freelancer/Warframe-shawzin) | MIDI | Song code | AGPL-3.0 |
| [PKBeam/shawzin-song-converter](https://github.com/PKBeam/shawzin-song-converter) | Song code | Conversions | — |
| [vinchenzo ShawzinComposer](https://vinchenzo.gitlab.io/warframe-shawzin-composer/) | Manual entry | Song code | — |

### shawzinscore

The most complete piece of work in the ecosystem: a browser-based viewer, editor
and player with a full model of every Shawzin variant, scale and chord voicing,
plus validation of the game's own rules. It is where SHAWZIFY's understanding of
the song-code structure, the scale tables and the format limits came from — and
it is the reason those tables did not have to be reverse-engineered from
scratch.

It is an *editor*, though. You bring the notes.

### ShawzinBot

A .NET application that plays a MIDI file or a live MIDI device into Warframe by
synthesising key presses. Its MIDI-note-to-position table is the source for
SHAWZIFY's absolute pitch reference (Shawzin octave 1 = MIDI 48), and its
default key bindings match the documented in-game controls.

Its mapping is a fixed dictionary: a note outside the table is either skipped or
folded with `note % 12`, which does not preserve contour. SHAWZIFY's live layer
does the same *job* — user-space `SendInput`, focus-gated — but plays an
arrangement that was optimised first.

### The MIDI-to-code converters

`MIDI-To-Shawzin`, `Warframe-shawzin` and similar tools parse a MIDI file and
emit a song code. They differ mainly in how they pick a scale and what they do
with unplayable notes. They are useful and they work; the input problem is the
one they do not address.

## What SHAWZIFY does differently

**Audio in, not just MIDI.** Stem separation, transcription and analysis, so the
input is a song rather than a score.

**Arrangement as constrained optimisation.** Not "which key is this note" but
"what should survive". Importance scoring, a scale/transposition search across
all nine scales, Viterbi melody mapping that preserves contour, polyphony
reduction by harmonic function, targeted density reduction, and conditional
arpeggiation.

**Honest measurement.** The compatibility score is weighted by note importance
and accounts for pitch error, timing shift, melody retention and harmony
survival — not `playable / total`, which would rate a piece that happens to sit
in C pentatonic at 100% no matter how badly it was arranged.

**Explainability.** Every changed note records what happened and why, and the UI
surfaces it per note.

**No truncation.** Over-long songs are split at phrase boundaries into importable
parts.

## Licence and attribution

SHAWZIFY's encoder, decoder, instrument model and arrangement engine are written
from scratch and released under the MIT licence.

* The **MIT-licensed** projects (shawzinscore, ShawzinBot) were the primary
  factual references for the song-code structure, the scale tables and the
  absolute pitch mapping. Their licence permits reuse with attribution; this
  file and `shawzin-format.md` are that attribution.
* The **GPL-3.0** and **AGPL-3.0** projects were read only to corroborate
  factual details of a game's file format. No code, data file or algorithm was
  taken from either. Facts about a format are not copyrightable, and none of
  SHAWZIFY is a derivative work of them.
* The **WARFRAME Wiki** (CC-BY-SA) supplied the scale list, controls table and
  note limits.

No game assets — audio, images or fonts — are included in this repository. The
demo melody is original, written for this project.
