# shawzify-engine

The audio, music and Shawzin arrangement engine behind
[SHAWZIFY](../README.md). Usable on its own as a library and a CLI; the desktop
app is one of its callers, not a requirement.

```python
from shawzify_engine.pipeline import convert

source, arrangement = convert("song.mp3")
print(arrangement.to_code())
```

```
python -m shawzify_engine.cli convert song.mp3 --tab
```

See `docs/architecture.md` and `docs/development.md` in the repository root.
