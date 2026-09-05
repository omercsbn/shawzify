# Contributing to SHAWZIFY

Bug reports and arrangements that came out badly are genuinely the most useful
thing you can send. The engine is a pile of musical judgement calls, and the
only way to know a weight is wrong is to hear it.

## Getting set up

```powershell
git clone https://github.com/omercsbn/shawzify
cd shawzify
scripts\setup.ps1          # -SkipMl if you do not want PyTorch (much faster)
scripts\test.ps1           # everything should pass before you change anything
```

Prerequisites and layout are in [docs/development.md](docs/development.md).
The engine alone needs only Python — no Rust, no Node — if that is the part you
are working on.

## Reporting a bad arrangement

This is the report that helps most, and it needs three things:

1. **What you converted** — a link, or the file's name and where it came from.
   Please do not attach copyrighted audio.
2. **The settings** — mode, complexity, scale, stem source. The Advanced panel
   or `--json` output has all of them.
3. **What was wrong with it** — "the chorus lost its melody", "the rhythm went
   flat", "it picked the wrong scale". Specific beats vague.

`shawzify convert song.mp3 --json > report.json` captures the whole decision
trail, including per-note reasons. Attach it if you can.

## Changing the engine

A few things the codebase is opinionated about:

* **Assert on musical outcomes, not tuning constants.** A test that says "a
  melody keeps its contour" survives retuning; one that says "the weight is
  0.15" does not.
* **Every arrangement stays playable.** `assert_playable()` re-validates
  against the instrument model. If you add a code path that emits notes, it
  runs through there too.
* **Explain every change to a note.** A decision without a reason is a bug;
  the UI shows those reasons to the user.
* **No mocks in production paths.** A backend that cannot work should say so
  through `available()`, not return plausible-looking fake data.
* **Bump the algorithm version** in `engine/shawzify_engine/version.py` when a
  change alters output for identical input. Cache keys and project files depend
  on it.

If you are adding a transcription backend, an audio source, a stem separator, a
preview instrument or an arrangement mode, there is a short recipe for each at
the end of [docs/development.md](docs/development.md).

## Before you open a pull request

```powershell
scripts\test.ps1
```

That runs pytest, ruff, tsc, vitest and cargo test. CI runs the same thing on
Windows, so a green local run means a green CI run.

Keep commits focused, and write the message for someone reading `git log` in a
year: what changed and why, not what the diff already shows.

## Security

Please do not open a public issue for a security problem — see
[SECURITY.md](SECURITY.md).

## What is out of scope

* **Anything that touches the game process.** No DLL injection, no memory
  reading or writing, no hooking, nothing that interacts with anti-cheat.
  SHAWZIFY sends ordinary user-space keystrokes into a focused window and that
  is the whole extent of it. Pull requests that change this will be closed.
* **Sending user audio anywhere.** Everything runs locally, and the network is
  used only for an explicit link fetch and one-time model downloads.
* **Bundling game assets or copyrighted music.**

## Code of conduct

By participating you agree to the [Code of Conduct](CODE_OF_CONDUCT.md).
