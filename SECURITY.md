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

## Supported versions

The latest release. This is a small project; there are no maintenance branches.
