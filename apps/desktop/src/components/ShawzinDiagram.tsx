/**
 * An abstract Shawzin: three strings, three frets.
 *
 * Deliberately schematic rather than a recreation of the in-game instrument --
 * it shows what is being pressed, which is what a player watching along needs.
 */

import { motion } from 'framer-motion';

const FRET_LABELS: Record<string, string> = { '1': 'Sky', '2': 'Earth', '3': 'Water' };

export function ShawzinDiagram({
  fret,
  strings,
  noteNames = [],
  compact = false,
}: {
  fret: string;
  strings: string;
  noteNames?: string[];
  compact?: boolean;
}) {
  const heldFrets = fret === '0' || !fret ? [] : fret.split('');
  const pluckedStrings = strings ? strings.split('') : [];
  const stringHeight = compact ? 44 : 60;

  return (
    <div className="flex items-stretch gap-4">
      <div className="flex flex-col justify-between py-1">
        {['1', '2', '3'].map((f) => {
          const held = heldFrets.includes(f);
          return (
            <div key={f} className="flex items-center gap-2">
              <motion.span
                className={`w-6 h-6 rounded-md border flex items-center justify-center text-2xs font-medium ${
                  held
                    ? 'bg-amber/20 border-amber/60 text-amber-bright'
                    : 'bg-white/[0.03] border-white/[0.08] text-paper-faint'
                }`}
                animate={{ scale: held ? 1.08 : 1 }}
                transition={{ type: 'spring', stiffness: 600, damping: 26 }}
              >
                {f}
              </motion.span>
              {!compact && (
                <span
                  className={`text-2xs ${held ? 'text-amber-bright' : 'text-paper-faint'}`}
                >
                  {FRET_LABELS[f]}
                </span>
              )}
            </div>
          );
        })}
      </div>

      <div className="flex-1 relative" style={{ minHeight: stringHeight }}>
        {['1', '2', '3'].map((s, i) => {
          const plucked = pluckedStrings.includes(s);
          const top = (i / 2) * (stringHeight - 2);
          return (
            <div key={s} className="absolute left-0 right-0" style={{ top }}>
              <div className="flex items-center gap-2">
                <span
                  className={`text-2xs w-3 tabular-nums ${
                    plucked ? 'text-amber-bright' : 'text-paper-faint'
                  }`}
                >
                  {s}
                </span>
                <div className="flex-1 relative h-[2px]">
                  <div
                    className={`absolute inset-0 rounded-full ${
                      plucked ? 'bg-amber' : 'bg-white/[0.09]'
                    }`}
                  />
                  {plucked && (
                    <motion.div
                      className="absolute inset-0 rounded-full bg-amber-bright"
                      initial={{ opacity: 1, scaleY: 3 }}
                      animate={{ opacity: 0, scaleY: 1 }}
                      transition={{ duration: 0.35 }}
                      key={`${s}-${noteNames.join()}`}
                    />
                  )}
                </div>
                {plucked && noteNames[pluckedStrings.indexOf(s)] && (
                  <span className="text-2xs font-mono text-amber-bright w-14 truncate">
                    {noteNames[pluckedStrings.indexOf(s)]}
                  </span>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
