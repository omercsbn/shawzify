/** The empty state: drop a song, or reopen a recent one. */

import { AnimatePresence, motion } from 'framer-motion';
import { useStore } from '@/state/store';
import { system } from '@/lib/ipc';
import { SourceInput } from './SourceInput';

function Logo({ size = 40 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 48 48" aria-hidden="true">
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
  );
}

export function Home() {
  const { recents, openFile, openProject, dropHover, environment, engineReady, engineMessage } =
    useStore();

  const pick = async () => {
    const path = await system.pickFile('media');
    if (path) void openFile(path);
  };

  const pickProject = async () => {
    const path = await system.pickFile('project');
    if (path) void openProject(path);
  };

  return (
    <div className="h-full flex flex-col items-center justify-center px-8 relative">
      <AnimatePresence>
        {dropHover && (
          <motion.div
            className="absolute inset-4 rounded-2xl border-2 border-dashed border-amber/60 bg-amber-glow pointer-events-none z-10"
            initial={{ opacity: 0, scale: 0.99 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.99 }}
            transition={{ duration: 0.14 }}
          />
        )}
      </AnimatePresence>

      <motion.div
        className="flex flex-col items-center text-center max-w-lg"
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4, ease: [0.22, 1, 0.36, 1] }}
      >
        <motion.div
          animate={dropHover ? { scale: 1.08, rotate: -3 } : { scale: 1, rotate: 0 }}
          transition={{ type: 'spring', stiffness: 320, damping: 22 }}
        >
          <Logo size={56} />
        </motion.div>

        <h1 className="mt-6 text-[2.6rem] leading-none font-semibold tracking-[-0.02em]">
          {dropHover ? 'Drop it' : 'Drop a song'}
        </h1>
        <p className="mt-3 text-sm text-paper-dim text-balance">
          SHAWZIFY turns audio or MIDI into a Warframe Shawzin performance, entirely on
          your machine.
        </p>

        <div className="mt-8 w-full">
          <SourceInput />
        </div>

        <div className="mt-4 flex items-center gap-3 w-full">
          <span className="flex-1 h-px bg-white/[0.07]" />
          <span className="text-2xs text-paper-faint">or</span>
          <span className="flex-1 h-px bg-white/[0.07]" />
        </div>

        <div className="mt-4 flex items-center gap-2">
          <button type="button" className="btn-ghost" onClick={pick}>
            Choose Audio or MIDI
          </button>
          <button type="button" className="btn-ghost" onClick={pickProject}>
            Open Project
          </button>
        </div>

        <div className="mt-4 flex items-center gap-4 text-2xs text-paper-faint">
          <span>WAV</span>
          <span>MP3</span>
          <span>FLAC</span>
          <span>M4A</span>
          <span>OGG</span>
          <span>MIDI</span>
          <span>YouTube</span>
          <span>Spotify</span>
        </div>
      </motion.div>

      {recents.length > 0 && (
        <motion.div
          className="mt-12 w-full max-w-2xl"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.15 }}
        >
          <div className="label mb-2.5">Recent</div>
          <div className="grid gap-1.5">
            {recents.slice(0, 5).map((item) => (
              <button
                key={item.path}
                type="button"
                onClick={() => void openProject(item.path)}
                className="surface flex items-center gap-4 px-3.5 h-11 text-left
                           hover:border-white/[0.14] hover:bg-ink-800 transition-colors group"
              >
                <span className="flex-1 min-w-0 truncate text-sm text-paper group-hover:text-amber-bright transition-colors">
                  {item.title}
                </span>
                <span className="chip">{item.kind}</span>
                <span className="text-sm tabular-nums text-amber w-14 text-right">
                  {item.compatibility.toFixed(0)}%
                </span>
              </button>
            ))}
          </div>
        </motion.div>
      )}

      <div className="absolute bottom-5 left-0 right-0 flex items-center justify-center gap-5 text-2xs text-paper-faint">
        <span className="inline-flex items-center gap-1.5">
          <span
            className={`w-1.5 h-1.5 rounded-full ${
              engineReady ? 'bg-amber' : 'bg-red-400'
            }`}
          />
          {engineReady ? 'Engine ready' : (engineMessage ?? 'Engine starting…')}
        </span>
        {environment?.gpu.cuda && <span>GPU: {environment.gpu.device}</span>}
        <span>Processed locally on your machine.</span>
      </div>
    </div>
  );
}
