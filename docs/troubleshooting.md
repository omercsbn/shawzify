# Troubleshooting

Start with `shawzify doctor` (or Settings → Audio Engine in the app). It reports
what is installed and usable right now, and most problems below show up there
first.

```powershell
scripts\dev.ps1 -Cli doctor
```

## Setup

### "Node.js 18+ is required"

Install it from [nodejs.org](https://nodejs.org) and re-run `scripts/setup.ps1`.
Only the desktop app needs Node; the CLI works without it.

### "Python 3.10+ is required"

Install Python from [python.org](https://python.org), or install
[uv](https://docs.astral.sh/uv/) — setup uses it to fetch a Python 3.12
automatically, regardless of what is on PATH.

### PyTorch or Demucs will not install

`scripts/setup.ps1 -SkipMl` skips them entirely. You lose stem separation and
Basic Pitch; the built-in CQT and pYIN transcribers still work and the app still
runs. `-Cpu` installs the CPU-only PyTorch build, which is much smaller.

### Basic Pitch fails to install with a TensorFlow error

Expected on Python 3.12+: Basic Pitch declares a TensorFlow dependency that has
no wheels for those versions, even though its ONNX runtime path does not need
it. `setup.ps1` handles this by installing it with `--no-deps` and adding the
packages it actually imports. If you are installing by hand:

```powershell
pip install --no-deps basic-pitch
pip install onnxruntime pretty_midi resampy mir_eval
```

### The virtual environment is in a strange state

```powershell
scripts\setup.ps1 -Force
```

## Audio

### "FFmpeg is not available"

`imageio-ffmpeg` normally supplies a bundled binary. If it did not install,
either add FFmpeg to PATH or point SHAWZIFY at one:

```powershell
$env:SHAWZIFY_FFMPEG = "C:\tools\ffmpeg\bin\ffmpeg.exe"
```

WAV, FLAC and OGG decode through libsndfile and work without FFmpeg. MP3 and
M4A do not.

### "That audio file could not be decoded"

Usually a truncated download or a container FFmpeg cannot read. Test it
directly:

```powershell
ffmpeg -i "your file.mp3" -f null -
```

If FFmpeg also fails, re-download or convert the file first.

### No notes were transcribed

Some possibilities, in order of likelihood:

* **The track is percussion-only or heavily distorted.** There is no pitch to
  find. Try Settings → Stem Separation on, and Stem Source `vocals`.
* **The track is very quiet.** Normalise it first.
* **Stem separation picked the wrong stem.** Set Stem Source explicitly instead
  of `auto`.
* **The transcriber is too strict for this material.** Try `--transcriber cqt`
  on the CLI; it is less precise but more willing.

The app always says which backend produced a result and which stem it used.

## Links

### "yt-dlp is not installed"

YouTube fetching is optional and deliberately not bundled, because extraction
breaks whenever the site changes and you want to update it yourself:

```powershell
engine\.venv\Scripts\python.exe -m pip install -U yt-dlp
```

### A download fails, or extraction errors

Almost always a yt-dlp that has fallen behind. Update it with the command above.
If it still fails, the video may be private, age-restricted or region-locked.

### SHAWZIFY fetched the wrong version of a song

It reports the match confidence for exactly this reason. Pick a different
candidate:

```powershell
shawzify fetch "https://open.spotify.com/track/..." --candidate 1
```

Or paste the YouTube link of the recording you want directly, which skips the
search entirely.

### "No Spotify app credentials"

Spotify needs your own app. Create one at developer.spotify.com/dashboard, then
either put the client id and secret in Settings, or set:

```powershell
$env:SPOTIFY_CLIENT_ID = "..."
$env:SPOTIFY_CLIENT_SECRET = "..."
```

### Spotify returns 403

If it happens on a track lookup, the credentials are wrong. If you are calling
`/audio-features` or `/audio-analysis` yourself, those have been unavailable to
new apps since November 2024 — SHAWZIFY does not use them and does not need
them. See `docs/research/music-sources.md`.

### "Spotify does not allow applications to download audio"

Correct, and not a bug. SHAWZIFY read the track details from Spotify and needs
somewhere to hear it: install yt-dlp so it can find the recording, or point it
at your own copy of the file.

## The browser interface

### "This page is no longer authorised"

The token changes every time the server restarts. Reload from the URL the
current `shawzify web` printed.

### The page is blank

The interface has not been built. Run `npm run build` in `apps/desktop` and
reload. If it is built and still blank, the page now shows the error rather than
staying empty — reload and read what it says.

### Live playback is missing in the browser

It is desktop-only, by design: it needs Windows key injection and window-focus
detection that a browser tab cannot do. Everything else works in both.

### Can I open it from another machine?

No. The server binds 127.0.0.1 and refuses any other host. Exposing a local
music library and file paths to a network is not something to make configurable.

## GPU

### CUDA is not detected

```powershell
engine\.venv\Scripts\python.exe -c "import torch; print(torch.__version__, torch.cuda.is_available())"
```

A `+cpu` version string means the CPU build got installed. Reinstall:

```powershell
engine\.venv\Scripts\python.exe -m pip install --force-reinstall torch torchaudio --index-url https://download.pytorch.org/whl/cu126
```

If `cuda.is_available()` is still False, the NVIDIA driver is likely older than
the CUDA build requires.

### "GPU processing failed. SHAWZIFY switched to CPU mode."

Almost always out of video memory, especially with a game running. It is not an
error — the work completed on the CPU, just more slowly. Close other GPU
applications, or set GPU to `CPU` in Settings to skip the attempt.

## The desktop app

### "Engine offline" / "The SHAWZIFY audio engine is not running"

The shell could not find or start the Python sidecar. Check that
`engine/.venv/Scripts/python.exe` exists (run `scripts/setup.ps1` if not), then
verify the engine runs standalone:

```powershell
scripts\dev.ps1 -Cli doctor
```

To point the shell at a specific interpreter:

```powershell
$env:SHAWZIFY_PYTHON = "C:\path\to\python.exe"
$env:SHAWZIFY_ROOT = "C:\path\to\shawzin"
```

### The window is blank

In dev, Vite may not be up yet — wait for `ready in ...` in the terminal. In a
release build, the frontend was probably not built; run `npm run build` in
`apps/desktop`, or use `scripts/build.ps1`.

### Dragging a file does nothing

File drops arrive through Tauri rather than the DOM, so they only work in the
real desktop window, not in a plain browser tab pointed at the Vite server. Use
"Choose Audio or MIDI" there instead.

## Warframe playback

### The "Play in Warframe" button is disabled

It needs all of: Windows, Warframe running, and a key binding set with no
conflicts. The tooltip and the line under the button say which one is missing.

### "Switch to Warframe and equip the Shawzin emote, then press play"

Warframe is running but is not the focused window. This is deliberate: SHAWZIFY
will not send keystrokes into whatever happens to be in front.

### Playback stops immediately

Focus left Warframe. Alt-tabbing away, a notification stealing focus, or a
borderless-window setup switching monitors will all do it. The safety check runs
before every event and cannot be turned off.

### The notes are wrong in game

The in-game scale must match the one SHAWZIFY chose. The Compatibility panel
shows it; press Tab in game until the Shawzin's scale matches, then play.

### The notes are late, or chords sound broken

Settings → Latency Calibration:

* **Notes land late** → make Playback Offset more negative.
* **Chords sound broken or notes are missed** → raise Fret to string delay
  (try 20–25 ms) and Between strings (try 6–8 ms).
* **Notes are dropped entirely** → raise Key hold time.

Measure the scheduler itself (independent of the game) with:

```powershell
scripts\dev.ps1 -Cli convert assets\demo\demo.mid --no-write --dry-run-live
```

### Some keys do nothing

Your in-game bindings differ from the defaults. Settings → Warframe Key Bindings
→ Calibrate walks through each control and records what you press.

## Results

### "This arrangement exceeds the Shawzin song limit"

The song is over four minutes or over 1000 notes. SHAWZIFY splits it at phrase
boundaries into parts you can import one at a time — the Export panel has a tab
per part. Nothing is truncated. Lowering Complexity also reduces the note count.

### The code will not paste into the game

* The chat-link limit is 100 notes; above that a code can still be imported from
  the clipboard, just not linked in chat. The Export panel says when you are over.
* Make sure the whole code was copied — they can be several hundred characters.
* Verify it decodes before blaming the game:
  `scripts\dev.ps1 -Cli decode <code>`

### The arrangement sounds wrong

Things worth trying, roughly in order:

1. **Mode.** Melody for a tune you want recognisable; Chordal for harmony.
2. **Scale.** Chromatic gives the most accurate pitches but only one octave;
   the pentatonic scales give two and a half octaves with fewer pitch classes.
   The Advanced view lists the runners-up with their scores.
3. **Complexity.** Low removes more and can sound sparse; high keeps more and
   can sound cluttered.
4. **Quantization.** Off preserves expressive timing; a coarse grid tightens a
   loose performance but can flatten a rhythm.
5. **Stem Source.** For a song with vocals, `vocals` usually produces the most
   recognisable result.

### Compatibility seems low

It is measuring something real. A dense, chromatic, wide-range mix genuinely
cannot be reproduced on twelve notes, and the breakdown says which dimension is
losing the most. Melody Preservation is usually the number that matters for
whether a listener recognises the tune.

## Diagnostics

Settings → **Copy Debug Info** produces a JSON report with versions, hardware,
backend availability and stage timings. Your home directory is redacted and no
file contents are included.

Logs are JSONL at:

```
%LOCALAPPDATA%\Shawzify\logs\shawzify.jsonl
```

Settings → Open Logs reveals the folder. To echo them to the terminal while
running the CLI:

```powershell
$env:SHAWZIFY_LOG_ECHO = "1"
```

## Environment variables

| Variable | Effect |
| --- | --- |
| `SHAWZIFY_HOME` | Override the app data directory (cache, logs, projects) |
| `SHAWZIFY_PYTHON` | Interpreter the desktop shell should use for the engine |
| `SHAWZIFY_ROOT` | Repository root, when the shell cannot infer it |
| `SHAWZIFY_FFMPEG` | Path to a specific FFmpeg binary |
| `SHAWZIFY_LOG_ECHO` | `1` to mirror structured logs to stderr |
| `SHAWZIFY_WEB_ROOT` | Serve the web interface from a specific build directory |
| `SPOTIFY_CLIENT_ID` | Spotify app client id (overrides the stored one) |
| `SPOTIFY_CLIENT_SECRET` | Spotify app client secret |
