/**
 * Application state.
 *
 * One store, split by concern. The important rule encoded here: analysis and
 * arrangement are separate actions with separate loading flags, because
 * changing an arrangement control must never re-run transcription.
 */

import { create } from 'zustand';
import type {
  ArrangementDto,
  ArrangementOptionsDto,
  EnvironmentDto,
  InstrumentDto,
  KeymapDto,
  ProgressPayload,
  ProviderInfo,
  RecentProject,
  SourceDto,
  SpotifyCredentialsDto,
  WarframeStatus,
} from '@shawzify/shared-types';

import { ShawzifyError, engine, live, system, transport } from '@/lib/ipc';

export type View = 'home' | 'workspace' | 'settings' | 'diagnostics';
export type PreviewTarget = 'source' | 'arrangement';

export const DEFAULT_OPTIONS: ArrangementOptionsDto = {
  mode: 'balanced',
  scale: 'auto',
  transpose: 'auto',
  quantization: 'auto',
  quantizationStrength: 0.85,
  complexity: 0.55,
  preserveMelody: true,
  arpeggiateChords: 'auto',
  maxDensity: 'auto',
  shawzinVariant: 'dax',
  stemSource: 'auto',
  focus: 'auto',
  useStructure: true,
};

export interface Toast {
  id: number;
  kind: 'info' | 'success' | 'error';
  message: string;
  detail?: string | null;
}

interface AppStore {
  // -- environment
  view: View;
  environment: EnvironmentDto | null;
  instrument: InstrumentDto | null;
  keymap: KeymapDto | null;
  warframe: WarframeStatus | null;
  recents: RecentProject[];
  providers: ProviderInfo[];
  spotify: SpotifyCredentialsDto | null;
  transport: 'tauri' | 'web' | 'none';
  engineReady: boolean;
  engineMessage: string | null;
  onboarded: boolean;

  // -- current work
  source: SourceDto | null;
  arrangement: ArrangementDto | null;
  options: ArrangementOptionsDto;
  useStems: boolean;

  // -- transient
  analyzing: boolean;
  arranging: boolean;
  progress: ProgressPayload | null;
  error: ShawzifyError | null;
  toasts: Toast[];
  dropHover: boolean;
  selectedDecision: number | null;
  previewTarget: PreviewTarget;
  playhead: number;
  playing: boolean;
  liveActive: boolean;
  liveCountdown: number | null;
  liveIndex: number;
  advanced: boolean;
  expandedShawzin: string | null;

  // -- actions
  setView: (view: View) => void;
  setDropHover: (hovering: boolean) => void;
  setSelectedDecision: (index: number | null) => void;
  setPreviewTarget: (target: PreviewTarget) => void;
  setPlayhead: (seconds: number) => void;
  setPlaying: (playing: boolean) => void;
  setAdvanced: (advanced: boolean) => void;
  setOnboarded: (value: boolean) => void;
  toast: (kind: Toast['kind'], message: string, detail?: string | null) => void;
  dismissToast: (id: number) => void;
  clearError: () => void;

  bootstrap: () => Promise<void>;
  refreshWarframe: () => Promise<void>;
  loadProviders: () => Promise<void>;
  saveSpotify: (clientId: string, clientSecret: string) => Promise<void>;
  setExpandedShawzin: (id: string | null) => void;
  openLink: (target: string) => Promise<void>;
  openFile: (path: string) => Promise<void>;
  openProject: (path: string) => Promise<void>;
  reArrange: (patch: Partial<ArrangementOptionsDto>) => Promise<void>;
  setUseStems: (value: boolean) => void;
  reset: () => void;
  saveKeymap: (keymap: KeymapDto['keymap']) => Promise<void>;
  setLiveActive: (active: boolean) => void;
  setLiveCountdown: (value: number | null) => void;
  setLiveIndex: (index: number) => void;
}

let toastId = 0;
/** Guards against a slow analysis overwriting a newer one. */
let latestRun = 0;

