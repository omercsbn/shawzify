"""Arrangement options.

AUTO is a first-class value, not ``None``: every option that can be decided by
the engine says so explicitly, and the resolved value is reported back so the
UI can show what AUTO actually chose.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from enum import Enum
from typing import Any, Literal


class Auto(Enum):
    """Sentinel meaning "let the engine decide"."""

    AUTO = "auto"

    def __repr__(self) -> str:  # pragma: no cover - debugging nicety
        return "AUTO"

    def __str__(self) -> str:
        return "auto"


AUTO = Auto.AUTO


class ArrangementMode(str, Enum):
    MELODY = "melody"
    BALANCED = "balanced"
    CHORDAL = "chordal"
    VIRTUOSO = "virtuoso"


class StemSource(str, Enum):
    AUTO = "auto"
    VOCALS = "vocals"
    INSTRUMENTAL = "instrumental"
    FULL_MIX = "full"
    BASS = "bass"
    DRUMS = "drums"
    OTHER = "other"


@dataclass(frozen=True)
class ModeProfile:
    """How a mode reshapes the optimizer's priorities."""

    max_voices: int
    harmony_weight: float
    melody_weight: float
    contour_weight: float
    pitch_error_weight: float
    timing_weight: float
    density_scale: float
    prefer_chord_frets: bool
    arpeggiate_default: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


MODE_PROFILES: dict[ArrangementMode, ModeProfile] = {
    ArrangementMode.MELODY: ModeProfile(
        max_voices=1,
        harmony_weight=0.05,
        melody_weight=1.0,
        contour_weight=0.85,
        pitch_error_weight=1.0,
        timing_weight=0.7,
        density_scale=0.75,
        prefer_chord_frets=False,
        arpeggiate_default=False,
    ),
    ArrangementMode.BALANCED: ModeProfile(
        max_voices=2,
        harmony_weight=0.45,
        melody_weight=0.9,
        contour_weight=0.7,
        pitch_error_weight=0.9,
        timing_weight=0.75,
        density_scale=1.0,
        prefer_chord_frets=False,
        arpeggiate_default=True,
    ),
    ArrangementMode.CHORDAL: ModeProfile(
        max_voices=3,
        harmony_weight=1.0,
        melody_weight=0.6,
        contour_weight=0.45,
        pitch_error_weight=0.7,
        timing_weight=0.7,
        density_scale=0.9,
        prefer_chord_frets=True,
        arpeggiate_default=True,
    ),
    ArrangementMode.VIRTUOSO: ModeProfile(
        max_voices=3,
        harmony_weight=0.6,
        melody_weight=0.85,
        contour_weight=0.6,
        pitch_error_weight=0.85,
        timing_weight=0.9,
        density_scale=1.8,
        prefer_chord_frets=False,
        arpeggiate_default=True,
    ),
}

QuantizeSetting = Literal["off", "1/4", "1/8", "1/8t", "1/16", "1/16t", "1/32"] | Auto


@dataclass(frozen=True)
class ArrangementOptions:
    """Everything the arranger needs beyond the notes themselves."""

    mode: ArrangementMode = ArrangementMode.BALANCED
    scale: str | Auto = AUTO
    transpose: int | Auto = AUTO
    quantization: str | Auto = AUTO           # "off" | grid label | AUTO
    quantization_strength: float = 0.85       # 0..1
    complexity: float = 0.55                  # 0..1, scales density budget
    preserve_melody: bool = True
    arpeggiate_chords: bool | Auto = AUTO
    max_density: float | Auto = AUTO          # notes per second
    shawzin_variant: str = "dax"
    stem_source: StemSource = StemSource.AUTO
    #: Cap on how far AUTO may transpose, in semitones.
    transpose_search: int = 12
    #: Minimum ticks between two plucks of the same string (1 tick = 1/16 s).
    min_repeat_ticks: int = 1
    lead_in_ticks: int | Auto = AUTO
    seed: int = 0  # kept for reproducibility; the engine itself is deterministic

    @property
    def profile(self) -> ModeProfile:
        return MODE_PROFILES[self.mode]

    def with_(self, **changes: Any) -> ArrangementOptions:
        return replace(self, **changes)

    def density_budget(self, fallback: float = 9.0) -> float:
        """Notes per second the arrangement may use."""
        if isinstance(self.max_density, (int, float)):
            return float(self.max_density)
        base = fallback * self.profile.density_scale
        # complexity 0 -> half the base, 1 -> double it
        return max(1.0, base * (0.5 + 1.5 * max(0.0, min(1.0, self.complexity))))

    def to_dict(self) -> dict[str, Any]:
        def enc(v: Any) -> Any:
            if isinstance(v, Auto):
                return "auto"
            if isinstance(v, Enum):
                return v.value
            return v

        return {k: enc(v) for k, v in asdict(self).items()}

    @staticmethod
    def from_dict(d: dict[str, Any]) -> ArrangementOptions:
        def dec_auto(value: Any, cast: Any = None) -> Any:
            if value is None or value == "auto":
                return AUTO
            return cast(value) if cast else value

        defaults = ArrangementOptions()
        return ArrangementOptions(
            mode=ArrangementMode(d.get("mode", defaults.mode.value)),
            scale=dec_auto(d.get("scale", "auto")),
            transpose=dec_auto(d.get("transpose", "auto"), int),
            quantization=dec_auto(d.get("quantization", "auto")),
            quantization_strength=float(d.get("quantization_strength", d.get("quantizationStrength", defaults.quantization_strength))),
            complexity=float(d.get("complexity", defaults.complexity)),
            preserve_melody=bool(d.get("preserve_melody", d.get("preserveMelody", True))),
            arpeggiate_chords=dec_auto(d.get("arpeggiate_chords", d.get("arpeggiateChords", "auto")), bool),
            max_density=dec_auto(d.get("max_density", d.get("maxDensity", "auto")), float),
            shawzin_variant=str(d.get("shawzin_variant", d.get("shawzinVariant", defaults.shawzin_variant))),
            stem_source=StemSource(d.get("stem_source", d.get("stemSource", defaults.stem_source.value))),
            transpose_search=int(d.get("transpose_search", d.get("transposeSearch", defaults.transpose_search))),
            min_repeat_ticks=int(d.get("min_repeat_ticks", d.get("minRepeatTicks", defaults.min_repeat_ticks))),
            lead_in_ticks=dec_auto(d.get("lead_in_ticks", d.get("leadInTicks", "auto")), int),
            seed=int(d.get("seed", 0)),
        )


@dataclass
class ResolvedOptions:
    """What AUTO actually resolved to, reported alongside the result."""

    mode: str
    scale_id: str
    scale_name: str
    transpose: int
    quantization: str
    quantization_strength: float
    max_density: float
    arpeggiate_chords: bool
    lead_in_ticks: int
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "scaleId": self.scale_id,
            "scaleName": self.scale_name,
            "transpose": self.transpose,
            "quantization": self.quantization,
            "quantizationStrength": round(self.quantization_strength, 3),
            "maxDensity": round(self.max_density, 3),
            "arpeggiateChords": self.arpeggiate_chords,
            "leadInTicks": self.lead_in_ticks,
            "detail": self.detail,
        }
