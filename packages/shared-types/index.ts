/**
 * Types shared between the Rust shell, the Python engine and the UI.
 *
 * These mirror the JSON the engine emits. Keeping them in one package means a
 * change to an engine payload shows up as a TypeScript error rather than as a
 * blank panel at runtime.
 */

// -- errors --------------------------------------------------------------

export interface EngineError {
  code: string;
  message: string;
  hint: string | null;
  technical: string | null;
}

// -- progress ------------------------------------------------------------

export type StageId =
  | 'decode'
  | 'waveform'
  | 'stems'
  | 'analyze'
  | 'transcribe'
  | 'arrange'
  | 'encode';

export interface ProgressPayload {
  stage: StageId;
  label: string;
  stageFraction: number;
  overallFraction: number;
  message: string | null;
}

export interface EngineEvent {
  id: number;
  kind: string;
  payload: ProgressPayload | Record<string, unknown>;
}

// -- music ---------------------------------------------------------------

export interface NoteEventDto {
  pitchMidi: number;
  pitchName: string;
  startSeconds: number;
  durationSeconds: number;
  velocity: number;
  confidence: number;
  source: string;
  voice: number;
}

export interface KeyEstimateDto {
  tonicPitchClass: number;
  tonic: string;
  mode: 'major' | 'minor';
  name: string;
  confidence: number;
  correlation: number;
  runnerUp: string | null;
}

export interface WaveformDto {
  min: number[];
  max: number[];
  rms: number[];
  buckets: number;
  durationSeconds: number;
  sampleRate: number;
}

export interface TrackAnalysisDto {
  durationSeconds: number;
  tempoBpm: number;
  tempoConfidence: number;
  key: string;
  mode: string;
  keyConfidence: number;
  timeSignatureEstimate: string;
  energy: number;
  onsetDensity: number;
  pitchRange: [number, number];
  polyphonyEstimate: number;
  backend: string;
}

export interface AudioMetadataDto {
  path: string;
  filename: string;
  durationSeconds: number;
  sampleRate: number;
  channels: number;
  codec: string | null;
  bitrate: number | null;
  title: string | null;
  artist: string | null;
}

export interface MidiTrackDto {
  index: number;
  name: string;
  noteCount: number;
  channels: number[];
  programs: number[];
  pitchRange: [number, number];
  meanPitch: number;
  isPercussion: boolean;
  durationSeconds: number;
}

export interface SourceDto {
  sourceId: string;
  kind: 'audio' | 'midi';
  title: string;
  durationSeconds: number;
  noteCount: number;
  bpm: number;
  bpmConfidence: number;
  key: KeyEstimateDto | null;
  transcriptionBackend: string;
  stemUsed: string;
  contentHash: string;
  warnings: string[];
  track?: TrackReferenceDto;
  matchConfidence?: number;
  matchReason?: string;
  audio?: AudioMetadataDto;
  analysis?: TrackAnalysisDto;
  waveform?: WaveformDto;
  midi?: { tracks: MidiTrackDto[]; tempoBpm: number; timeSignature: [number, number] };
  events?: NoteEventDto[];
}

// -- Shawzin -------------------------------------------------------------

export interface ShawzinNoteDto {
  fret: string;
  string: string;
  position: string;
  midi: number;
  name: string;
}

export interface ShawzinChordDto {
  fret: string;
  string: string;
  position: string;
  name: string;
  midi: number[];
}

export interface ShawzinScaleDto {
  id: string;
  code: string;
  index: number;
  name: string;
  chordType: string;
  rootPitchClass: number;
  intervals: number[];
  lowestMidi: number;
  highestMidi: number;
  pitchClasses: number[];
  notes: ShawzinNoteDto[];
  chords: ShawzinChordDto[];
}

export interface ShawzinVariantDto {
  id: string;
  name: string;
  polyphony: 'polyphonic' | 'duophonic' | 'monophonic';
  clef: string;
  tuningCents: number;
  noteLengthSeconds: number;
  supportsAltNotes: boolean;
  chordType: string;
}

export interface InstrumentDto {
  baseMidi: number;
  variant: ShawzinVariantDto;
  variants: ShawzinVariantDto[];
  format: {
    ticksPerSecond: number;
    maxSongSeconds: number;
    maxTicks: number;
    maxNotes: number;
    chatLinkMaxNotes: number;
    tickSeconds: number;
  };
  maxSimultaneousStrings: number;
  overallRange: [number, number];
  scales: ShawzinScaleDto[];
}

