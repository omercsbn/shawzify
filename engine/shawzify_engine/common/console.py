"""Make the process's own output able to carry the text it prints.

Windows still gives a console a legacy code page — cp1254 on a Turkish
machine, cp1252 on a German one — and Python honours it. Printing a filename
like ``şarkı — 音楽.mp3`` then raises UnicodeEncodeError, *after* the work is
done, so a conversion that succeeded looks like a crash. The song titles this
program handles come from other people's filenames and other people's YouTube
uploads, so non-ASCII is the normal case, not the exotic one.
"""

from __future__ import annotations

import sys
from typing import IO, Any


def _reconfigure(stream: IO[Any] | None) -> None:
    if stream is None:
        return
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is None:  # a pipe wrapped by something that is not TextIO
        return
    try:
        reconfigure(encoding="utf-8", errors="replace")
    except (ValueError, OSError):
        # A stream that refuses is still better than one that raises later.
        pass


def use_utf8() -> None:
    """Print UTF-8 on every platform, replacing anything the terminal cannot show.

    ``errors="replace"`` matters as much as the encoding: a console font
    without a glyph should cost you a question mark, not the command.
    """
    _reconfigure(sys.stdout)
    _reconfigure(sys.stderr)
