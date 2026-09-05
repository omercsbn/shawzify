/**
 * Which Shawzin to play this on.
 *
 * The eleven variants differ in polyphony, sustain and register, which changes
 * what is playable and what it sounds like. This ranks them for the arrangement
 * in hand and says why -- and selecting one re-arranges against its real
 * constraints, so a monophonic pick actually changes the result.
 */

import { AnimatePresence, motion } from 'framer-motion';
import type { MusicProfileDto, ShawzinSuggestionDto } from '@shawzify/shared-types';

import { useStore } from '@/state/store';
import { Panel } from './primitives';

const POLYPHONY_LABEL: Record<string, string> = {
  polyphonic: '3 notes at once',
  duophonic: '2 notes at once',
  monophonic: '1 note at a time',
};

function ScoreBar({ value }: { value: number }) {
  const pct = Math.max(0, Math.min(100, value));
  return (
    <div className="h-0.5 rounded-full bg-white/[0.07] overflow-hidden">
      <motion.div
        className={`h-full ${pct >= 75 ? 'bg-amber' : pct >= 55 ? 'bg-amber-deep' : 'bg-paper-faint'}`}
        initial={{ width: 0 }}
        animate={{ width: `${pct}%` }}
        transition={{ duration: 0.4, ease: [0.22, 1, 0.36, 1] }}
      />
    </div>
  );
}

export function ShawzinPicker({
  suggestions,
  profile,
  current,
}: {
  suggestions: ShawzinSuggestionDto[];
  profile: MusicProfileDto;
  current: string;
}) {
  const { reArrange, arranging, expandedShawzin, setExpandedShawzin } = useStore();
  if (suggestions.length === 0) return null;

  const best = suggestions[0];
  const currentSuggestion = suggestions.find((s) => s.variantId === current);

  return (
    <Panel
      title="Shawzin"
      action={
        <span className="text-2xs text-paper-faint tabular-nums">
          {profile.notesPerSecond.toFixed(1)} notes/s ·{' '}
          {Math.round(profile.chordFraction * 100)}% chords
        </span>
      }
    >
      {best.variantId !== current && (
        <div className="mb-3 p-2.5 rounded-lg bg-amber/[0.09] border border-amber/25">
          <div className="text-xs text-amber-bright">
            {best.name} suits this better than {currentSuggestion?.name ?? 'the current one'}.
          </div>
          <button
            type="button"
            className="btn-primary h-7 mt-2 text-xs"
            disabled={arranging}
            onClick={() => void reArrange({ shawzinVariant: best.variantId })}
          >
            Use {best.name}
          </button>
        </div>
      )}

      <div className="space-y-1">
        {suggestions.map((s) => {
          const selected = s.variantId === current;
          const expanded = expandedShawzin === s.variantId;
          return (
            <div
              key={s.variantId}
              className={`rounded-lg border transition-colors ${
                selected
                  ? 'border-amber/40 bg-amber/[0.07]'
                  : 'border-transparent hover:bg-white/[0.03]'
              }`}
            >
              <button
                type="button"
                className="w-full text-left px-2.5 py-2"
                onClick={() => setExpandedShawzin(expanded ? null : s.variantId)}
                aria-expanded={expanded}
              >
                <div className="flex items-baseline gap-2">
                  <span
                    className={`flex-1 text-sm truncate ${
                      selected ? 'text-amber-bright' : 'text-paper'
                    }`}
                  >
                    {s.name}
                  </span>
                  {s.notesLost > 0 && (
                    <span className="text-2xs text-red-300 tabular-nums">
                      -{s.notesLost} notes
                    </span>
                  )}
                  <span className="text-xs tabular-nums text-paper-dim w-9 text-right">
                    {s.score.toFixed(0)}
                  </span>
                </div>
                <div className="mt-1.5">
                  <ScoreBar value={s.score} />
                </div>
                <div className="mt-1.5 text-2xs text-paper-faint truncate">
                  {POLYPHONY_LABEL[s.polyphony] ?? s.polyphony} · {s.timbre}
                </div>
              </button>

              <AnimatePresence initial={false}>
                {expanded && (
                  <motion.div
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: 'auto', opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    transition={{ duration: 0.18, ease: [0.22, 1, 0.36, 1] }}
                    className="overflow-hidden"
                  >
                    <div className="px-2.5 pb-2.5 space-y-1">
                      {s.reasons.map((r, i) => (
                        <p key={i} className="text-2xs text-paper-dim leading-relaxed flex gap-1.5">
                          <span className="text-amber shrink-0">+</span>
                          <span>{r}</span>
                        </p>
                      ))}
                      {s.warnings.map((w, i) => (
                        <p key={i} className="text-2xs text-paper-faint leading-relaxed flex gap-1.5">
                          <span className="text-red-300 shrink-0">!</span>
                          <span>{w}</span>
                        </p>
                      ))}
                      {!selected && (
                        <button
                          type="button"
                          className="btn-ghost h-7 mt-1.5 text-xs"
                          disabled={arranging}
                          onClick={() => void reArrange({ shawzinVariant: s.variantId })}
                        >
                          Arrange for this Shawzin
                        </button>
                      )}
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          );
        })}
      </div>
    </Panel>
  );
}
