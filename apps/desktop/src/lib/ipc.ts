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
  MusicProfileDto,
  ProviderInfo,
  ResolvedSourceDto,
  SearchCandidateDto,
  ShawzinSuggestionDto,
  SpotifyCredentialsDto,
  StructureResponse,
  TrackReferenceDto,
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

/**
 * Injected into index.html by the local web server to identify the transport.
 *
 * It carries no token: the document is served without authorisation, so a
 * secret placed in it would be readable by anything on the machine. The page's
 * own URL carries the token instead.
 */
interface WebRuntime {
  server: string;
  version?: string;
}

declare global {
  interface Window {
    __SHAWZIFY_WEB__?: WebRuntime;
  }
}

export type Transport = 'tauri' | 'web' | 'none';

export function isTauri(): boolean {
  return typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window;
}

export function isWeb(): boolean {
  return typeof window !== 'undefined' && Boolean(window.__SHAWZIFY_WEB__);
}

/**
 * Which transport this build is running over.
 *
 * The same React app serves the desktop shell and the local web interface.
 * Tauri wins when both are somehow present, because a desktop window has
 * native file dialogs and live playback that the browser cannot reach.
 */
export function transport(): Transport {
  if (isTauri()) return 'tauri';
  if (isWeb()) return 'web';
  return 'none';
}

const webToken = (): string => {
  try {
    return new URLSearchParams(window.location.search).get('token') ?? '';
  } catch {
    return '';
  }
};

// -- web transport health -------------------------------------------------

type ProgressHandler = (payload: ProgressPayload) => void;
const progressHandlers = new Map<number, ProgressHandler>();

/**
 * Whether the page can still reach the local server.
 *
 * `offline` and `stale` are different problems with different fixes. A stopped
 * server may come back on the same URL, so retrying is worth it; a restarted
 * one issues a new token, which leaves this page permanently unauthorised and
 * retrying pointless. The UI says which of the two happened.
 */
export type Connection = 'connected' | 'reconnecting' | 'offline' | 'stale';

let connection: Connection = 'connected';
const connectionListeners = new Set<(state: Connection) => void>();

export function connectionState(): Connection {
  return connection;
}

function setConnection(next: Connection): void {
  if (connection === next) return;
  connection = next;
  for (const handler of connectionListeners) handler(next);
}

let stream: EventSource | null = null;
let retryTimer: ReturnType<typeof setTimeout> | undefined;
let retryAttempt = 0;

/** Ask the server whether it is alive, and whether this page's token still is. */
async function probe(): Promise<Connection> {
  try {
    const response = await fetch('/api/rpc?token=' + encodeURIComponent(webToken()), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ method: 'ping', params: {} }),
    });
    if (response.status === 403) return 'stale';
    return response.ok ? 'connected' : 'offline';
  } catch {
    return 'offline';
  }
}

function openStream(): void {
  if (stream || typeof EventSource === 'undefined') return;
  const source = new EventSource('/api/events?token=' + encodeURIComponent(webToken()));
  stream = source;

  source.onopen = () => {
    retryAttempt = 0;
    setConnection('connected');
  };

  source.onmessage = (event) => {
    try {
      const message = JSON.parse(event.data) as {
        id: number;
        event: string;
        payload: ProgressPayload;
      };
      const handler = progressHandlers.get(message.id);
      if (handler && message.event === 'progress') handler(message.payload);
    } catch {
      /* a malformed frame is not worth breaking the stream over */
    }
  };

  source.onerror = () => {
    // Left alone, EventSource retries every few seconds forever, with no
    // backoff and a console error per attempt -- hundreds of them if the
    // server stays down. Take the retry over so it backs off, and so it can
    // stop entirely when retrying cannot possibly work.
    source.close();
    if (stream === source) stream = null;
    if (connection === 'connected') setConnection('reconnecting');
    scheduleReconnect();
  };
}

function scheduleReconnect(): void {
  if (retryTimer !== undefined || connection === 'stale') return;
  const delay = Math.min(30000, 1000 * 2 ** retryAttempt);
  retryAttempt += 1;
  retryTimer = setTimeout(() => {
    retryTimer = undefined;
    void probe().then((state) => {
      setConnection(state);
      if (state === 'connected') openStream();
      else if (state !== 'stale') scheduleReconnect();
    });
  }, delay);
}

/** Retry immediately instead of waiting out the backoff. */
export function reconnect(): void {
  if (retryTimer !== undefined) {
    clearTimeout(retryTimer);
    retryTimer = undefined;
  }
  retryAttempt = 0;
  if (connection === 'stale') setConnection('offline');
  scheduleReconnect();
}

/**
 * Subscribe to transport health; the handler is called immediately with the
 * current state. On the web transport this also starts the event stream, which
 * is what notices a server going away in the first place.
 */
export function onConnection(handler: (state: Connection) => void): () => void {
  connectionListeners.add(handler);
  if (!isTauri() && isWeb()) openStream();
  handler(connection);
  return () => {
    connectionListeners.delete(handler);
  };
}

