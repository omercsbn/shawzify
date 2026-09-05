/**
 * Piano roll showing the source against the arrangement.
 *
 * Colour is the whole point of this view:
 *   dim grey  - a source note the Shawzin does not play
 *   amber     - played as written
 *   deep amber- moved (octave folded or snapped to the nearest scale note)
 *   cyan      - spread into an arpeggio
 *   red x     - removed
 * Hovering a note explains what happened to it and why.
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import type { ArrangementDto, DecisionDto, NoteEventDto } from '@shawzify/shared-types';

interface Props {
  arrangement: ArrangementDto | null;
  sourceEvents: NoteEventDto[];
  duration: number;
  playhead: number;
  onSeek?: (seconds: number) => void;
  onSelect?: (index: number | null) => void;
  selected: number | null;
  /** Minimum drawing height; the roll fills its container beyond this. */
  minHeight?: number;
}

interface Marker {
  index: number;
  x: number;
  y: number;
  w: number;
  kind: 'kept' | 'moved' | 'arpeggiated' | 'removed' | 'chord';
  decision: DecisionDto;
}

const COLORS: Record<Marker['kind'], string> = {
  kept: 'rgba(232,168,76,0.92)',
  moved: 'rgba(180,124,46,0.95)',
  arpeggiated: 'rgba(90,200,216,0.9)',
  chord: 'rgba(245,194,117,0.95)',
  removed: 'rgba(210,90,90,0.5)',
};

const LEGEND: { kind: Marker['kind']; label: string }[] = [
  { kind: 'kept', label: 'Played as written' },
  { kind: 'moved', label: 'Moved to fit' },
  { kind: 'chord', label: 'Shawzin chord' },
  { kind: 'arpeggiated', label: 'Arpeggiated' },
  { kind: 'removed', label: 'Removed' },
];

function classify(decision: DecisionDto): Marker['kind'] {
  if (decision.removed) return 'removed';
  if (decision.operations.includes('arpeggiate')) return 'arpeggiated';
  if (decision.operations.includes('chord_substitute')) return 'chord';
  if (decision.operations.includes('octave_fold') || decision.operations.includes('simplify'))
    return 'moved';
  return 'kept';
}

