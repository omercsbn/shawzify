/**
 * The single door between the UI and everything native.
 *
 * Every engine call goes through here so that request ids, progress routing,
 * cancellation and error normalisation exist in exactly one place. Outside a
 * Tauri window (vitest, `vite preview`) the module falls back to a clearly
 * labelled unavailable state rather than throwing at import time.
 */

import type {
  ArrangementDto,
  ArrangementOptionsDto,
  EngineError,
  EnvironmentDto,
  InstrumentDto,
  KeymapDto,
  LiveEventDto,
  LiveStats,
  LiveTick,
  ProgressPayload,
  RecentProject,
  SourceDto,
  WarframeStatus,
} from '@shawzify/shared-types';

type Invoke = <T>(cmd: string, args?: Record<string, unknown>) => Promise<T>;
type Listen = <T>(event: string, handler: (e: { payload: T }) => void) => Promise<() => void>;

interface TauriBridge {
  invoke: Invoke;
  listen: Listen;
  available: boolean;
}

let bridge: TauriBridge | null = null;

export function isTauri(): boolean {
  return typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window;
}

async function getBridge(): Promise<TauriBridge> {
  if (bridge) return bridge;
  if (!isTauri()) {
    bridge = {
      available: false,
      invoke: async () => {
        throw normalizeError({
          code: 'not_desktop',
          message: 'This feature needs the SHAWZIFY desktop app.',
          hint: 'Run scripts/dev.ps1 to launch it.',
          technical: null,
        });
      },
      listen: async () => () => undefined,
    };
    return bridge;
  }
  const [core, event] = await Promise.all([
    import('@tauri-apps/api/core'),
    import('@tauri-apps/api/event'),
  ]);
  bridge = {
    available: true,
    invoke: core.invoke as Invoke,
    listen: event.listen as unknown as Listen,
  };
  return bridge;
}

export class ShawzifyError extends Error {
  code: string;
  hint: string | null;
  technical: string | null;

  constructor(payload: EngineError) {
    super(payload.message);
    this.name = 'ShawzifyError';
    this.code = payload.code;
    this.hint = payload.hint;
    this.technical = payload.technical;
  }
}

export function normalizeError(raw: unknown): ShawzifyError {
  if (raw instanceof ShawzifyError) return raw;
  if (raw && typeof raw === 'object' && 'message' in raw) {
    const r = raw as Record<string, unknown>;
    return new ShawzifyError({
      code: typeof r.code === 'string' ? r.code : 'unknown',
      message: typeof r.message === 'string' ? r.message : 'Something went wrong.',
      hint: typeof r.hint === 'string' ? r.hint : null,
      technical: typeof r.technical === 'string' ? r.technical : null,
    });
  }
  return new ShawzifyError({
    code: 'unknown',
    message: typeof raw === 'string' ? raw : 'Something went wrong.',
    hint: null,
    technical: null,
  });
}

async function invoke<T>(cmd: string, args?: Record<string, unknown>): Promise<T> {
  const b = await getBridge();
  try {
    return await b.invoke<T>(cmd, args);
  } catch (err) {
    throw normalizeError(err);
  }
}

// -- request ids and progress routing -----------------------------------

let nextRequestId = 1;
export function newRequestId(): number {
  nextRequestId += 1;
  return nextRequestId;
}

type ProgressHandler = (payload: ProgressPayload) => void;
const progressHandlers = new Map<number, ProgressHandler>();
let progressBound = false;

async function bindProgress(): Promise<void> {
  if (progressBound) return;
  progressBound = true;
  const b = await getBridge();
  if (!b.available) return;
  await b.listen<{ id: number; kind: string; payload: ProgressPayload }>(
    'engine://event',
    ({ payload }) => {
      const handler = progressHandlers.get(payload.id);
      if (handler && payload.kind === 'progress') handler(payload.payload);
    },
  );
}

