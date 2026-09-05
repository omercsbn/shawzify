/** Export, copy, and PLAY IN WARFRAME. */

import { useEffect, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import type { ArrangementDto, SourceDto } from '@shawzify/shared-types';

import { ShawzifyError, engine, live, system } from '@/lib/ipc';
import { useStore } from '@/state/store';
import { Panel } from './primitives';
import { ShawzinDiagram } from './ShawzinDiagram';

function CodeBlock({ code, noteCount, limit }: { code: string; noteCount: number; limit: number }) {
  const overChatLimit = noteCount > limit;
  return (
    <div>
      <div
        className="font-mono text-[10.5px] leading-[1.5] text-paper-dim bg-ink-900 rounded-lg
                   border divider p-2.5 max-h-24 overflow-y-auto break-all select-text"
      >
        {code || '—'}
      </div>
      <div className="mt-1.5 flex items-center justify-between text-2xs text-paper-faint">
        <span>{code.length} characters</span>
        <span className={overChatLimit ? 'text-amber' : undefined}>
          {noteCount} notes{overChatLimit ? ` · over the ${limit}-note chat link limit` : ''}
        </span>
      </div>
    </div>
  );
}

export function Export({
  arrangement,
  source,
}: {
  arrangement: ArrangementDto;
  source: SourceDto;
}) {
  const {
    toast,
    warframe,
    keymap,
    liveActive,
    setLiveActive,
    liveCountdown,
    setLiveCountdown,
    transport,
  } = useStore();
  const [copied, setCopied] = useState(false);
  const [tick, setTick] = useState<{ fret: string; string: string; index: number } | null>(null);
  const [selectedPart, setSelectedPart] = useState(0);

  const parts = arrangement.parts;
  const code = parts.length > 0 ? (parts[selectedPart]?.code ?? '') : arrangement.code;
  const noteCount =
    parts.length > 0 ? (parts[selectedPart]?.noteCount ?? 0) : arrangement.song.noteCount;

  useEffect(() => {
    let unlistenTick: (() => void) | undefined;
    let unlistenDone: (() => void) | undefined;
    void live.onTick((t) => setTick({ fret: t.fret, string: t.string, index: t.index })).then(
      (fn) => {
        unlistenTick = fn;
      },
    );
    void live
      .onFinished((stats) => {
        setLiveActive(false);
        setTick(null);
        if (stats.stopped_early && stats.stop_reason) {
          toast('info', stats.stop_reason);
        } else {
          toast(
            'success',
            `Performance finished — ${stats.fired} events, ${stats.mean_error_ms.toFixed(1)} ms average timing error.`,
          );
        }
      })
      .then((fn) => {
        unlistenDone = fn;
      });
    return () => {
      unlistenTick?.();
      unlistenDone?.();
    };
  }, [setLiveActive, toast]);

  // Esc always stops live playback, whatever has focus.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && liveActive) {
        void live.stop();
        setLiveActive(false);
        setLiveCountdown(null);
        toast('info', 'Playback stopped.');
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [liveActive, setLiveActive, setLiveCountdown, toast]);

  const copy = async () => {
    try {
      await system.copy(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch (err) {
      toast('error', (err as ShawzifyError).message);
    }
  };

  const exportAs = async (kind: string, name: string, extensions: string[]) => {
    try {
      if (transport === 'web') {
        // A browser cannot name a path, so the engine writes into its own
        // cache and the page downloads it. Without this every export button
        // did nothing at all here, silently.
        const written = await engine.export(arrangement.sourceId, kind);
        await system.downloadFromCache(written.path, name);
        toast('success', `Downloaded ${name}`);
        return;
      }
      const path = await system.pickSavePath(name, extensions);
      if (!path) return;
      const written = await engine.export(arrangement.sourceId, kind, path);
      toast('success', `Saved ${written.path}`);
    } catch (err) {
      const e = err as ShawzifyError;
      toast('error', e.message, e.technical);
    }
  };

  const playLive = async () => {
    if (!keymap) return;
    try {
      const status = await live.status();
      if (!status.supported) {
        toast('error', 'Live playback is only available on Windows.');
        return;
      }
      if (!status.found) {
        toast('error', 'Warframe is not running.', 'Start Warframe and equip the Shawzin emote.');
        return;
      }
      // Give the player time to alt-tab, then start.
      setLiveCountdown(3);
      for (let i = 3; i > 0; i -= 1) {
        setLiveCountdown(i);
        await new Promise((r) => setTimeout(r, 1000));
      }
      setLiveCountdown(0);
      await new Promise((r) => setTimeout(r, 350));
      setLiveCountdown(null);

      const events =
        parts.length > 0
          ? arrangement.liveEvents.filter((e) => {
              const part = parts[selectedPart];
              return part ? e.at >= part.startSeconds && e.at <= part.endSeconds : true;
            })
          : arrangement.liveEvents;

      await live.play(events, keymap.keymap.bindings, keymap.keymap.timing, true);
      setLiveActive(true);
    } catch (err) {
      setLiveCountdown(null);
      const e = err as ShawzifyError;
      toast('error', e.message, e.technical);
    }
  };

  const stopLive = async () => {
    await live.stop();
    setLiveActive(false);
    setLiveCountdown(null);
  };

  const canLive = Boolean(warframe?.supported) && (keymap?.problems.length ?? 0) === 0;
  const stem = source.title.replace(/[^\w.-]+/g, '_') || 'shawzify';

  return (
    <Panel title="Export">
      {parts.length > 0 && (
        <div className="mb-3">
          <div className="text-2xs text-amber mb-2">
            This arrangement exceeds the Shawzin song limit and was split into {parts.length} parts.
          </div>
          <div className="segmented">
            {parts.map((part, i) => (
              <button
                key={part.index}
                type="button"
                data-active={i === selectedPart}
                onClick={() => setSelectedPart(i)}
              >
                Part {i + 1}
              </button>
            ))}
          </div>
        </div>
      )}

      <CodeBlock code={code} noteCount={noteCount} limit={100} />

      <div className="mt-3 grid grid-cols-2 gap-2">
        <button type="button" className="btn-primary" onClick={copy}>
          {copied ? 'Copied' : 'Copy Shawzin Code'}
        </button>
        <button
          type="button"
          className="btn-ghost"
          onClick={() => void exportAs('code', `${stem}.shawzin.txt`, ['txt'])}
        >
          Save Code
        </button>
        <button
          type="button"
          className="btn-ghost"
          onClick={() => void exportAs('midi', `${stem}.arranged.mid`, ['mid'])}
        >
          Export Arranged MIDI
        </button>
        <button
          type="button"
          className="btn-ghost"
          onClick={() => void exportAs('sourceMidi', `${stem}.source.mid`, ['mid'])}
        >
          Export Source MIDI
        </button>
        <button
          type="button"
          className="btn-ghost"
          onClick={() => void exportAs('project', `${stem}.shawzify`, ['shawzify'])}
        >
          Save Project
        </button>
        <button
          type="button"
          className="btn-ghost"
          onClick={() => void exportAs('analysis', `${stem}.analysis.json`, ['json'])}
        >
          Export Analysis JSON
        </button>
      </div>

      <div className="mt-4 pt-4 border-t divider">
        {liveActive ? (
          <button type="button" className="btn-danger w-full" onClick={() => void stopLive()}>
            Stop (Esc)
          </button>
        ) : (
          <button
            type="button"
            className="btn-primary w-full"
            disabled={!canLive || liveCountdown !== null}
            onClick={() => void playLive()}
            title={
              !warframe?.supported
                ? 'Live playback is only available on Windows.'
                : !warframe?.found
                  ? 'Warframe is not running.'
                  : undefined
            }
          >
            Play in Warframe
          </button>
        )}
        <p className="mt-2 text-2xs text-paper-faint leading-relaxed">
          {!warframe?.supported
            ? 'Live playback needs Windows.'
            : !warframe?.found
              ? 'Start Warframe and equip the Shawzin emote to enable live playback.'
              : 'SHAWZIFY types the notes for you. Warframe must stay the active window; playback stops the moment it is not.'}
        </p>
      </div>

      <AnimatePresence>
        {liveCountdown !== null && (
          <motion.div
            className="fixed inset-0 z-50 flex items-center justify-center bg-ink-900/85 backdrop-blur-sm"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
          >
            <motion.div
              key={liveCountdown}
              initial={{ scale: 0.7, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 1.3, opacity: 0 }}
              className="text-[7rem] leading-none font-semibold text-amber tabular-nums"
            >
              {liveCountdown === 0 ? 'PLAY' : liveCountdown}
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {liveActive && (
        <div className="mt-4 pt-4 border-t divider">
          <div className="label mb-2">Now playing</div>
          <ShawzinDiagram
            fret={tick?.fret ?? '0'}
            strings={tick?.string ?? ''}
            compact
          />
          <div className="mt-2 text-2xs text-paper-faint tabular-nums">
            Event {(tick?.index ?? 0) + 1} of {arrangement.liveEvents.length}
          </div>
        </div>
      )}
    </Panel>
  );
}