/** Call an engine method over HTTP, in the shape the Tauri command uses. */
async function webCall<T>(method: string, params: Record<string, unknown>): Promise<T> {
  let response: Response;
  try {
    response = await fetch('/api/rpc?token=' + encodeURIComponent(webToken()), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ method, params }),
    });
  } catch (err) {
    // fetch only rejects when the request never reached a server at all.
    setConnection('offline');
    scheduleReconnect();
    throw normalizeError({
      code: 'server_gone',
      message: 'The SHAWZIFY server is not running, so nothing can be processed.',
      hint: 'Start it again with: scripts\\dev.ps1 -Cli web, then open the link it prints.',
      technical: String(err),
    });
  }
  if (response.status === 403) {
    setConnection('stale');
    throw normalizeError({
      code: 'web_transport',
      message: 'This page is from an earlier run of the server, so its token expired.',
      hint: 'Open the link the current server printed.',
      technical: null,
    });
  }
  if (!response.ok) {
    throw normalizeError({
      code: 'web_transport',
      message: 'The SHAWZIFY engine returned ' + response.status + '.',
      hint: null,
      technical: null,
    });
  }
  if (connection !== 'connected') {
    setConnection('connected');
    openStream();
  }
  const payload = (await response.json()) as { result?: T; error?: EngineError };
  if (payload.error) throw normalizeError(payload.error);
  return payload.result as T;
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

/** Tauri commands with no HTTP equivalent: they need the native shell. */
const DESKTOP_ONLY = new Set([
  'live_play',
  'live_stop',
  'live_is_playing',
  'warframe_status',
  'copy_to_clipboard',
  'reveal_path',
  'startup_file',
]);

async function invoke<T>(cmd: string, args?: Record<string, unknown>): Promise<T> {
  if (!isTauri() && isWeb()) {
    if (cmd === 'engine_call') {
      const a = (args ?? {}) as { method: string; params?: Record<string, unknown> };
      return webCall<T>(a.method, a.params ?? {});
    }
    if (cmd === 'engine_status') {
      return { running: true, python: null, root: '', error: null } as unknown as T;
    }
    if (cmd === 'engine_start' || cmd === 'engine_restart') {
      return { running: true, python: null, root: '', error: null } as unknown as T;
    }
    if (cmd === 'warframe_status') {
      return { found: false, focused: false, title: null, supported: false } as unknown as T;
    }
    if (cmd === 'startup_file') return null as unknown as T;
    if (cmd === 'live_is_playing') return false as unknown as T;
    if (DESKTOP_ONLY.has(cmd)) {
      throw normalizeError({
        code: 'desktop_only',
        message: 'That needs the SHAWZIFY desktop app.',
        hint: 'Live Warframe playback and native file dialogs are desktop-only.',
        technical: cmd,
      });
    }
  }
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

let progressBound = false;

async function bindProgress(): Promise<void> {
  if (progressBound) return;
  progressBound = true;

  if (!isTauri() && isWeb()) {
    // The web transport streams the same events over SSE. openStream() owns
    // the connection so that a server going away backs off rather than
    // retrying forever.
    openStream();
    return;
  }

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

  /** Identify a link without downloading anything. */
  identify: (target: string) =>
    invoke<ResolvedSourceDto>('engine_call', { method: 'identify', params: { target } }),

  sources: () =>
    invoke<{ providers: ProviderInfo[] }>('engine_call', { method: 'sources', params: {} }),

  searchTracks: (query: string, limit = 6) =>
    invoke<{ results: SearchCandidateDto[] }>('engine_call', {
      method: 'search',
      params: { query, limit },
    }),

  spotifyCredentials: (save?: { clientId: string; clientSecret: string }) =>
    invoke<SpotifyCredentialsDto>('engine_call', {
      method: 'spotifyCredentials',
      params: save ? { save } : {},
    }),

  recommendShawzin: (sourceId: string, current?: string) =>
    invoke<{ profile: MusicProfileDto; suggestions: ShawzinSuggestionDto[] }>('engine_call', {
      method: 'recommendShawzin',
      params: { sourceId, current },
    }),

  structure: (sourceId: string, windowSeconds = 240) =>
    invoke<StructureResponse>('engine_call', {
      method: 'structure',
      params: { sourceId, windowSeconds },
    }),

  /** Download a link and analyse it, as one operation. */
  async fetch(
    target: string,
    opts: {
      useStems?: boolean;
      candidateIndex?: number;
      onProgress?: ProgressHandler;
    } = {},
  ): Promise<SourceDto & { track?: TrackReferenceDto; matchConfidence?: number; matchReason?: string }> {
    const requestId = newRequestId();
    return withProgress(requestId, opts.onProgress, () =>
      invoke('engine_call', {
        method: 'fetch',
        params: {
          target,
          requestId,
          analyze: true,
          useStems: opts.useStems ?? true,
          candidateIndex: opts.candidateIndex ?? 0,
        },
      }),
    );
  },

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

/** A URL the page can play, for a file the engine produced. */
export async function mediaUrl(path: string): Promise<string> {
  if (isTauri()) {
    const { convertFileSrc } = await import('@tauri-apps/api/core');
    return convertFileSrc(path);
  }
  return '/media?token=' + encodeURIComponent(webToken()) + '&path=' + encodeURIComponent(path);
}

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
    if (!isTauri()) return null; // the browser cannot hand over a real path
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
