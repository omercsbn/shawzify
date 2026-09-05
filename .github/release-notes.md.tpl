## Install

Download **{{NAME}}** below ({{SIZE}}) and run it. It installs for the current
user only, so it needs no administrator rights.

**The desktop app needs the engine.** SHAWZIFY's audio analysis and arrangement
work is done by a Python engine that is not bundled in the installer — the ML
model weights alone would make it several gigabytes. After installing, clone
this repository and run `scripts\setup.ps1` once; the app finds the engine
automatically. The [README](https://github.com/{{REPO}}#readme) has the
five-minute version.

Prefer no installer at all? `scripts\dev.ps1 -Cli web` gives you the whole
interface in a browser tab, and `shawzify convert song.mp3` gives you a song
code with no interface at all.

**Windows will warn you.** The installer is not code-signed — a certificate
costs a few hundred euros a year, which an unpaid fan project does not have —
so SmartScreen says "unknown publisher". Click **More info → Run anyway**, or
verify the hash below first and decide for yourself. Everything here is built
in the open by the workflow you can read at
[.github/workflows/release.yml](https://github.com/{{REPO}}/blob/{{TAG}}/.github/workflows/release.yml),
from the source at this tag.

## Try it without installing anything

The interface is published at
[omercsbn.github.io/shawzify/demo](https://omercsbn.github.io/shawzify/demo/) —
the real app, replaying a real conversion.

## Verify the download

```
SHA256  {{SHA256}}
```

## What changed

See [CHANGELOG.md](https://github.com/{{REPO}}/blob/{{TAG}}/CHANGELOG.md).

---

SHAWZIFY is an independent fan project. It is not affiliated with, endorsed by,
or connected to Digital Extremes. It sends ordinary keystrokes to a focused
window and never touches the game process.