/** Run an engine call, routing its progress events to `onProgress`. */
async function withProgress<T>(
  requestId: number,
  onProgress: ProgressHandler | undefined,
  run: () => Promise<T>,
): Promise<T> {
  if (onProgress) {
    await bindProgress();
    progressHandlers.set(requestId, onProgress);
  }
  try {
    return await run();
  } finally {
    progressHandlers.delete(requestId);
  }
}

// -- engine --------------------------------------------------------------

export interface EngineStatus {
  running: boolean;
  python: string | null;
  root: string;
  error: string | null;
}

export const engine = {
  /** A file passed on the command line, e.g. from Explorer's "Open with". */
  startupFile: () => invoke<string | null>('startup_file'),
  status: () => invoke<EngineStatus>('engine_status'),
  start: () => invoke<EngineStatus>('engine_start'),
  restart: () => invoke<EngineStatus>('engine_restart'),
  call: <T>(method: string, params: Record<string, unknown> = {}) =>
    invoke<T>('engine_call', { method, params }),

  environment: () => invoke<EnvironmentDto>('engine_call', { method: 'environment', params: {} }),
  instrument: (variant = 'dax') =>
    invoke<InstrumentDto>('engine_call', { method: 'instrument', params: { variant } }),
  recents: () =>
    invoke<{ recents: RecentProject[] }>('engine_call', { method: 'recents', params: {} }),
  diagnostics: () =>
    invoke<Record<string, unknown>>('engine_call', { method: 'diagnostics', params: {} }),
  keymap: (save?: KeymapDto['keymap']) =>
    invoke<KeymapDto>('engine_call', { method: 'keymap', params: save ? { save } : {} }),
  clearCache: (namespace?: string) =>
    invoke<{ cacheBytes: number }>('engine_call', {
      method: 'clearCache',
      params: namespace ? { namespace } : {},
    }),
  decode: (code: string, variant = 'dax') =>
    invoke<Record<string, unknown>>('engine_call', {
      method: 'decode',
      params: { code, variant },
    }),

  async analyze(
    path: string,
    options: Partial<ArrangementOptionsDto>,
    opts: { useStems?: boolean; transcriber?: string; device?: string; onProgress?: ProgressHandler } = {},
  ): Promise<SourceDto> {
    const requestId = newRequestId();
    return withProgress(requestId, opts.onProgress, () =>
      invoke<SourceDto>('engine_call', {
        method: 'analyze',
        params: {
          path,
          options,
          requestId,
          useStems: opts.useStems ?? true,
          transcriber: opts.transcriber ?? 'auto',
          device: opts.device ?? 'auto',
        },
      }),
    );
  },

  async arrange(
    sourceId: string,
    options: Partial<ArrangementOptionsDto>,
    opts: { onProgress?: ProgressHandler } = {},
  ): Promise<ArrangementDto> {
    const requestId = newRequestId();
    return withProgress(requestId, opts.onProgress, () =>
      invoke<ArrangementDto>('engine_call', {
        method: 'arrange',
        params: { sourceId, options, requestId },
      }),
    );
  },

  cancel: (requestId: number) =>
    invoke<{ cancelled: boolean }>('engine_call', {
      method: 'cancel',
      params: { requestId },
    }),

  preview: (sourceId: string) =>
    invoke<{ path: string; durationSeconds: number; sampleRate: number }>('engine_call', {
      method: 'preview',
      params: { sourceId },
    }),

  export: (sourceId: string, kind: string, path: string) =>
    invoke<{ path: string; kind: string }>('engine_call', {
      method: 'export',
      params: { sourceId, kind, path },
    }),

  openProject: (path: string) =>
    invoke<{ sourceId: string; source: SourceDto; code: string; reproducible: boolean }>(
      'engine_call',
      { method: 'openProject', params: { path } },
    ),
};

// -- system --------------------------------------------------------------

