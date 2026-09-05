"""Audio ingestion and analysis."""

from .analysis import TrackAnalysis, analyze_audio_buffer
from .decode import AudioBuffer, AudioMetadata, load_audio
from .ffmpeg import find_ffmpeg
from .waveform import compute_peaks

__all__ = [
    "AudioBuffer",
    "AudioMetadata",
    "load_audio",
    "TrackAnalysis",
    "analyze_audio_buffer",
    "compute_peaks",
    "find_ffmpeg",
]
