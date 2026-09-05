/**
 * The main working view: track header, A/B preview, waveform, piano roll,
 * compatibility, controls and export.
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import { motion } from 'framer-motion';

import { ShawzifyError, engine } from '@/lib/ipc';
import { useStore } from '@/state/store';
import { Analyzing } from './Analyzing';
import { Compatibility } from './Compatibility';
import { Controls } from './Controls';
import { Export } from './Export';
import { PianoRoll } from './PianoRoll';
import { Waveform } from './Waveform';
import { EmptyHint, Panel, Skeleton, Stat, formatTime } from './primitives';

function useAudioPreview() {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [ready, setReady] = useState(false);
  const [loading, setLoading] = useState(false);
  const { setPlayhead, setPlaying, playing } = useStore();

  useEffect(() => {
    const audio = new Audio();
    audio.preload = 'auto';
    audioRef.current = audio;
    const onTime = () => setPlayhead(audio.currentTime);
    const onEnd = () => setPlaying(false);
    audio.addEventListener('timeupdate', onTime);
    audio.addEventListener('ended', onEnd);
    return () => {
      audio.pause();
      audio.removeEventListener('timeupdate', onTime);
      audio.removeEventListener('ended', onEnd);
    };
  }, [setPlayhead, setPlaying]);

  const load = async (sourceId: string) => {
    const audio = audioRef.current;
    if (!audio) return;
    setLoading(true);
    setReady(false);
    try {
      const rendered = await engine.preview(sourceId);
      const { convertFileSrc } = await import('@tauri-apps/api/core');
      audio.src = convertFileSrc(rendered.path);
      audio.load();
      setReady(true);
    } finally {
      setLoading(false);
    }
  };

  const toggle = async () => {
    const audio = audioRef.current;
    if (!audio || !ready) return;
    if (audio.paused) {
      await audio.play();
      setPlaying(true);
    } else {
      audio.pause();
      setPlaying(false);
    }
  };

  const seek = (seconds: number) => {
    const audio = audioRef.current;
    if (audio && ready) audio.currentTime = seconds;
    setPlayhead(seconds);
  };

  const stop = () => {
    const audio = audioRef.current;
    if (audio) {
      audio.pause();
      audio.currentTime = 0;
    }
    setPlaying(false);
    setPlayhead(0);
  };

  return { load, toggle, seek, stop, ready, loading, playing };
}

export function Workspace() {
  const {
    source,
    arrangement,
    analyzing,
    arranging,
    progress,
    instrument,
    advanced,
    playhead,
    setPlayhead,
    selectedDecision,
    setSelectedDecision,
    reArrange,
    toast,
    reset,
  } = useStore();

  const preview = useAudioPreview();
  const [previewLoadedFor, setPreviewLoadedFor] = useState<string | null>(null);

  const duration = source?.durationSeconds ?? 0;
  const sourceEvents = useMemo(() => source?.events ?? [], [source]);

  // Space toggles preview, as in every audio tool.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (target && ['INPUT', 'SELECT', 'TEXTAREA'].includes(target.tagName)) return;
      if (e.code === 'Space') {
        e.preventDefault();
        void preview.toggle();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [preview]);

  const loadPreview = async () => {
    if (!arrangement) return;
    try {
      await preview.load(arrangement.sourceId);
      setPreviewLoadedFor(arrangement.code);
    } catch (err) {
      toast('error', (err as ShawzifyError).message);
    }
  };

  if (analyzing || (!source && arranging)) {
    return (
      <Analyzing
        progress={progress}
        title={source?.title ?? 'Loading…'}
      />
    );
  }

  if (!source) {
    return <EmptyHint>Drop an audio or MIDI file to begin.</EmptyHint>;
  }

  const report = arrangement?.report;
  const stale = previewLoadedFor !== null && previewLoadedFor !== arrangement?.code;

  return (
    <div className="h-full flex flex-col min-h-0">
      {/* -- header ------------------------------------------------------ */}
      <header className="shrink-0 px-6 py-3.5 border-b divider flex items-center gap-6">
        <button
          type="button"
          onClick={reset}
          className="text-paper-faint hover:text-paper transition-colors shrink-0"
          title="Back"
          aria-label="Back to home"
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
            <path
              d="M10 3 5 8l5 5"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </button>
        <div className="min-w-0 flex-1">
          <h1 className="text-base font-medium truncate">{source.title}</h1>
          <div className="text-2xs text-paper-faint truncate">
            {source.kind === 'midi' ? 'MIDI' : (source.audio?.codec?.toUpperCase() ?? 'Audio')} ·{' '}
            {source.noteCount.toLocaleString()} source notes ·{' '}
            {source.kind === 'midi' ? 'from file' : `via ${source.transcriptionBackend}`}
            {source.kind !== 'midi' && source.stemUsed !== 'full'
              ? ` · ${source.stemUsed} stem`
              : ''}
          </div>
        </div>
        <div className="flex items-center gap-7 shrink-0">
          <Stat label="Duration" value={formatTime(duration)} />
          <Stat
            label="Tempo"
            value={`${source.bpm.toFixed(0)} BPM`}
            hint={source.bpmConfidence < 0.55 ? 'low confidence' : undefined}
          />
          <Stat
            label="Key"
            value={source.key?.name ?? '—'}
            hint={
              source.key && source.key.confidence < 0.5
                ? `or ${source.key.runnerUp ?? 'unclear'}`
                : undefined
            }
          />
        </div>
      </header>

      {/* -- body -------------------------------------------------------- */}
      <div className="flex-1 min-h-0 grid grid-cols-[1fr_360px] gap-4 p-4">
        <div className="flex flex-col gap-4 min-h-0">
          <Panel dense className="shrink-0">
            <div className="px-4 pt-3.5">
              <Waveform
                waveform={source.waveform ?? null}
                duration={duration}
                playhead={playhead}
                phrases={arrangement?.phrases}
                events={sourceEvents}
                onSeek={preview.seek}
              />
            </div>
            <div className="px-4 py-2.5 flex items-center gap-2 border-t divider mt-2">
              {!preview.ready ? (
                <button
                  type="button"
                  className="btn-ghost"
                  disabled={!arrangement || preview.loading}
                  onClick={() => void loadPreview()}
                >
                  {preview.loading ? 'Rendering preview…' : 'Load Preview'}
                </button>
              ) : (
                <>
                  <button type="button" className="btn-ghost w-24" onClick={() => void preview.toggle()}>
                    {preview.playing ? 'Pause' : 'Play'}
                  </button>
                  <button type="button" className="btn-quiet" onClick={preview.stop}>
                    Stop
                  </button>
                  {stale && (
                    <button
                      type="button"
                      className="btn-quiet text-amber"
                      onClick={() => void loadPreview()}
                    >
                      Re-render for current arrangement
                    </button>
                  )}
                </>
              )}
              <span className="ml-auto text-2xs text-paper-faint">
                Space to play/pause · Esc stops live playback
              </span>
            </div>
          </Panel>

          <Panel title="Arrangement" className="flex-1 min-h-0" dense grow>
            <div className="flex-1 min-h-0 p-4 flex flex-col">
              {arrangement ? (
                <PianoRoll
                  arrangement={arrangement}
                  sourceEvents={sourceEvents}
                  duration={duration}
                  playhead={playhead}
                  onSeek={setPlayhead}
                  onSelect={setSelectedDecision}
                  selected={selectedDecision}
                />
              ) : (
                <Skeleton className="w-full h-full" />
              )}
            </div>
          </Panel>

          {advanced && report && (
            <Panel title="Diagnostics" className="shrink-0">
              <div className="grid grid-cols-4 gap-5">
                <Stat label="Source notes" value={report.metrics.sourceNotes} />
                <Stat label="Played" value={report.metrics.outputNotes} tone="amber" />
                <Stat label="Removed" value={report.metrics.removedNotes} tone="dim" />
                <Stat label="Octave folded" value={report.metrics.octaveFoldedNotes} />
                <Stat label="Arpeggiated" value={report.metrics.arpeggiatedNotes} />
                <Stat label="Chord positions" value={report.metrics.chordSubstitutions} />
                <Stat
                  label="Mean pitch error"
                  value={`${report.metrics.weightedPitchError.toFixed(2)} st`}
                />
                <Stat
                  label="Mean timing shift"
                  value={`${(report.metrics.timingErrorMean * 1000).toFixed(0)} ms`}
                />
              </div>
              {report.stageTimings.length > 0 && (
                <div className="mt-4 pt-3 border-t divider flex flex-wrap gap-x-5 gap-y-1 text-2xs text-paper-faint">
                  {report.stageTimings.map((t) => (
                    <span key={t.stage}>
                      {t.stage} {t.durationSeconds.toFixed(2)}s
                    </span>
                  ))}
                </div>
              )}
            </Panel>
          )}
        </div>

        {/* -- right rail ------------------------------------------------ */}
        <div className="flex flex-col gap-4 min-h-0 scroll-y pr-1 -mr-1 [&>section]:shrink-0">
          {arrangement ? (
            <Compatibility
              arrangement={arrangement}
              advanced={advanced}
              onScalePick={(scale, transpose) => void reArrange({ scale, transpose })}
            />
          ) : (
            <Skeleton className="h-64" />
          )}

          <Controls instrument={instrument} />

          {arrangement && report && report.warnings.length > 0 && (
            <Panel title="Warnings">
              <ul className="space-y-2">
                {report.warnings.map((w, i) => (
                  <li key={i} className="text-xs text-paper-dim leading-relaxed flex gap-2">
                    <span className="text-amber shrink-0">·</span>
                    <span>{w}</span>
                  </li>
                ))}
              </ul>
            </Panel>
          )}

          {arrangement && <Export arrangement={arrangement} source={source} />}

          {selectedDecision !== null && arrangement && (
            <SelectedNote arrangement={arrangement} index={selectedDecision} />
          )}
        </div>
      </div>

      {arranging && (
        <motion.div
          className="absolute top-16 left-1/2 -translate-x-1/2 z-30 surface-raised px-3 h-8
                     flex items-center gap-2 text-xs text-paper-dim shadow-lg"
          initial={{ opacity: 0, y: -8 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -8 }}
        >
          <motion.span
            className="w-1.5 h-1.5 rounded-full bg-amber"
            animate={{ opacity: [1, 0.3, 1] }}
            transition={{ duration: 1.1, repeat: Infinity }}
          />
          Rearranging…
        </motion.div>
      )}
    </div>
  );
}

