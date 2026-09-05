/** The headline result: original vs optimized, and what drove it. */

import { motion } from 'framer-motion';
import type { ArrangementDto } from '@shawzify/shared-types';

import { MeterRow, Panel } from './primitives';

function BigNumber({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: 'dim' | 'amber';
}) {
  return (
    <div className="flex-1 min-w-0">
      <div className="label mb-1">{label}</div>
      <motion.div
        key={`${label}-${value.toFixed(1)}`}
        // Deliberately not a fade. An opacity animation that never runs -- a
        // background tab where requestAnimationFrame is throttled, a headless
        // render -- leaves the score invisible, and the score is the point of
        // the panel. Movement is decoration; the number must always be drawn.
        initial={{ y: 6, scale: 0.97 }}
        animate={{ y: 0, scale: 1 }}
        transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
        className={`text-[2.75rem] leading-none font-semibold tabular-nums tracking-[-0.03em] ${
          tone === 'amber' ? 'text-amber' : 'text-paper-faint'
        }`}
      >
        {value.toFixed(0)}
        <span className="text-2xl align-top ml-0.5">%</span>
      </motion.div>
    </div>
  );
}

export function Compatibility({
  arrangement,
  advanced,
  onScalePick,
}: {
  arrangement: ArrangementDto;
  advanced: boolean;
  onScalePick?: (scaleId: string, transpose: number) => void;
}) {
  const { report } = arrangement;
  const before = report.compatibilityBefore;
  const after = report.compatibilityAfter;
  const gain = after.overall - before.overall;

  return (
    <Panel title="Shawzin Compatibility">
      <div className="flex items-start gap-6">
        <BigNumber label="Original" value={before.overall} tone="dim" />
        <div className="pt-6 shrink-0">
          <motion.svg
            width="22"
            height="12"
            viewBox="0 0 22 12"
            initial={{ opacity: 0, x: -4 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: 0.1 }}
          >
            <path
              d="M0 6h18m0 0-4.5-4.5M18 6l-4.5 4.5"
              fill="none"
              stroke="rgba(232,168,76,0.55)"
              strokeWidth="1.4"
              strokeLinecap="round"
            />
          </motion.svg>
        </div>
        <BigNumber label="Optimized" value={after.overall} tone="amber" />
      </div>

      {gain > 0.5 && (
        <div className="mt-1 text-2xs text-paper-faint">
          +{gain.toFixed(1)} points from the arrangement engine
        </div>
      )}

      <div className="mt-5 space-y-2">
        <MeterRow label="Pitch Coverage" value={after.pitch_coverage} />
        <MeterRow label="Melody Preservation" value={after.melody_preservation} />
        <MeterRow label="Rhythm Preservation" value={after.rhythm_preservation} />
        <MeterRow label="Harmony Preservation" value={after.harmony_preservation} />
      </div>

      <div className="mt-5 pt-4 border-t divider grid grid-cols-2 gap-4">
        <div>
          <div className="label mb-1">Recommended Scale</div>
          <div className="text-base font-medium text-paper">{report.scaleName}</div>
        </div>
        <div>
          <div className="label mb-1">Transpose</div>
          <div className="text-base font-medium tabular-nums text-paper">
            {report.transpose > 0 ? '+' : ''}
            {report.transpose} semitone{Math.abs(report.transpose) === 1 ? '' : 's'}
          </div>
        </div>
      </div>

      {advanced && report.scaleCandidates.length > 1 && (
        <div className="mt-5 pt-4 border-t divider">
          <div className="label mb-2">Other scales considered</div>
          <div className="space-y-1">
            {report.scaleCandidates.map((candidate) => {
              const current = candidate.scaleId === report.scaleId;
              return (
                <button
                  key={candidate.scaleId}
                  type="button"
                  disabled={current}
                  onClick={() => onScalePick?.(candidate.scaleId, candidate.transpose)}
                  className={`w-full flex items-center gap-3 px-2 h-7 rounded-md text-xs
                    transition-colors ${
                      current
                        ? 'bg-amber/[0.12] text-amber-bright'
                        : 'text-paper-dim hover:bg-white/[0.05] hover:text-paper'
                    }`}
                >
                  <span className="flex-1 text-left truncate">{candidate.scaleName}</span>
                  <span className="tabular-nums w-10 text-right">
                    {candidate.transpose > 0 ? '+' : ''}
                    {candidate.transpose}
                  </span>
                  <span className="tabular-nums w-12 text-right">
                    {candidate.score.toFixed(1)}
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      )}
    </Panel>
  );
}
