/** Settings: key bindings with a calibration wizard, timing, and diagnostics. */

import { useEffect, useState } from 'react';
import type { EnvironmentDto, KeymapDto } from '@shawzify/shared-types';

import { ShawzifyError, engine, system } from '@/lib/ipc';
import { useStore } from '@/state/store';
import { Panel, Slider, Toggle, formatBytes } from './primitives';

const CALIBRATION_ORDER = [
  'string1',
  'string2',
  'string3',
  'fret1',
  'fret2',
  'fret3',
  'whammy',
  'scale',
] as const;

function keyLabel(event: KeyboardEvent): string | null {
  const key = event.key;
  if (key === ' ') return 'space';
  if (key === 'Escape') return 'escape';
  if (key === 'Tab') return 'tab';
  if (key === 'Enter') return 'enter';
  if (key.startsWith('Arrow')) return key.slice(5).toLowerCase();
  if (key.length === 1) {
    const lower = key.toLowerCase();
    if (/[a-z0-9]/.test(lower)) return lower;
  }
  return null;
}

function Bindings({ keymap, onSave }: { keymap: KeymapDto; onSave: (k: KeymapDto['keymap']) => void }) {
  const [draft, setDraft] = useState(keymap.keymap);
  const [capturing, setCapturing] = useState<string | null>(null);
  const [wizardStep, setWizardStep] = useState<number | null>(null);

  useEffect(() => setDraft(keymap.keymap), [keymap]);

  useEffect(() => {
    if (!capturing) return;
    const onKey = (event: KeyboardEvent) => {
      event.preventDefault();
      event.stopPropagation();
      if (event.key === 'Escape' && wizardStep === null) {
        setCapturing(null);
        return;
      }
      const label = keyLabel(event);
      if (!label) return;
      setDraft((d) => ({ ...d, bindings: { ...d.bindings, [capturing]: label } }));
      if (wizardStep !== null) {
        const next = wizardStep + 1;
        if (next < CALIBRATION_ORDER.length) {
          setWizardStep(next);
          setCapturing(CALIBRATION_ORDER[next]);
        } else {
          setWizardStep(null);
          setCapturing(null);
        }
      } else {
        setCapturing(null);
      }
    };
    window.addEventListener('keydown', onKey, true);
    return () => window.removeEventListener('keydown', onKey, true);
  }, [capturing, wizardStep]);

  const dirty = JSON.stringify(draft) !== JSON.stringify(keymap.keymap);

  return (
    <Panel
      title="Warframe Key Bindings"
      action={
        <button
          type="button"
          className="text-2xs text-paper-faint hover:text-paper"
          onClick={() => {
            setWizardStep(0);
            setCapturing(CALIBRATION_ORDER[0]);
          }}
        >
          Calibrate
        </button>
      }
    >
      {wizardStep !== null && (
        <div className="mb-4 p-3 rounded-lg bg-amber/[0.09] border border-amber/25">
          <div className="text-sm text-amber-bright">
            Press your {keymap.labels[CALIBRATION_ORDER[wizardStep]]} key
          </div>
          <div className="text-2xs text-paper-dim mt-1">
            Step {wizardStep + 1} of {CALIBRATION_ORDER.length}
          </div>
        </div>
      )}

      <div className="space-y-1.5">
        {Object.entries(draft.bindings).map(([action, key]) => (
          <div key={action} className="flex items-center gap-3">
            <span className="flex-1 text-sm text-paper-dim">
              {keymap.labels[action] ?? action}
            </span>
            <button
              type="button"
              className={`font-mono text-xs px-2.5 h-7 rounded-md border transition-colors min-w-[4.5rem]
                ${
                  capturing === action
                    ? 'bg-amber/20 border-amber/60 text-amber-bright'
                    : 'bg-ink-800 border-white/[0.08] text-paper hover:border-white/20'
                }`}
              onClick={() => setCapturing(capturing === action ? null : action)}
            >
              {capturing === action ? 'Press a key…' : key.toUpperCase()}
            </button>
          </div>
        ))}
      </div>

      {keymap.problems.length > 0 && (
        <ul className="mt-3 space-y-1">
          {keymap.problems.map((p, i) => (
            <li key={i} className="text-2xs text-red-300">
              {p}
            </li>
          ))}
        </ul>
      )}

      <div className="mt-4 flex gap-2">
        <button
          type="button"
          className="btn-primary"
          disabled={!dirty}
          onClick={() => onSave(draft)}
        >
          Save Bindings
        </button>
        <button
          type="button"
          className="btn-quiet"
          onClick={() =>
            setDraft((d) => ({ ...d, bindings: { ...keymap.defaults } }))
          }
        >
          Reset to Defaults
        </button>
      </div>
    </Panel>
  );
}

