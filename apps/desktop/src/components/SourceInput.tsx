/**
 * Paste a link, or pick a file.
 *
 * A Spotify link identifies the track exactly but cannot supply audio, so the
 * panel says so up front and then resolves the recording elsewhere. Whatever
 * route was used, the match confidence is shown -- SHAWZIFY never quietly
 * arranges a different song than the one that was asked for.
 */

import { useEffect, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import type { ProviderInfo, ResolvedSourceDto } from '@shawzify/shared-types';

import { ShawzifyError, engine } from '@/lib/ipc';
import { useStore } from '@/state/store';
import { formatTime } from './primitives';

const PROVIDER_LABEL: Record<string, string> = {
  local: 'Local file',
  youtube: 'YouTube',
  spotify: 'Spotify',
};

function looksLikeLink(text: string): boolean {
  return /^(https?:\/\/|spotify:)/i.test(text.trim());
}

export function SourceInput({ compact = false }: { compact?: boolean }) {
  const { openLink, providers, loadProviders, analyzing } = useStore();
  const [value, setValue] = useState('');
  const [preview, setPreview] = useState<ResolvedSourceDto | null>(null);
  const [checking, setChecking] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    void loadProviders();
  }, [loadProviders]);

  // Identify while the user pauses, so pasting a link shows what it is before
  // committing to a download.
  useEffect(() => {
    const text = value.trim();
    setPreview(null);
    setProblem(null);
    if (!looksLikeLink(text)) return;
    let cancelled = false;
    const timer = setTimeout(async () => {
      setChecking(true);
      try {
        const identified = await engine.identify(text);
        if (!cancelled) setPreview(identified);
      } catch (err) {
        if (!cancelled) setProblem((err as ShawzifyError).message);
      } finally {
        if (!cancelled) setChecking(false);
      }
    }, 650);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [value]);

  const submit = () => {
    const text = value.trim();
    if (!text) return;
    void openLink(text);
  };

  const unavailable = providers.filter((p: ProviderInfo) => p.online && !p.available);

  return (
    <div className={compact ? '' : 'w-full max-w-xl'}>
      <div className="flex gap-2">
        <input
          className="field flex-1 h-10"
          placeholder="Paste a YouTube or Spotify link"
          value={value}
          spellCheck={false}
          disabled={analyzing}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') submit();
          }}
          aria-label="Song link"
        />
        <button
          type="button"
          className="btn-primary h-10 px-5"
          disabled={!value.trim() || analyzing}
          onClick={submit}
        >
          {checking ? 'Checking…' : 'Convert'}
        </button>
      </div>

      <AnimatePresence>
        {preview && (
          <motion.div
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            className="surface mt-2 p-3 flex items-center gap-3 text-left"
          >
            {preview.reference.artworkUrl && (
              <img
                src={preview.reference.artworkUrl}
                alt=""
                className="w-11 h-11 rounded object-cover shrink-0"
              />
            )}
            <div className="min-w-0 flex-1">
              <div className="text-sm text-paper truncate">{preview.reference.title}</div>
              <div className="text-2xs text-paper-faint truncate">
                {[
                  preview.reference.artist,
                  PROVIDER_LABEL[preview.kind] ?? preview.kind,
                  preview.reference.durationSeconds
                    ? formatTime(preview.reference.durationSeconds)
                    : null,
                ]
                  .filter(Boolean)
                  .join(' · ')}
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {preview?.warnings.map((w) => (
        <p key={w} className="mt-2 text-2xs text-cyan leading-relaxed">
          {w}
        </p>
      ))}
      {problem && <p className="mt-2 text-2xs text-red-300">{problem}</p>}

      {unavailable.length > 0 && !compact && (
        <div className="mt-3 space-y-1">
          {unavailable.map((p) => (
            <p key={p.id} className="text-2xs text-paper-faint leading-relaxed">
              <span className="text-paper-dim">{p.name} unavailable.</span> {p.detail}
            </p>
          ))}
        </div>
      )}
    </div>
  );
}

/** Shown after a fetch, when the match is anything less than certain. */
export function MatchNotice({
  confidence,
  reason,
  title,
}: {
  confidence: number;
  reason: string;
  title: string;
}) {
  if (confidence >= 0.999) return null;
  const uncertain = confidence < 0.6;
  return (
    <div
      className={`surface p-3 ${uncertain ? 'border-amber/40 bg-amber-glow' : ''}`}
    >
      <div className="flex items-baseline gap-2">
        <span className="label">Matched</span>
        <span className={`text-xs tabular-nums ${uncertain ? 'text-amber' : 'text-paper-dim'}`}>
          {Math.round(confidence * 100)}%
        </span>
      </div>
      <div className="text-sm text-paper mt-1 truncate">{title}</div>
      {reason && <p className="text-2xs text-paper-faint mt-1 leading-relaxed">{reason}</p>}
    </div>
  );
}
