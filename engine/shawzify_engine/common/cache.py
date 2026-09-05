"""Content-addressed cache for expensive intermediates.

Key = sha256 of (file content or explicit payload) plus a namespace and a
version/settings fingerprint. Changing only arrangement settings must not
invalidate stems, so each namespace picks its own fingerprint inputs.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any

from .paths import cache_dir

_CHUNK = 1 << 20


def hash_file(path: str | os.PathLike[str]) -> str:
    """sha256 of file contents, streamed so large files are fine."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(_CHUNK)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def hash_payload(payload: Any) -> str:
    data = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def make_key(*parts: str) -> str:
    joined = "\x00".join(parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:32]


class Cache:
    """Namespaced disk cache. Values are JSON blobs or opaque directories."""

    def __init__(self, root: str | None = None) -> None:
        self.root = Path(root or cache_dir())

    def _ns(self, namespace: str) -> Path:
        p = self.root / namespace
        p.mkdir(parents=True, exist_ok=True)
        return p

    def json_path(self, namespace: str, key: str) -> Path:
        return self._ns(namespace) / (key + ".json")

    def get_json(self, namespace: str, key: str) -> Any | None:
        p = self.json_path(namespace, key)
        if not p.exists():
            return None
        try:
            with open(p, encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, json.JSONDecodeError):
            # A half-written or corrupt entry is a cache miss, not a failure.
            p.unlink(missing_ok=True)
            return None

    def put_json(self, namespace: str, key: str, value: Any) -> None:
        p = self.json_path(namespace, key)
        tmp = p.with_name(p.name + ".part")
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(value, fh)
            os.replace(tmp, p)
        except OSError:
            tmp.unlink(missing_ok=True)

    def dir_path(self, namespace: str, key: str) -> Path:
        return self._ns(namespace) / key

    def get_dir(self, namespace: str, key: str) -> Path | None:
        p = self.dir_path(namespace, key)
        return p if (p / ".complete").exists() else None

    def begin_dir(self, namespace: str, key: str) -> Path:
        p = self.dir_path(namespace, key)
        if p.exists():
            shutil.rmtree(p, ignore_errors=True)
        p.mkdir(parents=True, exist_ok=True)
        return p

    def commit_dir(self, namespace: str, key: str) -> Path:
        p = self.dir_path(namespace, key)
        (p / ".complete").write_text("ok", encoding="utf-8")
        return p

    def size_bytes(self) -> int:
        total = 0
        for dirpath, _dirnames, filenames in os.walk(self.root):
            for name in filenames:
                try:
                    total += os.path.getsize(os.path.join(dirpath, name))
                except OSError:
                    pass
        return total

    def clear(self, namespace: str | None = None) -> None:
        target = self._ns(namespace) if namespace else self.root
        shutil.rmtree(target, ignore_errors=True)
