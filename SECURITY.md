# Security policy

## Reporting a vulnerability

Please report privately rather than in a public issue: open a
[security advisory](https://github.com/omercsbn/shawzify/security/advisories/new)
on this repository. If you cannot, open a normal issue that says only that you
have a security report and asks for a contact — no details in it.

Expect an acknowledgement within a week. Fixes ship in the next release; if the
problem is serious, sooner.

## What SHAWZIFY does, so you know what to look at

It is a local desktop application. It has no server, no accounts and no
telemetry, so most of the usual attack surface does not exist. What is left:

**Local HTTP server (`shawzify web`).** Binds `127.0.0.1` and refuses to
construct on any other host. Every API request needs a token, which the CLI
prints in a URL and stores in `%LOCALAPPDATA%\Shawzify\web-token` so the link
survives a restart. Cross-origin requests are rejected. The page itself is
served without authorisation — a browser cannot attach a token to a
`<script src>` — so the document deliberately carries no secret. Anyone who can
read that token can drive the engine, which is why it is not printed anywhere
else. `--new-token` rotates it.

**Media route.** Serves files only from inside SHAWZIFY's own cache directory,
resolved and re-checked after symlink resolution.

**The stdio sidecar.** The desktop shell talks to the engine over a pipe that
only the parent process holds. There is no port and nothing to connect to.

**Untrusted input.** Audio files, MIDI files, project files, song codes and
link metadata are all treated as data. Nothing from them is executed,
interpolated into a shell command, or used to build a file path without
validation. FFmpeg is invoked with an argument array, never a shell string.

**Windows input simulation.** Live playback sends ordinary `SendInput`
keystrokes, and only while Warframe is the focused window — the check runs
before every event and cannot be turned off. There is no injection, no memory
access and no hooking of anything.

**Network.** Only two things reach out: an explicit link fetch you asked for
(via yt-dlp, or the Spotify Web API with your own credentials), and a one-time
model download on first use of an ML backend. No audio ever leaves the machine.

## Things that are not vulnerabilities

* The web token appearing in the URL bar and in shell history. It is a local
  capability, deliberately visible where you started it.
* Another program running as you being able to read that token file. So can it
  read your documents; the token is not a boundary against your own account.
* The bundled FFmpeg. Report those upstream.

## Advisories that do not apply here

Dependency scanners flag the whole lockfile, and a lockfile covers every
platform. Two categories show up on this project and neither reaches anyone who
installs it:

**`glib` (RUSTSEC unsoundness in `VariantStrIter`).** It arrives through
`tauri > muda > gtk > atk > glib`, and every link in that chain is Linux only.
SHAWZIFY ships Windows, where the crate is not in the dependency graph at all:

```powershell
cd apps\desktop\src-tauri
cargo tree -i glib --target x86_64-pc-windows-msvc   # prints nothing
cargo tree -i glib --target x86_64-unknown-linux-gnu # prints the chain above
```

It is also not fixable from here: 0.18.5 is the newest version Tauri's chain
permits and the fix landed in 0.20.0. A future Tauri release will carry it.

**Vite, Vitest and esbuild dev-server advisories.** Those are build tooling.
They matter to someone running `npm run dev` on a machine that then visits a
hostile page; they are not in the installer, and `npm audit --omit=dev` reports
nothing. They still get updated, because a contributor's machine is worth
protecting too.

If you find one that *does* apply, the reporting instructions are above.

## Supported versions

The latest release. This is a small project; there are no maintenance branches.