function Timing({ keymap, onSave }: { keymap: KeymapDto; onSave: (k: KeymapDto['keymap']) => void }) {
  const [draft, setDraft] = useState(keymap.keymap.timing);
  useEffect(() => setDraft(keymap.keymap.timing), [keymap]);
  const dirty = JSON.stringify(draft) !== JSON.stringify(keymap.keymap.timing);

  return (
    <Panel title="Latency Calibration">
      <div className="space-y-5">
        <Slider
          label="Playback offset"
          value={draft.playback_offset_ms}
          min={-200}
          max={200}
          step={5}
          onChange={(v) => setDraft({ ...draft, playback_offset_ms: v })}
          format={(v) => `${v > 0 ? '+' : ''}${v} ms`}
        />
        <Slider
          label="Fret to string delay"
          value={draft.fret_to_string_ms}
          min={0}
          max={60}
          step={1}
          onChange={(v) => setDraft({ ...draft, fret_to_string_ms: v })}
          format={(v) => `${v} ms`}
        />
        <Slider
          label="Between strings"
          value={draft.inter_string_ms}
          min={0}
          max={30}
          step={1}
          onChange={(v) => setDraft({ ...draft, inter_string_ms: v })}
          format={(v) => `${v} ms`}
        />
        <Slider
          label="Key hold time"
          value={draft.key_hold_ms}
          min={4}
          max={60}
          step={1}
          onChange={(v) => setDraft({ ...draft, key_hold_ms: v })}
          format={(v) => `${v} ms`}
        />
      </div>
      <p className="mt-4 text-2xs text-paper-faint leading-relaxed">
        If notes land late in game, make the playback offset more negative. If chords sound
        broken, raise the fret-to-string delay.
      </p>
      <button
        type="button"
        className="btn-primary mt-3"
        disabled={!dirty}
        onClick={() => onSave({ ...keymap.keymap, timing: draft })}
      >
        Save Timing
      </button>
    </Panel>
  );
}

