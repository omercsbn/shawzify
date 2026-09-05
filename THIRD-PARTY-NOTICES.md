# Third-party notices

SHAWZIFY is MIT licensed (see `LICENSE`). This file records the works it builds
on, and the notices their licences require.

## Works this project derived data from

### shawzinscore — MIT

`engine/shawzify_engine/shawzin/data/shawzin_instrument.json` — the scale
tables, chord voicings, variant properties and format limits in that file were
extracted from the instrument metadata in
[buff0000n/shawzinscore](https://github.com/buff0000n/shawzinscore) and
re-expressed in SHAWZIFY's own schema. That makes it a derived work, so its
notice is reproduced in full:

```
MIT License

Copyright (c) 2023 Buff00n

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

### ShawzinBot — MIT

The absolute pitch reference SHAWZIFY uses (Shawzin string 1, fret 0 = MIDI 48)
was corroborated against the note table in
[ianespana/ShawzinBot](https://github.com/ianespana/ShawzinBot), as were the
default in-game key bindings. No code was copied.

```
MIT License

Copyright (c) 2019 Ian Ramirez-España

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Works this project read but took nothing from

[Empyrrhus/MIDI-To-Shawzin](https://github.com/Empyrrhus/MIDI-To-Shawzin)
(GPL-3.0) and
[DANser-freelancer/Warframe-shawzin](https://github.com/DANser-freelancer/Warframe-shawzin)
(AGPL-3.0) were read only to corroborate factual details of the song-code
format — the tick rate, the note-byte layout, the alphabet. No code, data file
or algorithm from either is present in SHAWZIFY, and nothing here is a
derivative work of them. Where the three sources disagreed, the disagreement is
recorded in `docs/research/shawzin-format.md`.

## Reference material

The [WARFRAME Wiki](https://warframe.fandom.com/wiki/Shawzin) (CC BY-SA 3.0)
supplied the list of Shawzin variants and their published properties, the
in-game controls table, and the note limits. SHAWZIFY states these facts in its
own structures rather than reproducing the wiki's text.

## Runtime dependencies

SHAWZIFY installs these itself; it does not redistribute them. Their licences
apply to your installation, not to this repository.

| Component | Licence | Used for |
| --- | --- | --- |
| NumPy, SciPy, librosa, soundfile | BSD-3-Clause | Audio analysis |
| mido | MIT | MIDI reading and writing |
| PyTorch, torchaudio | BSD-3-Clause | Tensor runtime for the ML backends |
| Demucs | MIT | Stem separation |
| Basic Pitch | Apache-2.0 | Neural transcription |
| ONNX Runtime | MIT | Running the Basic Pitch model |
| yt-dlp | Unlicense | Optional: fetching audio from a link |
| FFmpeg (via imageio-ffmpeg) | LGPL-2.1+ / GPL-2+ | Decoding compressed audio |
| React, Zustand, Vite, Tailwind CSS | MIT | The interface |
| Framer Motion | MIT | Interface animation |
| Tauri | MIT / Apache-2.0 | The desktop shell |

FFmpeg is invoked as a separate executable through an argument array; SHAWZIFY
does not link against it.

## Not included here

No Warframe assets — audio, images, fonts or data files — are in this
repository. The demo melody in `assets/demo/` is original, written for this
project. No copyrighted music is committed, and none is uploaded anywhere:
every conversion happens on your own machine.