export const useStore = create<AppStore>((set, get) => ({
  view: 'home',
  environment: null,
  instrument: null,
  keymap: null,
  warframe: null,
  recents: [],
  providers: [],
  spotify: null,
  transport: transport(),
  engineReady: false,
  engineMessage: null,
  onboarded: (() => {
    try {
      return localStorage.getItem('shawzify.onboarded') === '1';
    } catch {
      return false;
    }
  })(),

  source: null,
  arrangement: null,
  options: DEFAULT_OPTIONS,
  useStems: true,

  analyzing: false,
  arranging: false,
  progress: null,
  error: null,
  toasts: [],
  dropHover: false,
  selectedDecision: null,
  previewTarget: 'arrangement',
  playhead: 0,
  playing: false,
  liveActive: false,
  liveCountdown: null,
  liveIndex: 0,
  advanced: false,
  expandedShawzin: null,

  setExpandedShawzin: (expandedShawzin) => set({ expandedShawzin }),

  setView: (view) => set({ view }),
  setDropHover: (dropHover) => set({ dropHover }),
  setSelectedDecision: (selectedDecision) => set({ selectedDecision }),
  setPreviewTarget: (previewTarget) => set({ previewTarget }),
  setPlayhead: (playhead) => set({ playhead }),
  setPlaying: (playing) => set({ playing }),
  setAdvanced: (advanced) => set({ advanced }),
  setOnboarded: (value) => {
    try {
      localStorage.setItem('shawzify.onboarded', value ? '1' : '0');
    } catch {
      /* storage is a nicety, not a requirement */
    }
    set({ onboarded: value });
  },
  setLiveActive: (liveActive) => set({ liveActive }),
  setLiveCountdown: (liveCountdown) => set({ liveCountdown }),
  setLiveIndex: (liveIndex) => set({ liveIndex }),

  toast: (kind, message, detail = null) => {
    toastId += 1;
    const id = toastId;
    set((s) => ({ toasts: [...s.toasts, { id, kind, message, detail }] }));
    const ttl = kind === 'error' ? 9000 : 4000;
    setTimeout(() => get().dismissToast(id), ttl);
  },
  dismissToast: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
  clearError: () => set({ error: null }),

  setUseStems: (useStems) => set({ useStems }),

  async bootstrap() {
    try {
      const status = await engine.status();
      if (!status.running) await engine.start();
      const [environment, instrument, keymap, recents] = await Promise.all([
        engine.environment(),
        engine.instrument(get().options.shawzinVariant),
        engine.keymap(),
        engine.recents(),
      ]);
      set({
        environment,
        instrument,
        keymap,
        recents: recents.recents,
        engineReady: true,
        engineMessage: null,
      });
      void get().refreshWarframe();
      void get().loadProviders();
      // Honour a file passed on the command line once the engine is up.
      try {
        const startup = await engine.startupFile();
        if (startup) {
          if (startup.toLowerCase().endsWith('.shawzify')) void get().openProject(startup);
          else void get().openFile(startup);
        }
      } catch {
        /* no startup file is the normal case */
      }
    } catch (err) {
      const e = err as ShawzifyError;
      set({ engineReady: false, engineMessage: e.message, error: e });
    }
  },

  async loadProviders() {
    try {
      const [sources, spotify] = await Promise.all([
        engine.sources(),
        engine.spotifyCredentials().catch(() => null),
      ]);
      set({ providers: sources.providers, spotify });
    } catch {
      set({ providers: [] });
    }
  },

  async saveSpotify(clientId, clientSecret) {
    try {
      const saved = await engine.spotifyCredentials({ clientId, clientSecret });
      set({ spotify: saved });
      get().toast(
        saved.available ? 'success' : 'info',
        saved.available ? 'Spotify is connected.' : saved.detail,
      );
      void get().loadProviders();
    } catch (err) {
      const e = err as ShawzifyError;
      get().toast('error', e.message, e.technical);
    }
  },

  /** Fetch a YouTube or Spotify link, then run the normal pipeline on it. */
  async openLink(target) {
    const run = ++latestRun;
    set({
      analyzing: true,
      error: null,
      progress: null,
      source: null,
      arrangement: null,
      selectedDecision: null,
      playhead: 0,
      view: 'workspace',
    });
    try {
      const source = await engine.fetch(target, {
        useStems: get().useStems,
        onProgress: (progress) => {
          if (run === latestRun) set({ progress });
        },
      });
      if (run !== latestRun) return;
      set({ source, analyzing: false, arranging: true });
      const arrangement = await engine.arrange(source.sourceId, get().options, {
        onProgress: (progress) => {
          if (run === latestRun) set({ progress });
        },
      });
      if (run !== latestRun) return;
      set({ arrangement, arranging: false, progress: null });
      for (const warning of source.warnings ?? []) get().toast('info', warning);
      if (source.matchConfidence !== undefined && source.matchConfidence < 0.6) {
        get().toast(
          'info',
          'The best match for that link is uncertain. Check the result before playing it.',
          source.matchReason,
        );
      }
    } catch (err) {
      if (run !== latestRun) return;
      const e = err as ShawzifyError;
      set({ analyzing: false, arranging: false, progress: null, error: e });
      if (e.code === 'cancelled') return;
      get().toast('error', e.message, e.hint ?? e.technical);
    }
  },

  async refreshWarframe() {
    try {
      set({ warframe: await live.status() });
    } catch {
      set({ warframe: null });
    }
  },

  async openFile(path) {
    const run = ++latestRun;
    set({
      analyzing: true,
      error: null,
      progress: null,
      source: null,
      arrangement: null,
      selectedDecision: null,
      playhead: 0,
      view: 'workspace',
    });
    try {
      const source = await engine.analyze(path, get().options, {
        useStems: get().useStems,
        onProgress: (progress) => {
          if (run === latestRun) set({ progress });
        },
      });
      if (run !== latestRun) return;
      set({ source, analyzing: false, arranging: true });
      const arrangement = await engine.arrange(source.sourceId, get().options, {
        onProgress: (progress) => {
          if (run === latestRun) set({ progress });
        },
      });
      if (run !== latestRun) return;
      set({ arrangement, arranging: false, progress: null });
      for (const warning of source.warnings) get().toast('info', warning);
    } catch (err) {
      if (run !== latestRun) return;
      const e = err as ShawzifyError;
      set({ analyzing: false, arranging: false, progress: null, error: e });
      if (e.code === 'cancelled') return;
      get().toast('error', e.message, e.technical);
    }
  },

  async openProject(path) {
    set({ analyzing: true, error: null, view: 'workspace' });
    try {
      const opened = await engine.openProject(path);
      const arrangement = await engine.arrange(opened.sourceId, get().options);
      set({ source: opened.source, arrangement, analyzing: false });
      if (!opened.reproducible) {
        get().toast(
          'info',
          'This project was made with an earlier arrangement engine, so the result may differ slightly.',
        );
      }
    } catch (err) {
      const e = err as ShawzifyError;
      set({ analyzing: false, error: e });
      get().toast('error', e.message, e.technical);
    }
  },

  async reArrange(patch) {
    const options = { ...get().options, ...patch };
    set({ options });
    const source = get().source;
    if (!source) return;
    const run = ++latestRun;
    set({ arranging: true, error: null });
    try {
      const arrangement = await engine.arrange(source.sourceId, options, {
        onProgress: (progress) => {
          if (run === latestRun) set({ progress });
        },
      });
      if (run !== latestRun) return;
      set({ arrangement, arranging: false, progress: null, selectedDecision: null });
    } catch (err) {
      if (run !== latestRun) return;
      const e = err as ShawzifyError;
      set({ arranging: false, progress: null, error: e });
      get().toast('error', e.message, e.technical);
    }
  },

  async saveKeymap(keymap) {
    try {
      const saved = await engine.keymap(keymap);
      set({ keymap: saved });
      get().toast('success', 'Key bindings saved.');
    } catch (err) {
      const e = err as ShawzifyError;
      get().toast('error', e.message, e.technical);
    }
  },

  reset: () =>
    set({
      source: null,
      arrangement: null,
      progress: null,
      error: null,
      selectedDecision: null,
      playhead: 0,
      playing: false,
      view: 'home',
    }),
}));

// -- selectors -----------------------------------------------------------

export const selectCompatibility = (s: AppStore) => ({
  before: s.arrangement ? s.arrangement.report.compatibilityBefore.overall : null,
  after: s.arrangement ? s.arrangement.report.compatibilityAfter.overall : null,
});

export const selectBusy = (s: AppStore) => s.analyzing || s.arranging;

export const selectCanPlayLive = (s: AppStore) =>
  Boolean(s.arrangement) &&
  Boolean(s.warframe?.supported) &&
  Boolean(s.warframe?.found) &&
  (s.keymap?.problems.length ?? 0) === 0;

export { system };
