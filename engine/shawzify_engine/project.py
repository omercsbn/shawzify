""".shawzify project files.

A JSON manifest that references the source audio by path and content hash
rather than embedding it -- a project stays a few hundred KB even for a long
track. Engine versions are recorded so a reopened project can say whether its
stored arrangement is still reproducible.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .arrangement.arranger import Arrangement
from .arrangement.options import ArrangementOptions
from .common.errors import ShawzifyError
from .common.paths import projects_dir
from .common.safety import safe_output_path
from .music.events import NoteEvent
from .music.key import KeyEstimate
from .pipeline import SourceMaterial
from .version import PROJECT_SCHEMA_VERSION, version_dict


@dataclass
class ProjectFile:
    schema_version: int = PROJECT_SCHEMA_VERSION
    title: str = "Untitled"
    source_path: str = ""
    source_kind: str = "audio"
    content_hash: str = ""
    duration: float = 0.0
    bpm: float = 120.0
    bpm_confidence: float = 0.0
    key: dict[str, Any] | None = None
    analysis: dict[str, Any] | None = None
    options: dict[str, Any] = field(default_factory=dict)
    source_events: list[dict[str, Any]] = field(default_factory=list)
    arrangement: dict[str, Any] | None = None
    song_code: str = ""
    report: dict[str, Any] | None = None
    engine_versions: dict[str, Any] = field(default_factory=version_dict)
    created_at: str = ""
    modified_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "title": self.title,
            "source": {
                "path": self.source_path,
                "kind": self.source_kind,
                "contentHash": self.content_hash,
                "durationSeconds": round(self.duration, 3),
            },
            "analysis": self.analysis,
            "bpm": round(self.bpm, 3),
            "bpmConfidence": round(self.bpm_confidence, 3),
            "key": self.key,
            "options": self.options,
            "sourceEvents": self.source_events,
            "arrangement": self.arrangement,
            "songCode": self.song_code,
            "report": self.report,
            "engineVersions": self.engine_versions,
            "createdAt": self.created_at,
            "modifiedAt": self.modified_at,
        }

    @staticmethod
    def from_dict(d: dict[str, Any]) -> ProjectFile:
        src = d.get("source") or {}
        return ProjectFile(
            schema_version=int(d.get("schemaVersion", 1)),
            title=str(d.get("title", "Untitled")),
            source_path=str(src.get("path", "")),
            source_kind=str(src.get("kind", "audio")),
            content_hash=str(src.get("contentHash", "")),
            duration=float(src.get("durationSeconds", 0.0)),
            bpm=float(d.get("bpm", 120.0)),
            bpm_confidence=float(d.get("bpmConfidence", 0.0)),
            key=d.get("key"),
            analysis=d.get("analysis"),
            options=d.get("options") or {},
            source_events=list(d.get("sourceEvents") or []),
            arrangement=d.get("arrangement"),
            song_code=str(d.get("songCode", "")),
            report=d.get("report"),
            engine_versions=d.get("engineVersions") or {},
            created_at=str(d.get("createdAt", "")),
            modified_at=str(d.get("modifiedAt", "")),
        )

    # -- convenience ----------------------------------------------------

    def events(self) -> list[NoteEvent]:
        return [NoteEvent.from_dict(e) for e in self.source_events]

    def arrangement_options(self) -> ArrangementOptions:
        return ArrangementOptions.from_dict(self.options)

    def key_estimate(self) -> KeyEstimate | None:
        if not self.key:
            return None
        return KeyEstimate(
            tonic_pitch_class=int(self.key.get("tonicPitchClass", 0)),
            mode=str(self.key.get("mode", "major")),
            confidence=float(self.key.get("confidence", 0.0)),
            correlation=float(self.key.get("correlation", 0.0)),
        )

    def is_reproducible(self) -> bool:
        """Whether the stored arrangement matches the current engine version."""
        current = version_dict()
        for key in ("arrangement", "encoder"):
            if self.engine_versions.get(key) != current.get(key):
                return False
        return True


def build_project(
    source: SourceMaterial, arrangement: Arrangement, *, title: str | None = None
) -> ProjectFile:
    import time

    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    return ProjectFile(
        title=title or source.title,
        source_path=source.path,
        source_kind=source.kind,
        content_hash=source.content_hash,
        duration=source.duration,
        bpm=source.bpm,
        bpm_confidence=source.bpm_confidence,
        key=source.key.to_dict() if source.key else None,
        analysis=source.analysis.to_dict() if source.analysis else None,
        options=arrangement.options.to_dict(),
        source_events=[e.to_dict() for e in source.events],
        arrangement=arrangement.to_dict(include_decisions=False),
        # An over-long arrangement has no single valid code; the project stores
        # the events and options, so reopening it re-derives the parts.
        song_code="" if arrangement.over_limits else arrangement.to_code(),
        report=arrangement.report.to_dict(),
        created_at=now,
        modified_at=now,
    )


def save_project(project: ProjectFile, path: str | Path) -> Path:
    import time

    project.modified_at = time.strftime("%Y-%m-%dT%H:%M:%S")
    out = safe_output_path(path)
    if out.suffix.lower() != ".shawzify":
        out = out.with_suffix(".shawzify")
    out.write_text(json.dumps(project.to_dict(), indent=1), encoding="utf-8")
    return out


def load_project(path: str | Path) -> ProjectFile:
    p = Path(path)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ShawzifyError(
            "That project file could not be opened.", cause=exc
        ) from exc
    if not isinstance(data, dict):
        raise ShawzifyError("That project file is not a SHAWZIFY project.")
    schema = int(data.get("schemaVersion", 0))
    if schema > PROJECT_SCHEMA_VERSION:
        raise ShawzifyError(
            "That project was made with a newer version of SHAWZIFY.",
            hint="Update SHAWZIFY to open it.",
        )
    return ProjectFile.from_dict(data)


# -- recent projects -----------------------------------------------------


def _recents_path() -> Path:
    return Path(projects_dir()) / "recent.json"


def load_recents() -> list[dict[str, Any]]:
    p = _recents_path()
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return list(data) if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def remember_project(
    *, title: str, path: str, compatibility: float, source_path: str = "", kind: str = "audio"
) -> list[dict[str, Any]]:
    import time

    entries = [e for e in load_recents() if e.get("path") != path]
    entries.insert(
        0,
        {
            "title": title,
            "path": path,
            "sourcePath": source_path,
            "kind": kind,
            "compatibility": round(compatibility, 1),
            "openedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
        },
    )
    entries = entries[:20]
    try:
        _recents_path().write_text(json.dumps(entries, indent=1), encoding="utf-8")
    except OSError:
        pass
    return entries