export function PianoRoll({
  arrangement,
  sourceEvents,
  duration,
  playhead,
  onSeek,
  onSelect,
  selected,
  minHeight = 160,
}: Props) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [width, setWidth] = useState(800);
  const [height, setHeight] = useState(minHeight);
  const [hover, setHover] = useState<Marker | null>(null);
  const markersRef = useRef<Marker[]>([]);

  const range = useMemo(() => {
    const pitches: number[] = [];
    for (const e of sourceEvents) pitches.push(e.pitchMidi);
    for (const d of arrangement?.decisions ?? []) if (d.output) pitches.push(d.output.midi);
    if (pitches.length === 0) return { low: 48, high: 84 };
    const low = Math.min(...pitches) - 2;
    const high = Math.max(...pitches) + 2;
    // Keep at least two octaves visible so a narrow melody is not stretched.
    if (high - low < 24) {
      const centre = (high + low) / 2;
      return { low: Math.round(centre - 12), high: Math.round(centre + 12) };
    }
    return { low, high };
  }, [sourceEvents, arrangement]);

  useEffect(() => {
    const wrap = wrapRef.current;
    if (!wrap) return;
    const measure = () => {
      setWidth(wrap.clientWidth);
      setHeight(Math.max(minHeight, wrap.clientHeight));
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(wrap);
    return () => observer.disconnect();
  }, [minHeight]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.max(1, Math.floor(width * dpr));
    canvas.height = Math.max(1, Math.floor(height * dpr));
    canvas.style.width = `${width}px`;
    canvas.style.height = `${height}px`;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, width, height);

    const span = Math.max(1, range.high - range.low);
    const rowHeight = height / span;
    const secondsToX = (s: number) => (duration > 0 ? (s / duration) * width : 0);
    const pitchToY = (p: number) => height - (p - range.low) * rowHeight - rowHeight;

    // Octave stripes give the eye a pitch reference without a full keyboard.
    for (let p = range.low; p <= range.high; p += 1) {
      if (p % 12 === 0) {
        ctx.fillStyle = 'rgba(255,255,255,0.035)';
        ctx.fillRect(0, pitchToY(p), width, rowHeight);
      }
    }

    // Source notes underneath, so a removed note is still visible as context.
    ctx.fillStyle = 'rgba(255,255,255,0.10)';
    for (const e of sourceEvents) {
      const x = secondsToX(e.startSeconds);
      const w = Math.max(1.5, secondsToX(e.durationSeconds));
      ctx.fillRect(x, pitchToY(e.pitchMidi) + rowHeight * 0.18, w, Math.max(1.4, rowHeight * 0.64));
    }

    const markers: Marker[] = [];
    for (const decision of arrangement?.decisions ?? []) {
      const kind = classify(decision);
      const midi = decision.output?.midi ?? decision.original.midi;
      const seconds = decision.output?.seconds ?? decision.original.seconds;
      const x = secondsToX(seconds);
      const w = Math.max(2.5, secondsToX(0.12));
      const y = pitchToY(midi);
      markers.push({ index: decision.sourceIndex, x, y, w, kind, decision });

      if (kind === 'removed') {
        ctx.strokeStyle = COLORS.removed;
        ctx.lineWidth = 1;
        const cy = y + rowHeight / 2;
        ctx.beginPath();
        ctx.moveTo(x - 2.5, cy - 2.5);
        ctx.lineTo(x + 2.5, cy + 2.5);
        ctx.moveTo(x + 2.5, cy - 2.5);
        ctx.lineTo(x - 2.5, cy + 2.5);
        ctx.stroke();
        continue;
      }

      // A line from where the note was to where it ended up.
      if (decision.pitchDelta !== 0 && decision.output) {
        ctx.strokeStyle = 'rgba(255,255,255,0.13)';
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(x + 1, pitchToY(decision.original.midi) + rowHeight / 2);
        ctx.lineTo(x + 1, y + rowHeight / 2);
        ctx.stroke();
      }

      ctx.fillStyle = COLORS[kind];
      const barHeight = Math.max(2, rowHeight * 0.72);
      ctx.fillRect(x, y + (rowHeight - barHeight) / 2, w, barHeight);

      if (selected === decision.sourceIndex) {
        ctx.strokeStyle = 'rgba(255,255,255,0.9)';
        ctx.lineWidth = 1;
        ctx.strokeRect(x - 1.5, y + (rowHeight - barHeight) / 2 - 1.5, w + 3, barHeight + 3);
      }
    }
    markersRef.current = markers;
  }, [arrangement, sourceEvents, duration, width, height, range, selected]);

  const pick = (event: React.MouseEvent<HTMLDivElement>): Marker | null => {
    const rect = event.currentTarget.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    let best: Marker | null = null;
    let bestDistance = 14;
    for (const marker of markersRef.current) {
      const dx = Math.abs(marker.x + marker.w / 2 - x);
      const dy = Math.abs(marker.y - y);
      const distance = dx + dy * 0.6;
      if (distance < bestDistance) {
        bestDistance = distance;
        best = marker;
      }
    }
    return best;
  };

  const ratio = duration > 0 ? Math.max(0, Math.min(1, playhead / duration)) : 0;

  return (
    <div className="flex flex-col h-full min-h-0">
      <div
        ref={wrapRef}
        className="relative flex-1 min-h-0 overflow-hidden"
        style={{ minHeight }}
        onMouseMove={(e) => setHover(pick(e))}
        onMouseLeave={() => setHover(null)}
        onClick={(e) => {
          const marker = pick(e);
          if (marker) {
            onSelect?.(marker.index);
          } else if (onSeek && duration > 0) {
            const rect = e.currentTarget.getBoundingClientRect();
            onSeek(((e.clientX - rect.left) / rect.width) * duration);
            onSelect?.(null);
          }
        }}
      >
        <canvas ref={canvasRef} className="block" />
        <div
          className="absolute top-0 bottom-0 w-px bg-paper/70 pointer-events-none"
          style={{ left: `${ratio * 100}%` }}
        />
        {hover && (
          <div
            className="absolute z-20 pointer-events-none surface-raised px-2.5 py-2 text-xs shadow-lg max-w-[16rem]"
            style={{
              left: Math.min(Math.max(hover.x - 60, 4), Math.max(4, width - 250)),
              top: Math.max(4, hover.y - 74),
            }}
          >
            <div className="flex items-baseline gap-2">
              <span className="text-paper-dim">Original</span>
              <span className="font-mono text-paper">{hover.decision.original.name}</span>
            </div>
            {hover.decision.output ? (
              <>
                <div className="flex items-baseline gap-2">
                  <span className="text-paper-dim">Mapped</span>
                  <span className="font-mono text-amber-bright">{hover.decision.output.name}</span>
                  <span className="text-2xs text-paper-faint font-mono">
                    {hover.decision.output.position}
                  </span>
                </div>
              </>
            ) : (
              <div className="text-red-300">Not played</div>
            )}
            <div className="mt-1.5 pt-1.5 border-t divider text-paper-dim leading-snug">
              {hover.decision.reason}
            </div>
          </div>
        )}
      </div>
      <div className="flex items-center gap-3 flex-wrap pt-2 shrink-0">
        {LEGEND.map((item) => (
          <span key={item.kind} className="inline-flex items-center gap-1.5 text-2xs text-paper-faint">
            <span
              className="w-2.5 h-2.5 rounded-[2px]"
              style={{ background: COLORS[item.kind] }}
            />
            {item.label}
          </span>
        ))}
      </div>
    </div>
  );
}
