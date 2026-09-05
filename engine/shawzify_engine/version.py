"""Versioned algorithm identifiers.

Every stage that can change its output for identical input carries a version.
These are recorded in project files and conversion reports so a result can be
reproduced (or invalidated) later.
"""

from __future__ import annotations

APP_VERSION = "0.1.0"

#: Bump when the arrangement search changes in a way that alters output.
ARRANGEMENT_ENGINE_VERSION = "1.0.0"
#: Bump when the Shawzin song-code encoder/decoder changes.
ENCODER_VERSION = "1.0.0"
#: Bump when audio transcription changes.
TRANSCRIPTION_VERSION = "1.0.0"
#: Bump when audio analysis (tempo/key/energy) changes.
ANALYSIS_VERSION = "1.0.0"
#: Bump when stem separation configuration changes.
STEMS_VERSION = "1.0.0"
#: Bump when the shawzin instrument data file changes shape.
INSTRUMENT_DATA_VERSION = "1.0.0"
#: .shawzify project manifest schema.
PROJECT_SCHEMA_VERSION = 1


def version_dict() -> dict[str, str | int]:
    return {
        "app": APP_VERSION,
        "arrangement": ARRANGEMENT_ENGINE_VERSION,
        "encoder": ENCODER_VERSION,
        "transcription": TRANSCRIPTION_VERSION,
        "analysis": ANALYSIS_VERSION,
        "stems": STEMS_VERSION,
        "instrumentData": INSTRUMENT_DATA_VERSION,
        "projectSchema": PROJECT_SCHEMA_VERSION,
    }
