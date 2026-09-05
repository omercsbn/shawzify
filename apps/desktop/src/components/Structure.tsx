/**
 * Song structure: where the sections are and which one is the hook.
 *
 * The practical point is the Focus control. A song over four minutes cannot be
 * one Shawzin code, and the first four minutes are rarely the memorable ones --
 * so Focus on the Hook arranges the window around the chorus instead.
 */

import { motion } from 'framer-motion';
import type { SegmentDto, SongStructureDto } from '@shawzify/shared-types';

import { useStore } from '@/state/store';
import { Panel, Segmented, formatTime } from './primitives';

const ROLE_COLOR: Record<string, string> = {
  intro: 'rgba(255,255,255,0.10)',
  verse: 'rgba(232,168,76,0.34)',
  chorus: 'rgba(232,168,76,0.80)',
  bridge: 'rgba(90,200,216,0.32)',
  outro: 'rgba(255,255,255,0.10)',
  section: 'rgba(255,255,255,0.16)',
};

/** A horizontal band of the whole song, one block per section. */
export function StructureBar({
  structure,
  duration,
  playhead,
  onSeek,
  focusWindow,
}: {
  structure: SongStructureDto;
  duration: number;
  playhead?: number;
  onSeek?: (seconds: number) => void;
  focusWindow?: [number, number] | null;
}) {
  if (!structure.segments.length || duration <= 0) return null;
  return (
    <div className="relative">
      <div className="flex h-6 rounded-md overflow-hidden gap-px">
        {structure.segments.map((s: SegmentDto) => {
          const width = ((s.endSeconds - s.startSeconds) / duration) * 100;
          const isHook = s.index === structure.hookIndex;
          return (
            <button
              key={s.index}
              type="button"
              title={`${s.role} · ${formatTime(s.startSeconds)}–${formatTime(s.endSeconds)} · ${Math.round(
                s.recognizability * 100,
              )}% recognisable${s.repetitions > 1 ? ` · repeats ${s.repetitions}×` : ''}`}
              onClick={() => onSeek?.(s.startSeconds)}
              className="relative group transition-opacity hover:opacity-80"
              style={{ width: `${width}%`, background: ROLE_COLOR[s.role] ?? ROLE_COLOR.section }}
            >
              {isHook && (
                <span className="absolute inset-0 border border-amber-bright/70 rounded-[2px]" />
              )}
              {width > 7 && (
                <span className="absolute inset-0 flex items-center justify-center text-[9px] uppercase tracking-wider text-ink-900/80 font-medium">
                  {s.role}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {focusWindow && (
        <div
          className="absolute -top-1 -bottom-1 border-x-2 border-amber-bright/70 pointer-events-none rounded-sm"
          style={{
            left: `${(focusWindow[0] / duration) * 100}%`,
            width: `${((focusWindow[1] - focusWindow[0]) / duration) * 100}%`,
          }}
        />
      )}

      {playhead !== undefined && (
        <div
          className="absolute top-0 bottom-0 w-px bg-paper pointer-events-none"
          style={{ left: `${Math.max(0, Math.min(1, playhead / duration)) * 100}%` }}
        />
      )}
    </div>
  );
}

export function StructurePanel({
  structure,
  duration,
  focusWindow,
  overLimit,
  onSeek,
}: {
  structure: SongStructureDto | null;
  duration: number;
  focusWindow: [number, number] | null;
  overLimit: boolean;
  onSeek?: (seconds: number) => void;
}) {
  const { options, reArrange, arranging } = useStore();
  if (!structure || structure.segments.length < 2) return null;

  const hook = structure.hook;
  const focus = options.focus === 'auto' ? 'full' : options.focus;

  return (
    <Panel
      title="Song Structure"
      action={
        hook && (
          <span className="text-2xs text-paper-faint">
            hook at {formatTime(hook.startSeconds)}
          </span>
        )
      }
    >
      <StructureBar
        structure={structure}
        duration={duration}
        focusWindow={focusWindow}
        onSeek={onSeek}
      />

      <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1">
        {['intro', 'verse', 'chorus', 'bridge'].map((role) => (
          <span key={role} className="inline-flex items-center gap-1.5 text-2xs text-paper-faint">
            <span
              className="w-2.5 h-2.5 rounded-[2px]"
              style={{ background: ROLE_COLOR[role] }}
            />
            {role}
          </span>
        ))}
      </div>

      <div className="mt-4 pt-3 border-t divider">
        <Segmented
          label="Focus"
          value={focus}
          options={[
            { value: 'full', label: 'Full Song', title: 'Arrange the whole track' },
            {
              value: 'hook',
              label: 'Hook Only',
              title: 'Arrange the most recognisable four minutes',
            },
          ]}
          onChange={(v) => void reArrange({ focus: v as 'full' | 'hook' })}
        />
        <p className="mt-2 text-2xs text-paper-faint leading-relaxed">
          {focus === 'hook' && focusWindow ? (
            <>
              Arranging {formatTime(focusWindow[0])}–{formatTime(focusWindow[1])}, the stretch a
              listener is most likely to recognise.
            </>
          ) : overLimit ? (
            <span className="text-amber">
              This song is longer than the Shawzin allows, so it will be split into parts.
              Hook Only fits the memorable part into a single code instead.
            </span>
          ) : (
            'The whole song fits, so nothing is being left out.'
          )}
        </p>
        {arranging && (
          <motion.p
            className="mt-1 text-2xs text-paper-faint"
            animate={{ opacity: [1, 0.4, 1] }}
            transition={{ duration: 1.1, repeat: Infinity }}
          >
            Rearranging…
          </motion.p>
        )}
      </div>
    </Panel>
  );
}