export interface SongEventDto {
  tick: number;
  fret: string;
  string: string;
  position: string;
}

// -- arrangement ---------------------------------------------------------

export type ArrangementMode = 'melody' | 'balanced' | 'chordal' | 'virtuoso';
export type StemSource =
  | 'auto'
  | 'vocals'
  | 'instrumental'
  | 'full'
  | 'bass'
  | 'drums'
  | 'other';
export type Focus = 'auto' | 'full' | 'hook';

export type QuantizeSetting =
  | 'auto'
  | 'off'
  | '1/4'
  | '1/8'
  | '1/8t'
  | '1/16'
  | '1/16t'
  | '1/32';

export interface ArrangementOptionsDto {
  mode: ArrangementMode;
  scale: string | 'auto';
  transpose: number | 'auto';
  quantization: QuantizeSetting;
  quantizationStrength: number;
  complexity: number;
  preserveMelody: boolean;
  arpeggiateChords: boolean | 'auto';
  maxDensity: number | 'auto';
  shawzinVariant: string;
  stemSource: StemSource;
  focus: Focus;
  useStructure: boolean;
}

export type Operation =
  | 'keep'
  | 'transpose'
  | 'octave_fold'
  | 'quantize'
  | 'arpeggiate'
  | 'remove'
  | 'simplify'
  | 'chord_substitute';

export interface DecisionDto {
  sourceIndex: number;
  operations: Operation[];
  original: { midi: number; name: string; seconds: number };
  output: { midi: number; name: string; seconds: number; position: string } | null;
  pitchDelta: number;
  timingDelta: number;
  reason: string;
  cost: number;
  importance: number;
  removed: boolean;
}

export interface CompatibilityDto {
  pitch_coverage: number;
  melody_preservation: number;
  rhythm_preservation: number;
  harmony_preservation: number;
  overall: number;
}

export interface MetricsDto {
  sourceNotes: number;
  outputNotes: number;
  removedNotes: number;
  movedNotes: number;
  octaveFoldedNotes: number;
  arpeggiatedNotes: number;
  chordSubstitutions: number;
  averagePitchError: number;
  weightedPitchError: number;
  timingErrorMean: number;
  timingErrorMax: number;
  melodyRetention: number;
}

export interface ScaleCandidateDto {
  scaleId: string;
  scaleName: string;
  transpose: number;
  score: number;
  pitchCoverage: number;
  weightedCoverage: number;
  rangeFit: number;
  contourFit: number;
  tonalFit: number;
  meanPitchError: number;
  octaveFolds: number;
}

export interface StageTimingDto {
  stage: string;
  durationSeconds: number;
  success: boolean;
  detail: Record<string, unknown>;
}

export interface ReportDto {
  detectedKey: string | null;
  keyConfidence: number;
  detectedBpm: number | null;
  bpmConfidence: number;
  scaleId: string;
  scaleName: string;
  transpose: number;
  compatibilityBefore: CompatibilityDto;
  compatibilityAfter: CompatibilityDto;
  metrics: MetricsDto;
  warnings: string[];
  durationSeconds: number;
  stageTimings: StageTimingDto[];
  scaleCandidates: ScaleCandidateDto[];
  parts: number;
  engineVersions: Record<string, string | number>;
}

export interface ResolvedOptionsDto {
  mode: string;
  scaleId: string;
  scaleName: string;
  transpose: number;
  quantization: string;
  quantizationStrength: number;
  maxDensity: number;
  arpeggiateChords: boolean;
  leadInTicks: number;
  focus: string;
  focusWindow: [number, number] | null;
  detail: Record<string, number>;
}

export interface PartDto {
  index: number;
  code: string;
  noteCount: number;
  eventCount: number;
  startSeconds: number;
  endSeconds: number;
  durationSeconds: number;
}

export interface PhraseDto {
  index: number;
  startSeconds: number;
  endSeconds: number;
  noteCount: number;
  boundaryStrength: number;
}

export interface LiveEventDto {
  at: number;
  fret: string;
  string: string;
}