function EnvironmentPanel({ environment }: { environment: EnvironmentDto | null }) {
  const { toast } = useStore();
  const [busy, setBusy] = useState(false);

  const rows: { label: string; value: string; ok: boolean }[] = environment
    ? [
        {
          label: 'FFmpeg',
          value: environment.ffmpeg.available
            ? `Installed (${environment.ffmpeg.source})`
            : 'Not found',
          ok: environment.ffmpeg.available,
        },
        { label: 'Python engine', value: `Ready ${environment.python}`, ok: true },
        {
          label: 'GPU',
          value: environment.gpu.cuda
            ? `CUDA · ${environment.gpu.device}`
            : 'CPU mode (no CUDA)',
          ok: true,
        },
        ...environment.transcribers.map((t) => ({
          label: t.name,
          value: t.available ? 'Ready' : 'Not installed',
          ok: t.available,
        })),
        ...environment.separators.map((s) => ({
          label: s.name,
          value: s.available ? 'Ready' : 'Not installed',
          ok: s.available,
        })),
        {
          label: 'Cache',
          value: formatBytes(environment.cacheBytes),
          ok: true,
        },
      ]
    : [];

  const copyDebug = async () => {
    try {
      const diagnostics = await engine.diagnostics();
      await system.copy(JSON.stringify(diagnostics, null, 2));
      toast('success', 'Debug information copied. Paths are redacted; no file contents included.');
    } catch (err) {
      toast('error', (err as ShawzifyError).message);
    }
  };

  return (
    <Panel title="Audio Engine">
      <div className="space-y-1.5">
        {rows.map((row) => (
          <div key={row.label} className="flex items-center gap-3 text-sm">
            <span
              className={`w-1.5 h-1.5 rounded-full shrink-0 ${
                row.ok ? 'bg-amber' : 'bg-paper-faint'
              }`}
            />
            <span className="flex-1 text-paper-dim truncate">{row.label}</span>
            <span className="text-paper text-xs truncate max-w-[14rem] text-right">
              {row.value}
            </span>
          </div>
        ))}
      </div>
      <div className="mt-4 flex flex-wrap gap-2">
        <button type="button" className="btn-ghost" onClick={() => void copyDebug()}>
          Copy Debug Info
        </button>
        <button
          type="button"
          className="btn-ghost"
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            try {
              const result = await engine.clearCache();
              toast('success', `Cache cleared (${formatBytes(result.cacheBytes)} remaining).`);
            } catch (err) {
              toast('error', (err as ShawzifyError).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          Clear Cache
        </button>
        <button
          type="button"
          className="btn-ghost"
          onClick={async () => {
            try {
              const d = (await engine.diagnostics()) as { logDir?: string };
              if (d.logDir) await system.reveal(d.logDir);
            } catch (err) {
              toast('error', (err as ShawzifyError).message);
            }
          }}
        >
          Open Logs
        </button>
      </div>
    </Panel>
  );
}

function SourcesPanel() {
  const { providers, spotify, saveSpotify, loadProviders } = useStore();
  const [clientId, setClientId] = useState('');
  const [clientSecret, setClientSecret] = useState('');
  const [editing, setEditing] = useState(false);

  useEffect(() => {
    void loadProviders();
  }, [loadProviders]);

  useEffect(() => {
    if (spotify) setClientId(spotify.clientId);
  }, [spotify]);

  return (
    <Panel title="Input Sources">
      <div className="space-y-1.5">
        {providers.map((p) => (
          <div key={p.id} className="flex items-start gap-3 text-sm">
            <span
              className={`mt-1.5 w-1.5 h-1.5 rounded-full shrink-0 ${
                p.available ? 'bg-amber' : 'bg-paper-faint'
              }`}
            />
            <div className="min-w-0 flex-1">
              <div className="text-paper-dim">{p.name}</div>
              {!p.available && (
                <div className="text-2xs text-paper-faint leading-relaxed mt-0.5">{p.detail}</div>
              )}
            </div>
          </div>
        ))}
      </div>

      <div className="mt-4 pt-3 border-t divider">
        <div className="flex items-center justify-between">
          <span className="label">Spotify</span>
          <button
            type="button"
            className="text-2xs text-paper-faint hover:text-paper"
            onClick={() => setEditing(!editing)}
          >
            {editing ? 'Cancel' : spotify?.configured ? 'Change' : 'Connect'}
          </button>
        </div>
        <p className="mt-2 text-2xs text-paper-faint leading-relaxed">
          Spotify does not let applications download audio, and since November 2024 it no
          longer exposes tempo or key analysis to new apps either. SHAWZIFY uses it only to
          identify a track precisely, then finds the recording elsewhere and does its own
          analysis.
        </p>
        {editing && (
          <div className="mt-3 space-y-2">
            <p className="text-2xs text-paper-faint">
              Create an app at developer.spotify.com/dashboard and paste its credentials.
              They are stored on this machine only.
            </p>
            <input
              className="field w-full"
              placeholder="Client ID"
              value={clientId}
              spellCheck={false}
              onChange={(e) => setClientId(e.target.value)}
              aria-label="Spotify client ID"
            />
            <input
              className="field w-full"
              type="password"
              placeholder={spotify?.hasSecret ? '(unchanged)' : 'Client secret'}
              value={clientSecret}
              spellCheck={false}
              onChange={(e) => setClientSecret(e.target.value)}
              aria-label="Spotify client secret"
            />
            <button
              type="button"
              className="btn-primary"
              disabled={!clientId.trim() || (!clientSecret.trim() && !spotify?.hasSecret)}
              onClick={() => {
                void saveSpotify(clientId.trim(), clientSecret.trim());
                setEditing(false);
                setClientSecret('');
              }}
            >
              Save Credentials
            </button>
          </div>
        )}
      </div>
    </Panel>
  );
}


export function Settings() {
  const { keymap, environment, saveKeymap, useStems, setUseStems, setView } = useStore();

  return (
    <div className="h-full flex flex-col min-h-0">
      <header className="shrink-0 px-6 py-3.5 border-b divider flex items-center gap-4">
        <button
          type="button"
          onClick={() => setView('home')}
          className="text-paper-faint hover:text-paper transition-colors"
          aria-label="Back"
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
        <h1 className="text-base font-medium">Settings</h1>
      </header>

      <div className="flex-1 min-h-0 scroll-y p-4">
        <div className="max-w-3xl mx-auto grid grid-cols-2 gap-4 items-start">
          <EnvironmentPanel environment={environment} />

          <SourcesPanel />

          <Panel title="Processing">
            <div className="space-y-3">
              <Toggle
                label="Stem separation"
                hint="Isolates the vocal or melody before transcribing. Slower, usually better."
                checked={useStems}
                onChange={setUseStems}
              />
            </div>
            <p className="mt-4 text-2xs text-paper-faint leading-relaxed">
              SHAWZIFY processes everything on this machine. No audio is uploaded anywhere,
              and there is no telemetry.
            </p>
          </Panel>

          {keymap && <Bindings keymap={keymap} onSave={(k) => void saveKeymap(k)} />}
          {keymap && <Timing keymap={keymap} onSave={(k) => void saveKeymap(k)} />}

          <Panel title="About" className="col-span-2">
            <p className="text-xs text-paper-dim leading-relaxed">
              SHAWZIFY is an independent fan-made tool and is not affiliated with or endorsed by
              Digital Extremes. Warframe and Shawzin are trademarks of Digital Extremes.
            </p>
            <p className="text-xs text-paper-faint leading-relaxed mt-2">
              Live playback uses ordinary Windows keyboard input, exactly like an external MIDI
              controller. It does not read or modify the game in any way.
            </p>
          </Panel>
        </div>
      </div>
    </div>
  );
}
