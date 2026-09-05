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
run it. There is no PC tag, which is exactly why the title says Windows.

## Titles

Pick one. The first is the recommendation: it says what the thing does in the
words a Shawzin player already uses, and "any song" is the actual claim.

1. **SHAWZIFY — turn any song into a Shawzin performance (Windows, free, open source)**
2. SHAWZIFY — drop in an MP3, get a Shawzin song code
3. I built a tool that arranges real music for the Shawzin, not just converts MIDI

Avoid "AI" in the title. It is accurate — there is a neural transcriber in
there — but it reads as marketing and invites an argument you do not want in
your own announcement thread.

## Before you post

* **Attach the images to the post** rather than hotlinking them. Forum uploads
  outlive a repository rename. The three files are in `assets/screenshots/`.
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

**Title:** SHAWZIFY — turn any song into a Shawzin performance (Windows, free, open source)

---

The Shawzin has twelve notes. Most music does not.

Every tool I could find takes a MIDI file and maps note numbers onto Shawzin
keys, which works right up until the music does not fit — and it usually does
not fit. Notes fall outside the range and get clamped. Chords need one fret
position and get mangled. The tune survives on paper and dies in your ears.

So I spent a while building the other half: **SHAWZIFY takes a song and decides
what should survive.**

![The SHAWZIFY workspace](workspace.png)

**Windows, free, MIT licensed** — and there is a browser demo further down if
you would rather look before installing anything.

Drop in an MP3, a WAV, a MIDI file, or paste a YouTube link. It separates the
stems, transcribes the notes, works out the key and the tempo, finds where the
chorus is — and then arranges it for the instrument you are actually holding.
Out comes a song code you paste into the game.

**What "arranging" means here:**

* Every note is scored for importance — confidence, velocity, whether it is
  carrying the melody, where it sits in its phrase — and reductions start from
  the bottom.
* All nine scales are searched at every transposition, scored on how much of
  the music each one keeps.
* The melody is mapped as a *path*, not note by note, so the line keeps its
  shape instead of jumping octaves at the range boundary.
* Chords reduce by harmonic function — root and third before the fifth — and
  fall back to the Shawzin's own chord positions when they fit.
* Dense passages are thinned only where they are actually too dense.
* Nothing is silently truncated. A song past the four-minute or 1000-note limit
  is split at phrase boundaries into parts you import one after another.

![Compatibility and the Shawzin recommendation](panels.png)

**It also tells you which Shawzin to play it on.** The eleven variants differ in
polyphony, sustain and tone, and two of them change what is even playable.
SHAWZIFY measures the music and ranks them with the reasoning shown — a fast
line does not want a 28-second sustain, a chord piece wants something
polyphonic.

**And it tells you what it did to your song.** Every changed note carries a
reason, and the piano roll colours them: played as written, moved to fit, folded
into a chord, arpeggiated, removed.

![The warnings panel](warnings.png)

**Try it without installing anything:** the interface is published at
https://omercsbn.github.io/shawzify/demo/ — that is the real app, replaying a
real conversion. Switch modes, poke at the panels, see what it produces.

**Downloads and source:** https://github.com/omercsbn/shawzify

It also plays the arrangement in game if you want it to — ordinary key presses,
the same ones your keyboard sends, and only while Warframe is the focused
window. It does not inject anything, read or write game memory, hook the client,
or touch anti-cheat in any way. The focus check runs before every note and
cannot be switched off; alt-tab away and it stops. Everything else — the whole
conversion — runs offline on your own machine, and nothing about your music is
ever uploaded.

Free, MIT licensed, and the source is all there, including
[the format research](https://github.com/omercsbn/shawzify/blob/main/docs/research/shawzin-format.md)
and credit to the tools I learned the song-code format from.

**What would help most:** a song it arranges badly. Post the track and the
settings and I will look at what the engine did wrong — the arrangement is a
pile of musical judgement calls and the only way to know one is wrong is to hear
it go wrong.

*SHAWZIFY is an independent fan project. It is not affiliated with or endorsed
by Digital Extremes.*
