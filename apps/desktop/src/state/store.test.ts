import { beforeEach, describe, expect, it, vi } from 'vitest';

import { DEFAULT_OPTIONS, selectBusy, selectCanPlayLive, useStore } from './store';
import { ShawzifyError, normalizeError } from '@/lib/ipc';
import {
  arrangementFixture,
  environmentFixture,
  instrumentFixture,
  keymapFixture,
  sourceFixture,
} from '@/test/fixtures';

vi.mock('@/lib/ipc', async () => {
  const actual = await vi.importActual<typeof import('@/lib/ipc')>('@/lib/ipc');
  return {
    ...actual,
    engine: {
      status: vi.fn(async () => ({ running: true, python: 'py', root: '/', error: null })),
      start: vi.fn(async () => ({ running: true, python: 'py', root: '/', error: null })),
      environment: vi.fn(async () => environmentFixture),
      instrument: vi.fn(async () => instrumentFixture),
      keymap: vi.fn(async () => keymapFixture),
      recents: vi.fn(async () => ({ recents: [] })),
      analyze: vi.fn(async () => sourceFixture),
      arrange: vi.fn(async () => arrangementFixture),
      openProject: vi.fn(async () => ({
        sourceId: 'p',
        source: sourceFixture,
        code: 'x',
        reproducible: true,
      })),
    },
    live: { status: vi.fn(async () => ({ found: true, focused: false, title: 'Warframe', supported: true })) },
  };
});

const initial = useStore.getState();

beforeEach(() => {
  useStore.setState({
    ...initial,
    source: null,
    arrangement: null,
    options: DEFAULT_OPTIONS,
    toasts: [],
    error: null,
    analyzing: false,
    arranging: false,
  });
  vi.clearAllMocks();
});

describe('bootstrap', () => {
  it('loads the environment, instrument and keymap', async () => {
    await useStore.getState().bootstrap();
    const state = useStore.getState();
    expect(state.engineReady).toBe(true);
    expect(state.environment?.gpu.cuda).toBe(true);
    expect(state.instrument?.scales).toHaveLength(2);
    expect(state.keymap?.keymap.bindings.string1).toBe('1');
  });

  it('reports an engine failure instead of crashing', async () => {
    const { engine } = await import('@/lib/ipc');
    vi.mocked(engine.status).mockRejectedValueOnce(
      new ShawzifyError({ code: 'x', message: 'Engine down.', hint: null, technical: null }),
    );
    vi.mocked(engine.start).mockRejectedValueOnce(
      new ShawzifyError({ code: 'x', message: 'Engine down.', hint: null, technical: null }),
    );
    await useStore.getState().bootstrap();
    expect(useStore.getState().engineReady).toBe(false);
    expect(useStore.getState().engineMessage).toBe('Engine down.');
  });
});

describe('openFile', () => {
  it('analyses then arranges, and lands in the workspace', async () => {
    const { engine } = await import('@/lib/ipc');
    await useStore.getState().openFile('C:/song.mp3');
    const state = useStore.getState();
    expect(engine.analyze).toHaveBeenCalledOnce();
    expect(engine.arrange).toHaveBeenCalledOnce();
    expect(state.source?.title).toBe('Demo Melody');
    expect(state.arrangement?.code).toBe(arrangementFixture.code);
    expect(state.view).toBe('workspace');
    expect(state.analyzing).toBe(false);
    expect(state.arranging).toBe(false);
  });

  it('surfaces an engine error as a toast, not an exception', async () => {
    const { engine } = await import('@/lib/ipc');
    vi.mocked(engine.analyze).mockRejectedValueOnce(
      new ShawzifyError({
        code: 'audio_decode_failed',
        message: 'That audio file could not be read.',
        hint: null,
        technical: 'stack',
      }),
    );
    await useStore.getState().openFile('C:/broken.mp3');
    const state = useStore.getState();
    expect(state.analyzing).toBe(false);
    expect(state.error?.code).toBe('audio_decode_failed');
    expect(state.toasts[0]?.kind).toBe('error');
    expect(state.toasts[0]?.detail).toBe('stack');
  });

  it('shows engine warnings to the user', async () => {
    const { engine } = await import('@/lib/ipc');
    vi.mocked(engine.analyze).mockResolvedValueOnce({
      ...sourceFixture,
      warnings: ['Stem separation is unavailable, so the full mix was used.'],
    });
    await useStore.getState().openFile('C:/song.mp3');
    expect(useStore.getState().toasts.map((t) => t.message)).toContain(
      'Stem separation is unavailable, so the full mix was used.',
    );
  });
});

