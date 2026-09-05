/**
 * Waveform + phrase markers, drawn on a canvas.
 *
 * The peaks arrive pre-bucketed from the engine, so this only has to scale
 * them; there is never a million-sample array in the renderer.
 */

import { useEffect, useMemo, useRef } from 'react';
import type { NoteEventDto, PhraseDto, WaveformDto } from '@shawzify/shared-types';

import { formatTime } from './primitives';

interface Props {
  waveform: WaveformDto | null;
  duration: number;
  playhead: number;
  phrases?: PhraseDto[];
  onSeek?: (seconds: number) => void;
  height?: number;
  /**
   * Used when there is no waveform -- a MIDI file has no audio, so the strip
   * shows note activity over time instead of an empty box.
   */
  events?: NoteEventDto[];
}

/** Phrase boundaries: where the engine would cut the song for splitting. */
function drawPhrases(
  ctx: CanvasRenderingContext2D,
  width: number,
  height: number,
  phrases: PhraseDto[],
  duration: number,
): void {
  if (duration <= 0 || phrases.length < 2) return;
  ctx.strokeStyle = 'rgba(90,200,216,0.32)';
  ctx.setLineDash([2, 3]);
  for (const phrase of phrases.slice(1)) {
    const x = (phrase.startSeconds / duration) * width;
    ctx.beginPath();
    ctx.moveTo(x, 4);
    ctx.lineTo(x, height - 4);
    ctx.stroke();
  }
  ctx.setLineDash([]);
}

/** Per-bucket note activity: sum of velocities of notes sounding in each slice. */
function noteEnvelope(events: NoteEventDto[], duration: number, buckets: number): number[] {
  const out = new Array<number>(buckets).fill(0);
  if (duration <= 0 || events.length === 0) return out;
  for (const e of events) {
    const from = Math.max(0, Math.floor((e.startSeconds / duration) * buckets));
    const end = e.startSeconds + e.durationSeconds;
    const to = Math.min(buckets - 1, Math.floor((end / duration) * buckets));
    for (let i = from; i <= to; i += 1) out[i] += 0.35 + 0.65 * e.velocity;
  }
  const peak = Math.max(...out, 1);
  return out.map((v) => v / peak);
}

export function Waveform({
  waveform,
  duration,
  playhead,
  phrases = [],
  onSeek,
  height = 84,
  events,
}: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const envelope = useMemo(
    () => (waveform || !events?.length ? null : noteEnvelope(events, duration, 240)),
    [waveform, events, duration],
  );

  useEffect(() => {
    const canvas = canvasRef.current;
    const wrap = wrapRef.current;
    if (!canvas || !wrap) return;

    const draw = () => {
      const dpr = window.devicePixelRatio || 1;
      const width = wrap.clientWidth;
      canvas.width = Math.max(1, Math.floor(width * dpr));
      canvas.height = Math.max(1, Math.floor(height * dpr));
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;

      const ctx = canvas.getContext('2d');
      if (!ctx) return;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, width, height);

      const mid = height / 2;

      // Centre line, so silence still reads as "there is a track here".
      ctx.strokeStyle = 'rgba(255,255,255,0.06)';
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(0, mid);
      ctx.lineTo(width, mid);
      ctx.stroke();

      if (!waveform || waveform.max.length === 0) {
        // No audio: draw note activity, mirrored so it still reads as a strip.
        if (envelope) {
          const step = width / envelope.length;
          ctx.fillStyle = 'rgba(232,168,76,0.45)';
          for (let i = 0; i < envelope.length; i += 1) {
            const h = Math.max(0.8, envelope[i] * mid * 0.9);
            ctx.fillRect(i * step, mid - h, Math.max(0.8, step - 0.4), h * 2);
          }
        }
        drawPhrases(ctx, width, height, phrases, duration);
        return;
      }

      const buckets = waveform.max.length;
      const step = width / buckets;

      // RMS body first (soft), then the peak envelope on top.
      ctx.fillStyle = 'rgba(232,168,76,0.20)';
      for (let i = 0; i < buckets; i += 1) {
        const r = waveform.rms[i] ?? 0;
        const h = Math.max(0.7, r * mid * 1.9);
        ctx.fillRect(i * step, mid - h, Math.max(0.8, step - 0.35), h * 2);
      }
      ctx.fillStyle = 'rgba(232,168,76,0.62)';
      for (let i = 0; i < buckets; i += 1) {
        const top = (waveform.max[i] ?? 0) * mid;
        const bottom = (waveform.min[i] ?? 0) * mid;
        const y = mid - Math.max(top, 0.4);
        const h = Math.max(0.8, top - bottom) || 1;
        ctx.fillRect(i * step, y, Math.max(0.7, step - 0.5), h);
      }

      drawPhrases(ctx, width, height, phrases, duration);
    };

    draw();
    const observer = new ResizeObserver(draw);
    observer.observe(wrap);
    return () => observer.disconnect();
  }, [waveform, envelope, phrases, duration, height]);

  const ratio = duration > 0 ? Math.max(0, Math.min(1, playhead / duration)) : 0;

  const handleSeek = (event: React.MouseEvent<HTMLDivElement>) => {
    if (!onSeek || duration <= 0) return;
    const rect = event.currentTarget.getBoundingClientRect();
    const x = (event.clientX - rect.left) / rect.width;
    onSeek(Math.max(0, Math.min(duration, x * duration)));
  };

  return (
    <div
      ref={wrapRef}
      className="relative w-full select-none"
      style={{ height }}
      onClick={handleSeek}
      role={onSeek ? 'slider' : undefined}
      aria-label={onSeek ? 'Seek' : undefined}
      aria-valuemin={0}
      aria-valuemax={Math.round(duration)}
      aria-valuenow={Math.round(playhead)}
      tabIndex={onSeek ? 0 : undefined}
      onKeyDown={(e) => {
        if (!onSeek) return;
        if (e.key === 'ArrowRight') onSeek(Math.min(duration, playhead + 5));
        if (e.key === 'ArrowLeft') onSeek(Math.max(0, playhead - 5));
      }}
    >
      <canvas ref={canvasRef} className="block w-full" />
      <div
        className="absolute top-0 bottom-0 w-px bg-paper/80 pointer-events-none"
        style={{ left: `${ratio * 100}%` }}
      >
        <div className="absolute -top-0.5 -left-[3px] w-[7px] h-[7px] rounded-full bg-paper" />
      </div>
      <div className="absolute bottom-0 left-0 text-2xs text-paper-faint tabular-nums">
        {formatTime(playhead)}
      </div>
      <div className="absolute bottom-0 right-0 text-2xs text-paper-faint tabular-nums">
        {formatTime(duration)}
      </div>
    </div>
  );
}
