"""Arrangement engine: the part that decides what survives."""

from .arranger import Arrangement, arrange_for_shawzin
from .options import AUTO, ArrangementMode, ArrangementOptions, StemSource
from .report import ConversionReport
from .scale_optimizer import find_best_shawzin_mapping

__all__ = [
    "Arrangement",
    "arrange_for_shawzin",
    "ArrangementOptions",
    "ArrangementMode",
    "StemSource",
    "AUTO",
    "ConversionReport",
    "find_best_shawzin_mapping",
]
