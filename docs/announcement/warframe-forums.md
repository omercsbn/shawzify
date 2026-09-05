# Announcing SHAWZIFY on the Warframe forums

Everything needed to post this, and the reasoning behind each choice. The post
itself is the second half of this file; `warframe-forums.html` is the same text
formatted for pasting straight into the forum editor.

## Where it goes

**[Fan Zone](https://forums.warframe.com/forum/17-fan-zone/)** — that is where
every Shawzin tool already lives, and where the audience is:

* [ShawzinBot 2.0](https://forums.warframe.com/topic/1126568-shawzinbot-20-fully-revamped/)
  — MIDI to key presses. The closest precedent to SHAWZIFY's live playback, and
  it has sat in Fan Zone for years.
* [Shawzin Spreadsheet Tool](https://forums.warframe.com/topic/1127700-shawzin-spreadsheet-tool/)
* [Shawzin Songs Megathread](https://forums.warframe.com/topic/1124212-shawzin-songs-megathread/)
  — hundreds of pages of players trading song codes.
* [Shawzin Request Thread](https://forums.warframe.com/topic/1128604-shawzin-request-thread/)

Post the announcement as a **new topic in Fan Zone**. Then, separately, leave a
short comment in the Megathread and the Request thread with two or three song
codes SHAWZIFY produced and a link back — those threads are where people who
already care about this are reading, and arriving with codes rather than a
pitch is the difference between a tool post and an advert.

## Tags

The tag field is not free text — it offers a fixed list: SPOILERS, Playstation,
Xbox, Nintendo Switch, Community, PS5, PS4, XBSX, XB1, Mobile, iOS, Conclave.

Use **Community** and nothing else. Every other option is a platform tag, and
SHAWZIFY is a Windows program: tagging it PS5 would pull in players who cannot
run it.

There is no PC tag, so the platform has to come from the text. In the post below
it appears in "Optional in-game playback", which is quite far down — if the
thread starts filling with "when console?", move it up or put *(PC)* in the
title.

## Title

**SHAWZIFY — Turn Almost Any Song into a Shawzin Performance (Free & Open Source)**

"Almost any" is the honest version and it costs nothing: the first person whose
death metal track comes out as mush will quote a stronger claim back at you.

Avoid "AI" in the title. It is accurate — there is a neural transcriber in
there — but it reads as marketing and invites an argument you do not want in
your own announcement thread.

## Before you post

* **Attach the images through the forum's own upload button** rather than
  leaving them hotlinked. Forum uploads outlive a repository rename. The three
  files are in `assets/screenshots/`.
* Reply to your own thread with a couple of song codes people can paste in
  immediately. A thread with something to try in it does far better than one
  with a download link.
* Expect "is this allowed?" in the first ten replies. The answer is in the post
  already — ordinary keystrokes, focus-gated, nothing touching the game — and
  ShawzinBot is the precedent. Answer once, calmly, and link to
  [SECURITY.md](../../SECURITY.md).
* Watch the SmartScreen question too: the installer is unsigned, the release
  notes explain why, and the hash is published.

---

# The post

**Title:** SHAWZIFY — Turn Almost Any Song into a Shawzin Performance (Free & Open Source)

---

The Shawzin has twelve notes. Most music does not.

Every tool I could find takes a MIDI file and maps note numbers onto Shawzin
keys. That works right up until the music does not fit — and usually, it does
not.

Notes fall outside the range. Chords do not fit the available fret positions.
Melodies jump octaves. The tune survives on paper and dies in your ears.

So I spent a while building the other half:

**SHAWZIFY takes a song and decides what should survive.**

![The SHAWZIFY workspace: waveform, piano roll, compatibility breakdown and song structure](https://omercsbn.github.io/shawzify/screenshots/workspace.png)

Drop in an MP3, WAV or MIDI file — or paste a YouTube link.

SHAWZIFY separates the stems, transcribes the notes, detects the key and tempo,
finds the song structure, and then arranges the result specifically for the
Shawzin.

At the end, you get a Shawzin song code you can paste into the game.

## What "arranging" actually means

This is not just MIDI note → Shawzin key mapping.

* Every note gets an importance score based on transcription confidence,
  velocity, melodic role, phrase position and rhythmic significance. When
  something has to disappear, low-value information goes first.

* All nine Shawzin scales are searched across possible transpositions and ranked
  by how much musical information they preserve.

* The melody is mapped as a **path**, rather than mapping every note
  independently. That lets it preserve melodic contour instead of suddenly
  jumping octaves whenever it hits the Shawzin's range boundary.

* Chords are reduced by harmonic importance — typically preserving the root and
  third before less important chord tones — and can fall back to native Shawzin
  chord positions when appropriate.

* Dense passages are simplified only where their actual note density exceeds
  what the instrument can reasonably reproduce.

* Songs that exceed the compatibility limits SHAWZIFY targets are not silently
  truncated. They are split at musical phrase boundaries into separately
  importable parts.

![Compatibility analysis, detected song structure and ranked Shawzin recommendation](https://omercsbn.github.io/shawzify/screenshots/panels.png)

## It also recommends which Shawzin to use

SHAWZIFY models the musical properties of the supported Shawzin profiles rather
than treating every instrument as interchangeable.

Tone, sustain, chord behaviour and other instrument characteristics can make one
Shawzin much better suited to a particular arrangement than another.

The engine measures the track and ranks the available choices with an
explanation.

A fast, dense melody probably does not want an instrument with an extremely long
sustain.

A chord-heavy arrangement may benefit from an instrument that handles those
passages differently.

You can see the reasoning instead of getting a mystery score.

## And it tells you what it changed

Every modified note carries an arrangement decision explaining what happened to
it — moved into range, folded down an octave, replaced by a Shawzin chord
position, spread into an arpeggio, or dropped — and the piano roll colours each
note by which of those it was.

![The warnings panel showing removed, shifted and arpeggiated notes — and why](https://omercsbn.github.io/shawzify/screenshots/warnings.png)

So if the result sounds wrong, you can actually inspect what the arranger decided
instead of staring at a finished song code.

## Try it without installing anything

**Interactive demo:**

https://omercsbn.github.io/shawzify/demo/

This is the real SHAWZIFY interface replaying a real conversion.

Switch arrangement modes, inspect the piano roll, open the analysis panels and
see what the engine produced.

## Download / Source

**GitHub:**

https://github.com/omercsbn/shawzify

SHAWZIFY is free and MIT licensed.

The repository also includes the research behind the Shawzin song-code
implementation:

https://github.com/omercsbn/shawzify/blob/main/docs/research/shawzin-format.md

along with credit to the existing Shawzin tools and projects I learned from.

## Optional in-game playback

SHAWZIFY can also play an arrangement through the game on PC using external
keyboard input events.

It does **not**:

* inject DLLs
* modify Warframe
* read or write game memory
* hook the game client
* interact with anti-cheat

Playback only runs while the Warframe window is focused.

The focus check happens before every scheduled note and cannot be disabled. If
Warframe loses focus, playback stops.

This feature is optional; song-code generation and export do not depend on it.

As with any third-party software used alongside Warframe, users should make their
own decision based on Digital Extremes' third-party software policy.

## Local-first

The conversion pipeline runs locally on your own machine.

Your audio is not uploaded to SHAWZIFY or to an AI/cloud service for processing.

Stem separation, transcription, analysis and arrangement happen locally.

## What would help me most

**Give me a song SHAWZIFY arranges badly.**

Seriously.

Post the track, the arrangement mode/settings you used, and what sounds wrong.

The arrangement engine is ultimately a pile of musical judgement calls:

Which note matters more?

Which octave sounds less wrong?

When should a chord become an arpeggio?

When does simplification destroy the melody instead of helping it?

The fastest way to improve those decisions is to find songs where they fail.

So if you manage to make SHAWZIFY butcher something:

**I want to hear it.**

---

*SHAWZIFY is an independent fan-made project. It is not affiliated with or
endorsed by Digital Extremes.*
