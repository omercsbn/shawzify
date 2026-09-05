/**
 * What to show when the app starts and its engine is not there.
 *
 * The installer ships the interface. The engine is a Python package, so a
 * freshly downloaded copy has nothing to talk to, and the first thing that
 * happened used to be a grey line at the bottom of the window reading
 * "the directory name is invalid (os error 267)". That is a dead end wearing
 * the clothes of a bug report. This is the same situation with a way out of it.
 */
import { useEffect, useState } from 'react';
import { motion } from 'framer-motion';

import { ShawzifyError, engine, system } from '@/lib/ipc';
import { useStore } from '@/state/store';

const REPO = 'https://github.com/omercsbn/shawzify';

export function EngineSetup() {
  const { engineMessage, bootstrap, toast } = useStore();
  const [candidates, setCandidates] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void engine
      .pythonCandidates()
      .then(setCandidates)
      .catch(() => setCandidates([]));
  }, []);

  const adopt = async (path: string) => {
    setBusy(true);
    try {
      await engine.setPython(path);
      toast('success', 'Engine connected');
      await bootstrap();
    } catch (err) {
      const e = err as ShawzifyError;
      toast('error', e.message, e.technical);
    } finally {
      setBusy(false);
    }
  };

  const browse = async () => {
    const path = await system.pickPython();
    if (path) await adopt(path);
  };

  const retry = async () => {
    setBusy(true);
    try {
      await engine.start();
      await bootstrap();
    } catch (err) {
      toast('error', (err as ShawzifyError).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <motion.div
      className="w-full max-w-xl surface-raised p-6"
      initial={{ y: 8 }}
      animate={{ y: 0 }}
      transition={{ duration: 0.3, ease: [0.22, 1, 0.36, 1] }}
    >
      <h2 className="text-base font-semibold text-paper">
        The audio engine is not installed yet
      </h2>

      <p className="mt-2 text-sm text-paper-dim leading-relaxed">
        This window is the interface. The part that listens to music and works out
        the arrangement is a Python package, and it is not in the installer: with
        the machine-learning models it would be several gigabytes, and most of
        that is downloaded on demand anyway.
      </p>

      <p className="mt-3 text-sm text-paper-dim leading-relaxed">
        Installing it is one command, once:
      </p>

      <pre className="mt-2 p-3 rounded-lg bg-ink-900 border divider text-2xs text-paper-dim overflow-x-auto select-text">
        git clone {REPO}
        {'\n'}cd shawzify
        {'\n'}scripts\setup.ps1
      </pre>

      {candidates.length > 0 && (
        <div className="mt-4">
          <div className="label mb-1.5">Interpreters found on this machine</div>
          <div className="space-y-1.5">
            {candidates.slice(0, 4).map((path) => (
              <button
                key={path}
                type="button"
                disabled={busy}
                className="btn-ghost w-full text-left truncate text-2xs"
                onClick={() => void adopt(path)}
                title={path}
              >
                {path}
              </button>
            ))}
          </div>
          <p className="mt-1.5 text-2xs text-paper-faint">
            Pick the one with the engine installed. SHAWZIFY checks before using it.
          </p>
        </div>
      )}

      <div className="mt-5 flex flex-wrap gap-2">
        <button type="button" className="btn-primary" disabled={busy} onClick={() => void retry()}>
          {busy ? 'Checking…' : 'Retry'}
        </button>
        <button type="button" className="btn-ghost" disabled={busy} onClick={() => void browse()}>
          Locate Python…
        </button>
        <button
          type="button"
          className="btn-ghost"
          onClick={() => void system.openUrl(`${REPO}#quick-start`)}
        >
          Setup guide
        </button>
      </div>

      {engineMessage && (
        <details className="mt-4">
          <summary className="text-2xs text-paper-faint cursor-pointer hover:text-paper-dim">
            What the engine reported
          </summary>
          <pre className="mt-1.5 text-[10px] leading-tight text-paper-faint whitespace-pre-wrap select-text">
            {engineMessage}
          </pre>
        </details>
      )}
    </motion.div>
  );
}