describe('reArrange', () => {
  it('re-runs only the arrangement, never the analysis', async () => {
    const { engine } = await import('@/lib/ipc');
    await useStore.getState().openFile('C:/song.mp3');
    vi.mocked(engine.analyze).mockClear();
    vi.mocked(engine.arrange).mockClear();

    await useStore.getState().reArrange({ mode: 'chordal' });

    expect(engine.analyze).not.toHaveBeenCalled();
    expect(engine.arrange).toHaveBeenCalledOnce();
    expect(useStore.getState().options.mode).toBe('chordal');
  });

  it('merges the patch into the existing options', async () => {
    await useStore.getState().openFile('C:/song.mp3');
    await useStore.getState().reArrange({ complexity: 0.9 });
    await useStore.getState().reArrange({ scale: 'pmin' });
    const options = useStore.getState().options;
    expect(options.complexity).toBe(0.9);
    expect(options.scale).toBe('pmin');
    expect(options.mode).toBe('balanced');
  });

  it('does nothing without a loaded source', async () => {
    const { engine } = await import('@/lib/ipc');
    await useStore.getState().reArrange({ mode: 'melody' });
    expect(engine.arrange).not.toHaveBeenCalled();
    expect(useStore.getState().options.mode).toBe('melody');
  });
});

describe('toasts', () => {
  it('adds and dismisses', () => {
    const { toast, dismissToast } = useStore.getState();
    toast('success', 'Copied.');
    const id = useStore.getState().toasts[0].id;
    expect(useStore.getState().toasts).toHaveLength(1);
    dismissToast(id);
    expect(useStore.getState().toasts).toHaveLength(0);
  });
});

describe('selectors', () => {
  it('selectBusy covers both loading phases', () => {
    useStore.setState({ analyzing: true, arranging: false });
    expect(selectBusy(useStore.getState())).toBe(true);
    useStore.setState({ analyzing: false, arranging: true });
    expect(selectBusy(useStore.getState())).toBe(true);
    useStore.setState({ analyzing: false, arranging: false });
    expect(selectBusy(useStore.getState())).toBe(false);
  });

  it('live playback needs an arrangement, Warframe and a clean keymap', () => {
    useStore.setState({
      arrangement: arrangementFixture,
      warframe: { found: true, focused: true, title: 'Warframe', supported: true },
      keymap: keymapFixture,
    });
    expect(selectCanPlayLive(useStore.getState())).toBe(true);

    useStore.setState({ warframe: { found: false, focused: false, title: null, supported: true } });
    expect(selectCanPlayLive(useStore.getState())).toBe(false);

    useStore.setState({
      warframe: { found: true, focused: true, title: 'Warframe', supported: true },
      keymap: { ...keymapFixture, problems: ['Sky Fret and 1st String are both bound to 1.'] },
    });
    expect(selectCanPlayLive(useStore.getState())).toBe(false);
  });
});

describe('error normalisation', () => {
  it('keeps a structured engine error intact', () => {
    const err = normalizeError({
      code: 'ffmpeg_missing',
      message: 'FFmpeg is not available.',
      hint: 'Run setup.ps1',
      technical: null,
    });
    expect(err).toBeInstanceOf(ShawzifyError);
    expect(err.code).toBe('ffmpeg_missing');
    expect(err.hint).toBe('Run setup.ps1');
  });

  it('makes something readable out of anything else', () => {
    expect(normalizeError('boom').message).toBe('boom');
    expect(normalizeError(undefined).message).toBe('Something went wrong.');
    expect(normalizeError(new Error('kaboom')).message).toBe('kaboom');
  });
});