export const system = {
  copy: async (text: string): Promise<void> => {
    // Prefer the webview clipboard; fall back to the native path.
    try {
      if (navigator?.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
        return;
      }
    } catch {
      /* fall through to the native path */
    }
    await invoke<void>('copy_to_clipboard', { text });
  },
  writeTextFile: (path: string, contents: string) =>
    invoke<string>('write_text_file', { path, contents }),
  readTextFile: (path: string) => invoke<string>('read_text_file', { path }),
  reveal: (path: string) => invoke<void>('reveal_path', { path }),

  async pickFile(kind: 'media' | 'project'): Promise<string | null> {
    if (!isTauri()) return null;
    const { open } = await import('@tauri-apps/plugin-dialog');
    const filters =
      kind === 'project'
        ? [{ name: 'SHAWZIFY project', extensions: ['shawzify'] }]
        : [
            { name: 'Audio and MIDI', extensions: ['wav', 'mp3', 'flac', 'm4a', 'ogg', 'mid', 'midi'] },
            { name: 'Audio', extensions: ['wav', 'mp3', 'flac', 'm4a', 'ogg', 'opus', 'aac', 'aiff', 'wma'] },
            { name: 'MIDI', extensions: ['mid', 'midi'] },
          ];
    const picked = await open({ multiple: false, directory: false, filters });
    return typeof picked === 'string' ? picked : null;
  },

  async pickSavePath(defaultName: string, extensions: string[]): Promise<string | null> {
    if (!isTauri()) return null;
    const { save } = await import('@tauri-apps/plugin-dialog');
    const picked = await save({
      defaultPath: defaultName,
      filters: [{ name: extensions.join('/').toUpperCase(), extensions }],
    });
    return typeof picked === 'string' ? picked : null;
  },
};

// -- Warframe live -------------------------------------------------------

export const live = {
  status: () => invoke<WarframeStatus>('warframe_status'),
  isPlaying: () => invoke<boolean>('live_is_playing'),
  stop: () => invoke<void>('live_stop'),
  play: (
    events: LiveEventDto[],
    bindings: Record<string, string>,
    timing: Record<string, number>,
    requireFocus = true,
  ) =>
    invoke<void>('live_play', {
      request: {
        events,
        bindings: {
          string1: bindings.string1 ?? '1',
          string2: bindings.string2 ?? '2',
          string3: bindings.string3 ?? '3',
          fret1: bindings.fret1 ?? 'left',
          fret2: bindings.fret2 ?? 'down',
          fret3: bindings.fret3 ?? 'right',
        },
        timing: {
          playback_offset_ms: timing.playback_offset_ms ?? 0,
          fret_to_string_ms: timing.fret_to_string_ms ?? 12,
          inter_string_ms: timing.inter_string_ms ?? 4,
          key_hold_ms: timing.key_hold_ms ?? 14,
        },
        require_focus: requireFocus,
      },
    }),

  async onTick(handler: (tick: LiveTick) => void): Promise<() => void> {
    const b = await getBridge();
    if (!b.available) return () => undefined;
    return b.listen<LiveTick>('live://tick', ({ payload }) => handler(payload));
  },

  async onFinished(handler: (stats: LiveStats) => void): Promise<() => void> {
    const b = await getBridge();
    if (!b.available) return () => undefined;
    return b.listen<LiveStats>('live://finished', ({ payload }) => handler(payload));
  },
};

/** Files dropped onto the window arrive as a Tauri event, not a DOM event. */
export async function onFileDrop(
  handler: (paths: string[]) => void,
  onHover?: (hovering: boolean) => void,
): Promise<() => void> {
  const b = await getBridge();
  if (!b.available) return () => undefined;
  const { getCurrentWebview } = await import('@tauri-apps/api/webview');
  const unlisten = await getCurrentWebview().onDragDropEvent((event) => {
    if (event.payload.type === 'over') onHover?.(true);
    else if (event.payload.type === 'leave') onHover?.(false);
    else if (event.payload.type === 'drop') {
      onHover?.(false);
      handler(event.payload.paths);
    }
  });
  return unlisten;
}
