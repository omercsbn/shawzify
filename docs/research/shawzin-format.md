# The Warframe Shawzin song code format

Everything SHAWZIFY knows about the instrument lives in
`engine/shawzify_engine/shawzin/data/shawzin_instrument.json`. This document
records where each fact came from, how it was verified, and where the sources
disagree.

Nothing here was assumed. Every constant below is either cross-checked against
at least two independent sources or verified by decoding a real in-game song
code and getting the expected music back.

## Sources

| Source | Licence | What it was used for |
| --- | --- | --- |
| [buff0000n/shawzinscore](https://github.com/buff0000n/shawzinscore) | MIT | Song-code structure, scale and chord tables, format limits |
| [ianespana/ShawzinBot](https://github.com/ianespana/ShawzinBot) | MIT | Absolute MIDI pitch of the instrument, default key bindings |
| [WARFRAME Wiki — Shawzin](https://warframe.fandom.com/wiki/Shawzin) | CC-BY-SA | Scale list and order, controls, note limits, chord/slap behaviour |
| [Empyrrhus/MIDI-To-Shawzin](https://github.com/Empyrrhus/MIDI-To-Shawzin) | GPL-3.0 | Read for corroboration only — no code or data taken |
| [DANser-freelancer/Warframe-shawzin](https://github.com/DANser-freelancer/Warframe-shawzin) | AGPL-3.0 | Read for corroboration only — no code or data taken |
| Community song-code guides (Steam) | — | A real published song code used as a golden test fixture |

**Licence note.** SHAWZIFY's encoder, decoder and instrument model are written
from scratch. The GPL and AGPL projects above were consulted only to confirm
factual details of a game's file format; no code was copied from any of them.
The MIT-licensed projects were the primary reference for the format's structure.

## Physical model

The Shawzin has three strings and three fret buttons. The fret buttons combine,
so there are eight fret states:

```
0      no fret held        1      Sky fret
2      Earth fret          3      Water fret
12  13  23  123            combinations
```

* A **single** fret state (`0`, `1`, `2`, `3`) plus a string sounds one note.
  Four fret states x three strings = **12 notes per scale**.
* A **combined** fret state (`12`, `13`, `23`, `123`) plus a string sounds a
  fixed three-note **chord** — 12 chords per scale. On the Tiamat Shawzin these
  positions produce a slap-bass version of the corresponding note instead of a
  chord (the wiki states this explicitly, and shawzinscore's data has
  `chords: "none"` with `chordtype: "slap"` for that instrument).

The fret is a hand position, which produces the constraint that shapes the whole
arrangement engine:

> **Every note sounding at the same instant must share one fret state.**

So the only notes playable *together* with a given note are the two others on
its fret row. shawzinscore enforces exactly this, flagging simultaneous notes
with differing frets as "Invalid concurrent notes".

## Song code encoding

A song code is `3n + 1` characters:

```
<scale><note><note>...

scale : one character, the 1-based index into the scale order, so "1".."9"
note  : three base64 characters
          [0]  note byte
          [1]  measure       = tick / 64
          [2]  measure tick  = tick % 64
```

The note byte is a bit field:

| Bit | Value | Meaning |
| --- | --- | --- |
| 0 | 0x01 | String 1 |
| 1 | 0x02 | String 2 |
| 2 | 0x04 | String 3 |
| 3 | 0x08 | Fret 1 (Sky) |
| 4 | 0x10 | Fret 2 (Earth) |
| 5 | 0x20 | Fret 3 (Water) |

Several string bits may be set at once: that is a strum, and it is a single
event in the code rather than several. Several fret bits set at once selects a
chord position.

The base64 alphabet is the **standard** one, letters before digits:

```
ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/
```

This matters — using the URL-safe or a digits-first ordering produces codes the
game rejects.

### Time

Time is measured in **ticks of 1/16 second**. `tick = measure * 64 + measureTick`,
so 64 characters of the low-order field cover exactly 4 seconds.

### Duviri alt notes

A note may carry a second "alt" note by appending three more characters:
`<noteByte>//`. The `//` marker is unambiguous because it would otherwise encode
tick 4095, beyond the game's own cap. SHAWZIFY decodes alt notes and preserves
them on re-encode, but never generates them: only the Corbu and Narmer Shawzins
support them, and a multi-string event cannot carry one.

## Limits

| Limit | Value | Source |
| --- | --- | --- |
| Ticks per second | 16 | shawzinscore, corroborated by "64 characters = 4 seconds" in community guides |
| Maximum song length | 240 s (3840 ticks) | shawzinscore comment: the format reaches 4m16s but the game caps at exactly 4m |
| Encodable maximum | 4095 ticks (255.94 s) | Two base64 characters |
| Maximum notes | 1000 | Wiki: "Global limit of notes in a song is 1000"; shawzinscore uses the same |
| Chat-link limit | 100 | Wiki: "The maximum number of notes in song for linking in chat is 100" |
| In-game lead-in | ~2.75 s (44 ticks) | shawzinscore |

A note is one string pluck, so a three-string strum counts as three notes
against the 1000-note limit. SHAWZIFY counts it the same way.

## Scales

Nine scales, in the order the in-game Tab key cycles them. The scale character
in a song code is the 1-based index into this list.

| Code | Id | Name | Pitch classes (from C) | Range |
| --- | --- | --- | --- | --- |
| 1 | `pmin` | Pentatonic Minor | 0 3 5 7 10 | C3–D#5 |
| 2 | `pmaj` | Pentatonic Major | 0 2 4 7 9 | C3–D5 |
| 3 | `chrom` | Chromatic | all 12 | C3–B3 |
| 4 | `hex` | Hexatonic (blues) | 0 3 5 6 7 10 | C3–A#4 |
| 5 | `maj` | Major | 0 2 4 5 7 9 11 | C3–G4 |
| 6 | `min` | Minor | 0 2 3 5 7 8 10 | C3–G4 |
| 7 | `hira` | Hirajoshi | 0 1 5 6 9 10 | C3–C#5 |
| 8 | `phry` | Phrygian Dominant | 0 1 4 5 7 8 10 | C3–G4 |
| 9 | `yo` | Yo | 1 3 6 8 10 | C#3–D#5 |

The ranges differ enormously — Chromatic covers a single octave with every
semitone, while Pentatonic Minor spans more than two octaves with five notes per
octave. That trade-off is exactly what SHAWZIFY's scale optimizer searches over.

The full per-position note and chord tables are in the data file; they were
extracted programmatically from shawzinscore's metadata and are identical across
every Shawzin variant (chord *voicings* differ per variant, note pitches do not).

## Absolute pitch, and a documented disagreement

SHAWZIFY places the Shawzin's first octave at **MIDI 48 (C3)**, so the full
instrument spans MIDI 48–75.

* **ShawzinBot** maps the Chromatic scale's twelve positions to MIDI 48–59
  (`{48, {0,0,1,0}}` is fret 0, string 1) and its table tops out at MIDI 75.
  This is an empirically derived table from a widely used converter.
* **The WARFRAME Wiki** labels its first-octave sample files C4–B4, which would
  put the instrument an octave higher.

The two disagree by one octave. SHAWZIFY follows ShawzinBot, because that table
was derived by playing the instrument rather than by labelling sample files, and
because it is what other converters in the ecosystem assume. The value is not
hard-coded: `baseMidi` in the data file controls it, and every pitch in the
model is derived from it.

Practically the disagreement matters little — the arrangement engine's automatic
transposition absorbs a constant octave offset — but it would change the
transposition number shown in the UI, so it is recorded here rather than hidden.

Naming note: the wiki calls scale 8 "Phrygian"; its intervals (0 1 4 5 7 8 10)
are Phrygian *Dominant*. SHAWZIFY uses the musically correct name.

## Verification

The `1BAACAIEAQJAYKAgMAo` fixture in `engine/tests/test_songcode.py` is a real
published song code. SHAWZIFY decodes it to an ascending C pentatonic minor run
— C3, D#3, F3, G3, A#3, C4 at half-second intervals — and re-encodes it
byte-for-byte identically. That single test pins the alphabet, the bit layout,
the tick rate, the measure split and the scale indexing all at once.

Property tests additionally assert that `decode(encode(song))` preserves every
event for randomly generated songs, that every emitted code is `3n+1` characters
drawn from the alphabet, and that no generated arrangement ever violates the
one-fret-per-instant rule.