export interface ArrangementDto {
  sourceId: string;
  code: string;
  song: { scaleId: string; events: SongEventDto[]; noteCount: number; endTick: number };
  resolved: ResolvedOptionsDto;
  report: ReportDto;
  decisions: DecisionDto[];
  scaleCandidates: ScaleCandidateDto[];
  phrases: PhraseDto[];
  outputNotes: NoteEventDto[];
  liveEvents: LiveEventDto[];
  parts: PartDto[];
  splitReasons: string[];
  tab: string;
  engineVersion: string;
  structure: SongStructureDto | null;
  musicProfile: MusicProfileDto;
  shawzinSuggestions: ShawzinSuggestionDto[];
}

// -- environment / diagnostics ------------------------------------------

export interface BackendInfo {
  id: string;
  name: string;
  available: boolean;
  polyphonic?: boolean;
}

export interface EnvironmentDto {
  app: Record<string, string | number>;
  python: string;
  platform: string;
  ffmpeg: { available: boolean; version: string | null; source: string; hasFfprobe: boolean };
  librosa: boolean;
  gpu: { cuda: boolean; device: string | null; torch: string | null; memoryTotalMb?: number };
  transcribers: BackendInfo[];
  separators: BackendInfo[];
  cacheBytes: number;
  generatedAt: string;
  microphone?: { available: boolean; detail: string };
  warframe?: WarframeStatus;
}

export interface WarframeStatus {
  found: boolean;
  focused: boolean;
  title: string | null;
  supported: boolean;
}

export interface KeymapDto {
  keymap: {
    bindings: Record<string, string>;
    timing: {
      playback_offset_ms: number;
      fret_to_string_ms: number;
      inter_string_ms: number;
      key_hold_ms: number;
      countdown_seconds: number;
    };
  };
  labels: Record<string, string>;
  defaults: Record<string, string>;
  problems: string[];
}

export interface RecentProject {
  title: string;
  path: string;
  sourcePath: string;
  kind: string;
  compatibility: number;
  openedAt: string;
}

export interface LiveTick {
  index: number;
  total: number;
  position_seconds: number;
  fret: string;
  string: string;
}

export interface LiveStats {
  fired: number;
  total: number;
  mean_error_ms: number;
  max_error_ms: number;
  stopped_early: boolean;
  stop_reason: string | null;
}

// -- audio sources -------------------------------------------------------

export interface TrackReferenceDto {
  title: string;
  artist: string;
  album: string;
  durationSeconds: number | null;
  provider: 'local' | 'youtube' | 'spotify' | string;
  sourceId: string;
  url: string;
  artworkUrl: string | null;
  isrc: string | null;
  display: string;
  extra: Record<string, unknown>;
}

export interface SearchCandidateDto {
  reference: TrackReferenceDto;
  score: number;
  reasons: string[];
}

export interface ResolvedSourceDto {
  kind: string;
  reference: TrackReferenceDto;
  path: string | null;
  matchConfidence: number;
  matchReason: string;
  alternatives: SearchCandidateDto[];
  warnings: string[];
}

export interface ProviderInfo {
  id: 'local' | 'youtube' | 'spotify' | string;
  name: string;
  online: boolean;
  available: boolean;
  detail: string;
}

export interface SpotifyCredentialsDto {
  configured: boolean;
  clientId: string;
  available: boolean;
  detail: string;
  hasSecret: boolean;
}

// -- song structure ------------------------------------------------------

export interface SegmentDto {
  index: number;
  startSeconds: number;
  endSeconds: number;
  durationSeconds: number;
  label: number;
  repetitions: number;
  energy: number;
  density: number;
  recognizability: number;
  role: 'intro' | 'verse' | 'chorus' | 'bridge' | 'outro' | 'section' | string;
}

export interface SongStructureDto {
  segments: SegmentDto[];
  hookIndex: number | null;
  hook: SegmentDto | null;
  backend: string;
}

export interface StructureResponse {
  structure: SongStructureDto;
  bestWindow: { startSeconds: number; endSeconds: number };
  hookNotes: NoteEventDto[];
}

// -- Shawzin recommendation ---------------------------------------------

export interface MusicProfileDto {
  notesPerSecond: number;
  peakNotesPerSecond: number;
  meanPolyphony: number;
  maxPolyphony: number;
  chordFraction: number;
  meanGapSeconds: number;
  medianPitch: number;
  lowFraction: number;
  sustainFraction: number;
  noteCount: number;
}

export interface ShawzinSuggestionDto {
  variantId: string;
  name: string;
  score: number;
  polyphony: 'polyphonic' | 'duophonic' | 'monophonic';
  timbre: string;
  reasons: string[];
  warnings: string[];
  notesLost: number;
}
