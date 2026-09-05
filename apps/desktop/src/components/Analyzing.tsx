/**
 * The analysis screen.
 *
 * Stages light up as the engine actually reaches them; the bar reflects real
 * weighted progress. Nothing here invents a percentage.
 */

import { motion } from 'framer-motion';
import type { ProgressPayload, StageId } from '@shawzify/shared-types';

const STAGES: { id: StageId; label: string }[] = [
  { id: 'decode', label: 'Loading audio' },
  { id: 'waveform', label: 'Drawing waveform' },
  { id: 'stems', label: 'Separating stems' },
  { id: 'analyze', label: 'Detecting rhythm and key' },
  { id: 'transcribe', label: 'Transcribing notes' },
  { id: 'arrange', label: 'Optimizing arrangement' },
  { id: 'encode', label: 'Encoding performance' },
];

export function Analyzing({
  progress,
  title,
  onCancel,
}: {
  progress: ProgressPayload | null;
  title: string;
  onCancel?: () => void;
}) {
  const currentIndex = progress ? STAGES.findIndex((s) => s.id === progress.stage) : -1;
  const overall = progress ? progress.overallFraction : 0;

  return (
    <div className="h-full flex flex-col items-center justify-center px-8">
      <div className="w-full max-w-sm">
        <div className="text-center">
          <div className="label">Analyzing</div>
          <h2 className="mt-1.5 text-xl font-medium truncate">{title}</h2>
        </div>

        <div className="mt-7 h-[3px] rounded-full bg-white/[0.07] overflow-hidden">
          <motion.div
            className="h-full bg-amber"
            animate={{ width: `${Math.round(overall * 100)}%` }}
            transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
          />
        </div>
        <div className="mt-2 flex justify-between text-2xs text-paper-faint tabular-nums">
          <span>{progress?.message ?? progress?.label ?? 'Starting…'}</span>
          <span>{Math.round(overall * 100)}%</span>
        </div>

        <ul className="mt-7 space-y-2.5">
          {STAGES.map((stage, i) => {
            const done = currentIndex > i;
            const active = currentIndex === i;
            return (
              <li key={stage.id} className="flex items-center gap-3">
                <span className="w-4 h-4 shrink-0 flex items-center justify-center">
                  {done ? (
                    <motion.svg
                      width="12"
                      height="12"
                      viewBox="0 0 12 12"
                      initial={{ scale: 0.6, opacity: 0 }}
                      animate={{ scale: 1, opacity: 1 }}
                    >
                      <path
                        d="M2.5 6.4 4.8 8.7 9.5 3.6"
                        fill="none"
                        stroke="#E8A84C"
                        strokeWidth="1.6"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      />
                    </motion.svg>
                  ) : active ? (
                    <motion.span
                      className="w-1.5 h-1.5 rounded-full bg-amber"
                      animate={{ opacity: [1, 0.25, 1] }}
                      transition={{ duration: 1.3, repeat: Infinity, ease: 'easeInOut' }}
                    />
                  ) : (
                    <span className="w-1.5 h-1.5 rounded-full bg-white/[0.12]" />
                  )}
                </span>
                <span
                  className={`text-sm transition-colors duration-200 ${
                    active ? 'text-paper' : done ? 'text-paper-dim' : 'text-paper-faint'
                  }`}
                >
                  {stage.label}
                </span>
                {active && progress && progress.stageFraction > 0 && progress.stageFraction < 1 && (
                  <span className="ml-auto text-2xs tabular-nums text-paper-faint">
                    {Math.round(progress.stageFraction * 100)}%
                  </span>
                )}
              </li>
            );
          })}
        </ul>

        {onCancel && (
          <div className="mt-7 flex justify-center">
            <button type="button" className="btn-quiet" onClick={onCancel}>
              Cancel
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