function SelectedNote({
  arrangement,
  index,
}: {
  arrangement: ReturnType<typeof useStore.getState>['arrangement'];
  index: number;
}) {
  const decision = arrangement?.decisions.find((d) => d.sourceIndex === index);
  const { setSelectedDecision } = useStore();
  if (!decision) return null;
  return (
    <Panel
      title="Note"
      action={
        <button
          type="button"
          className="text-2xs text-paper-faint hover:text-paper"
          onClick={() => setSelectedDecision(null)}
        >
          Close
        </button>
      }
    >
      <div className="grid grid-cols-2 gap-4">
        <Stat label="Original" value={decision.original.name} tone="dim" />
        <Stat
          label="Mapped"
          value={decision.output?.name ?? 'Not played'}
          tone={decision.output ? 'amber' : 'dim'}
          hint={decision.output?.position}
        />
        <Stat
          label="Pitch change"
          value={decision.pitchDelta === 0 ? 'none' : `${decision.pitchDelta > 0 ? '+' : ''}${decision.pitchDelta} st`}
        />
        <Stat
          label="Timing shift"
          value={`${(decision.timingDelta * 1000).toFixed(0)} ms`}
        />
      </div>
      <p className="mt-3 pt-3 border-t divider text-xs text-paper-dim leading-relaxed">
        {decision.reason}
      </p>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {decision.operations.map((op) => (
          <span key={op} className="chip">
            {op.replace(/_/g, ' ')}
          </span>
        ))}
      </div>
    </Panel>
  );
}
