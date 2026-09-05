/**
 * Arrangement controls.
 *
 * Every change here calls `reArrange`, which re-runs only the arrangement
 * stage -- stems and transcription stay cached, so the result comes back in
 * well under a second.
 */

import type { ArrangementMode, InstrumentDto, QuantizeSetting } from '@shawzify/shared-types';

import { useStore } from '@/state/store';
import { Panel, Segmented, Select, Slider, Toggle } from './primitives';

const MODES: { value: ArrangementMode; label: string; title: string }[] = [
  { value: 'melody', label: 'Melody', title: 'Just the tune, as recognisable as possible' },
  { value: 'balanced', label: 'Balanced', title: 'Melody plus supporting harmony' },
  { value: 'chordal', label: 'Chordal', title: "Uses the Shawzin's chord positions" },
  { value: 'virtuoso', label: 'Virtuoso', title: 'Keeps dense and fast material' },
];

const QUANTIZE: { value: QuantizeSetting; label: string }[] = [
  { value: 'auto', label: 'Auto' },
  { value: 'off', label: 'Off' },
  { value: '1/4', label: '1/4' },
  { value: '1/8', label: '1/8' },
  { value: '1/8t', label: '1/8 triplet' },
  { value: '1/16', label: '1/16' },
  { value: '1/16t', label: '1/16 triplet' },
  { value: '1/32', label: '1/32' },
];

export function Controls({ instrument }: { instrument: InstrumentDto | null }) {
  const { options, reArrange, arranging, arrangement, advanced, setAdvanced } = useStore();

  const scaleOptions = [
    { value: 'auto', label: 'Auto' },
    ...(instrument?.scales.map((s) => ({ value: s.id, label: s.name })) ?? []),
  ];
  const transposeOptions = [
    { value: 'auto', label: 'Auto' },
    ...Array.from({ length: 25 }, (_, i) => i - 12).map((n) => ({
      value: String(n),
      label: n === 0 ? '0' : n > 0 ? `+${n}` : String(n),
    })),
  ];
  const variantOptions =
    instrument?.variants.map((v) => ({
      value: v.id,
      label: `${v.name} · ${v.polyphony}`,
    })) ?? [];

  return (
    <Panel
      title="Arrangement"
      action={
        <button
          type="button"
          className="text-2xs text-paper-faint hover:text-paper transition-colors"
          onClick={() => setAdvanced(!advanced)}
        >
          {advanced ? 'Simple' : 'Advanced'}
        </button>
      }
    >
      <div className={`space-y-5 ${arranging ? 'opacity-60 pointer-events-none' : ''}`}>
        <Segmented
          label="Mode"
          options={MODES}
          value={options.mode}
          onChange={(mode) => void reArrange({ mode })}
        />

        <Slider
          label="Complexity"
          value={Math.round(options.complexity * 100)}
          min={0}
          max={100}
          onChange={(v) => void reArrange({ complexity: v / 100 })}
          format={(v) => `${v}%`}
        />

        <div className="grid grid-cols-2 gap-3">
          <Select
            label="Scale"
            value={String(options.scale)}
            options={scaleOptions}
            onChange={(scale) => void reArrange({ scale })}
          />
          <Select
            label="Transpose"
            value={String(options.transpose)}
            options={transposeOptions}
            onChange={(t) => void reArrange({ transpose: t === 'auto' ? 'auto' : Number(t) })}
          />
        </div>

        <div className="space-y-3">
          <Toggle
            label="Preserve melody"
            hint="Protects the main tune from density reduction"
            checked={options.preserveMelody}
            onChange={(preserveMelody) => void reArrange({ preserveMelody })}
          />
          <Toggle
            label="Arpeggiate chords"
            hint={
              options.arpeggiateChords === 'auto'
                ? `Auto — currently ${arrangement?.resolved.arpeggiateChords ? 'on' : 'off'}`
                : 'Spreads unplayable chords over time'
            }
            checked={
              options.arpeggiateChords === 'auto'
                ? Boolean(arrangement?.resolved.arpeggiateChords)
                : options.arpeggiateChords
            }
            onChange={(v) => void reArrange({ arpeggiateChords: v })}
          />
        </div>

        {advanced && (
          <div className="pt-4 border-t divider space-y-5">
            <div className="grid grid-cols-2 gap-3">
              <Select
                label="Quantization"
                value={options.quantization}
                options={QUANTIZE}
                onChange={(quantization) => void reArrange({ quantization })}
              />
              <Slider
                label="Quantize strength"
                value={Math.round(options.quantizationStrength * 100)}
                min={0}
                max={100}
                disabled={options.quantization === 'off'}
                onChange={(v) => void reArrange({ quantizationStrength: v / 100 })}
                format={(v) => `${v}%`}
              />
            </div>

            <Slider
              label="Max density"
              value={
                options.maxDensity === 'auto'
                  ? Math.round(arrangement?.resolved.maxDensity ?? 8)
                  : Math.round(options.maxDensity)
              }
              min={2}
              max={16}
              onChange={(v) => void reArrange({ maxDensity: v })}
              format={(v) => `${v} notes/sec`}
            />
            <button
              type="button"
              className="text-2xs text-paper-faint hover:text-paper"
              onClick={() => void reArrange({ maxDensity: 'auto' })}
              disabled={options.maxDensity === 'auto'}
            >
              Reset density to Auto
            </button>

            {variantOptions.length > 0 && (
              <Select
                label="Shawzin"
                value={options.shawzinVariant}
                options={variantOptions}
                onChange={(shawzinVariant) => void reArrange({ shawzinVariant })}
              />
            )}

            {arrangement && (
              <div className="pt-3 border-t divider text-2xs text-paper-faint space-y-1">
                <div className="flex justify-between">
                  <span>Resolved quantization</span>
                  <span className="text-paper-dim">{arrangement.resolved.quantization}</span>
                </div>
                <div className="flex justify-between">
                  <span>Density budget</span>
                  <span className="text-paper-dim">
                    {arrangement.resolved.maxDensity.toFixed(1)} n/s
                  </span>
                </div>
                <div className="flex justify-between">
                  <span>Source density</span>
                  <span className="text-paper-dim">
                    {(arrangement.resolved.detail.observedDensity ?? 0).toFixed(1)} n/s
                  </span>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </Panel>
  );
}
