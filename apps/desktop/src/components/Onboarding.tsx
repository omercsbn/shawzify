/** First launch: what this is, and whether the machine is ready for it. */

import { motion } from 'framer-motion';
import { useStore } from '@/state/store';

const POINTS = [
  'Runs entirely on your machine',
  'Supports audio and MIDI',
  'Adapts notes the Shawzin cannot reach',
  'Export a song code, or play it live in Warframe',
];

export function Onboarding() {
  const { environment, engineReady, engineMessage, setOnboarded } = useStore();

  const checks = environment
    ? [
        {
          label: 'Audio engine',
          value: engineReady ? 'Ready' : (engineMessage ?? 'Starting…'),
          ok: engineReady,
        },
        {
          label: 'FFmpeg',
          value: environment.ffmpeg.available
            ? `Installed (${environment.ffmpeg.source})`
            : 'Not found — MIDI still works',
          ok: environment.ffmpeg.available,
        },
        {
          label: 'GPU acceleration',
          value: environment.gpu.cuda
            ? (environment.gpu.device ?? 'CUDA')
            : 'CPU mode',
          ok: true,
        },
        {
          label: 'Transcription',
          value:
            environment.transcribers.find((t) => t.available)?.name ?? 'Unavailable',
          ok: environment.transcribers.some((t) => t.available),
        },
        {
          label: 'Stem separation',
          value: environment.separators.find((s) => s.available && s.id !== 'none')
            ? 'Demucs ready'
            : 'Unavailable — full mix will be used',
          ok: Boolean(environment.separators.find((s) => s.available && s.id !== 'none')),
        },
      ]
    : [];

  return (
    <div className="h-full flex items-center justify-center px-8">
      <motion.div
        className="w-full max-w-md"
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.45, ease: [0.22, 1, 0.36, 1] }}
      >
        <div className="flex items-center gap-3">
          <svg width="30" height="30" viewBox="0 0 48 48" aria-hidden="true">
            <g stroke="rgba(232,168,76,0.35)" strokeWidth="1.6" strokeLinecap="round">
              <line x1="16" y1="6" x2="16" y2="42" />
              <line x1="24" y1="6" x2="24" y2="42" />
              <line x1="32" y1="6" x2="32" y2="42" />
            </g>
            <path
              d="M24 13c5 0 9 3.2 9 7.4 0 5.4-5.2 11.6-9 14.6-3.8-3-9-9.2-9-14.6C15 16.2 19 13 24 13z"
              fill="#E8A84C"
            />
          </svg>
          <h1 className="text-2xl font-semibold tracking-[-0.02em]">SHAWZIFY</h1>
        </div>

        <p className="mt-4 text-sm text-paper-dim leading-relaxed">
          Turn songs into playable Shawzin arrangements.
        </p>

        <ul className="mt-5 space-y-2">
          {POINTS.map((point) => (
            <li key={point} className="flex items-center gap-2.5 text-sm text-paper-dim">
              <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">
                <path
                  d="M2.5 6.4 4.8 8.7 9.5 3.6"
                  fill="none"
                  stroke="#E8A84C"
                  strokeWidth="1.6"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
              {point}
            </li>
          ))}
        </ul>

        <div className="mt-7 surface p-4">
          <div className="label mb-3">Environment check</div>
          {checks.length === 0 ? (
            <div className="text-xs text-paper-faint">Checking…</div>
          ) : (
            <div className="space-y-2">
              {checks.map((check) => (
                <div key={check.label} className="flex items-center gap-2.5 text-xs">
                  <span
                    className={`w-1.5 h-1.5 rounded-full shrink-0 ${
                      check.ok ? 'bg-amber' : 'bg-paper-faint'
                    }`}
                  />
                  <span className="flex-1 text-paper-dim">{check.label}</span>
                  <span className="text-paper truncate max-w-[12rem] text-right">
                    {check.value}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>

        <button
          type="button"
          className="btn-primary w-full mt-6 h-10"
          onClick={() => setOnboarded(true)}
        >
          Get Started
        </button>

        <p className="mt-5 text-2xs text-paper-faint leading-relaxed text-center">
          SHAWZIFY is an independent fan-made tool and is not affiliated with or endorsed by
          Digital Extremes.
        </p>
      </motion.div>
    </div>
  );
}
