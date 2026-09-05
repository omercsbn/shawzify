import { useEffect } from 'react';
import { AnimatePresence, motion } from 'framer-motion';

import { onFileDrop, reconnect } from '@/lib/ipc';
import { useStore } from '@/state/store';
import { Home } from '@/components/Home';
import { Onboarding } from '@/components/Onboarding';
import { Settings } from '@/components/Settings';
import { Workspace } from '@/components/Workspace';

function TopBar() {
  const { view, setView, source, warframe, engineReady } = useStore();
  return (
    <div
      className="h-11 shrink-0 flex items-center gap-4 px-4 border-b divider bg-ink-850/60"
      data-tauri-drag-region
    >
      <button
        type="button"
        className="flex items-center gap-2.5 group"
        onClick={() => setView(source ? 'workspace' : 'home')}
      >
        <svg width="17" height="17" viewBox="0 0 48 48" aria-hidden="true">
          <path
            d="M24 13c5 0 9 3.2 9 7.4 0 5.4-5.2 11.6-9 14.6-3.8-3-9-9.2-9-14.6C15 16.2 19 13 24 13z"
            fill="#E8A84C"
          />
        </svg>
        <span className="text-[13px] font-semibold tracking-[0.16em] text-paper group-hover:text-amber-bright transition-colors">
          SHAWZIFY
        </span>
      </button>

      <div className="flex-1" />

      {warframe?.found && (
        <span className="chip">
          <span className="w-1.5 h-1.5 rounded-full bg-amber" />
          Warframe {warframe.focused ? 'focused' : 'running'}
        </span>
      )}
      {!engineReady && <span className="chip text-red-300">Engine offline</span>}

      <button
        type="button"
        className={`btn-quiet h-7 px-2.5 ${view === 'settings' ? 'text-amber' : ''}`}
        onClick={() => setView(view === 'settings' ? (source ? 'workspace' : 'home') : 'settings')}
      >
        Settings
      </button>
    </div>
  );
}

/**
 * The browser transport's server is a separate process the user started, so it
 * can disappear without the page knowing. Say so, rather than letting every
 * action fail with a network error.
 */
function ConnectionBanner() {
  const { transport, connection } = useStore();
  if (transport !== 'web' || connection === 'connected') return null;

  const stale = connection === 'stale';
  const message = stale
    ? 'This page is from an earlier run of the server. Open the link the current one printed.'
    : connection === 'reconnecting'
      ? 'Lost the connection to the SHAWZIFY server. Reconnecting...'
      : 'The SHAWZIFY server is not running. Start it again with: scripts\\dev.ps1 -Cli web';

  return (
    <div className="shrink-0 flex items-center gap-3 px-4 py-2 border-b border-red-500/25 bg-red-500/10">
      <span
        className={`w-1.5 h-1.5 rounded-full shrink-0 ${
          connection === 'reconnecting' ? 'bg-amber animate-pulse' : 'bg-red-400'
        }`}
      />
      <p className="flex-1 text-xs text-red-100">{message}</p>
      {!stale && (
        <button type="button" className="btn-quiet h-6 px-2 text-2xs" onClick={() => reconnect()}>
          Retry now
        </button>
      )}
    </div>
  );
}

function Toasts() {
  const { toasts, dismissToast } = useStore();
  return (
    <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2 w-[26rem] pointer-events-none">
      <AnimatePresence>
        {toasts.map((toast) => (
          <motion.div
            key={toast.id}
            layout
            initial={{ opacity: 0, y: 12, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 8, scale: 0.98 }}
            transition={{ duration: 0.2, ease: [0.22, 1, 0.36, 1] }}
            className={`pointer-events-auto surface-raised px-3.5 py-2.5 shadow-xl ${
              toast.kind === 'error' ? 'border-red-500/30' : ''
            }`}
          >
            <div className="flex items-start gap-2.5">
              <span
                className={`mt-1.5 w-1.5 h-1.5 rounded-full shrink-0 ${
                  toast.kind === 'error'
                    ? 'bg-red-400'
                    : toast.kind === 'success'
                      ? 'bg-amber'
                      : 'bg-cyan'
                }`}
              />
              <div className="min-w-0 flex-1">
                <p className="text-xs text-paper leading-relaxed">{toast.message}</p>
                {toast.detail && (
                  <details className="mt-1.5">
                    <summary className="text-2xs text-paper-faint cursor-pointer hover:text-paper-dim">
                      Technical details
                    </summary>
                    <pre className="mt-1 text-[10px] leading-tight text-paper-faint whitespace-pre-wrap max-h-40 overflow-y-auto select-text">
                      {toast.detail}
                    </pre>
                  </details>
                )}
              </div>
              <button
                type="button"
                className="text-paper-faint hover:text-paper text-xs shrink-0"
                onClick={() => dismissToast(toast.id)}
                aria-label="Dismiss"
              >
                ×
              </button>
            </div>
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  );
}

export default function App() {
  const { view, bootstrap, openFile, openProject, setDropHover, refreshWarframe, onboarded } =
    useStore();

  useEffect(() => {
    void bootstrap();
  }, [bootstrap]);

  // Files dropped on the window arrive through Tauri, not the DOM.
  useEffect(() => {
    let unlisten: (() => void) | undefined;
    void onFileDrop(
      (paths) => {
        const path = paths[0];
        if (!path) return;
        if (path.toLowerCase().endsWith('.shawzify')) void openProject(path);
        else void openFile(path);
      },
      setDropHover,
    ).then((fn) => {
      unlisten = fn;
    });
    return () => unlisten?.();
  }, [openFile, openProject, setDropHover]);

  // Warframe can start or stop at any time; poll gently so the button state is honest.
  useEffect(() => {
    const id = setInterval(() => void refreshWarframe(), 4000);
    return () => clearInterval(id);
  }, [refreshWarframe]);

  if (!onboarded) return <Onboarding />;

  return (
    <div className="h-full flex flex-col bg-ink-900">
      <TopBar />
      <ConnectionBanner />
      <main className="flex-1 min-h-0 relative">
        {view === 'settings' ? (
          <Settings />
        ) : view === 'workspace' ? (
          <Workspace />
        ) : (
          <Home />
        )}
      </main>
      <Toasts />
    </div>
  );
}
