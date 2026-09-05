/**
 * The web transport's health tracking.
 *
 * These are regression tests for a real failure: the server was stopped while a
 * page was open, and the browser's own EventSource retry hammered the dead port
 * every few seconds forever while the interface still looked healthy.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { Connection } from '@/lib/ipc';

class FakeEventSource {
  static instances: FakeEventSource[] = [];

  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  closed = false;

  constructor(readonly url: string) {
    FakeEventSource.instances.push(this);
  }

  close() {
    this.closed = true;
  }
}

/** Import a fresh copy of the module and start watching, recording states. */
async function freshIpc() {
  vi.resetModules();
  const ipc = await import('@/lib/ipc');
  const states: Connection[] = [];
  ipc.onConnection((state) => states.push(state));
  return { ipc, states };
}

const latestStream = () => FakeEventSource.instances[FakeEventSource.instances.length - 1];

describe('web transport health', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    FakeEventSource.instances = [];
    window.__SHAWZIFY_WEB__ = { token: 'test-token' };
    globalThis.EventSource = FakeEventSource as unknown as typeof EventSource;
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    delete window.__SHAWZIFY_WEB__;
  });

  it('backs off instead of reconnecting on a fixed interval', async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError('Failed to fetch'));
    vi.stubGlobal('fetch', fetchMock);

    const { states } = await freshIpc();
    expect(FakeEventSource.instances).toHaveLength(1);
    expect(states).toEqual(['connected']);

    latestStream().onerror?.();
    // The failed stream is closed rather than left to retry on its own.
    expect(latestStream().closed).toBe(true);
    expect(states.at(-1)).toBe('reconnecting');
    expect(fetchMock).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(1000);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(states.at(-1)).toBe('offline');

    // Second wait is twice the first, so a server that stays down is polled
    // less and less rather than once every few seconds forever.
    await vi.advanceTimersByTimeAsync(1999);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(fetchMock).toHaveBeenCalledTimes(2);

    // And no second stream was opened while the server was unreachable.
    expect(FakeEventSource.instances).toHaveLength(1);
  });

  it('stops retrying when the page token belongs to an earlier server', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: false, status: 403 });
    vi.stubGlobal('fetch', fetchMock);

    const { states } = await freshIpc();
    latestStream().onerror?.();
    await vi.advanceTimersByTimeAsync(1000);
    expect(states.at(-1)).toBe('stale');

    // A new token cannot appear without a reload, so retrying is pointless.
    await vi.advanceTimersByTimeAsync(120_000);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('reopens the stream once the server answers again', async () => {
    const fetchMock = vi
      .fn()
      .mockRejectedValueOnce(new TypeError('Failed to fetch'))
      .mockResolvedValue({ ok: true, status: 200 });
    vi.stubGlobal('fetch', fetchMock);

    const { ipc, states } = await freshIpc();
    latestStream().onerror?.();
    await vi.advanceTimersByTimeAsync(1000);
    expect(states.at(-1)).toBe('offline');

    ipc.reconnect();
    await vi.advanceTimersByTimeAsync(1000);

    expect(states.at(-1)).toBe('connected');
    expect(FakeEventSource.instances).toHaveLength(2);
    expect(latestStream().closed).toBe(false);
  });

  it('reports a stopped server as such, not as a network error', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));

    const { ipc } = await freshIpc();
    await expect(ipc.engine.environment()).rejects.toMatchObject({
      code: 'server_gone',
      message: expect.stringContaining('not running'),
      hint: expect.stringContaining('-Cli web'),
    });
    expect(ipc.connectionState()).toBe('offline');
  });

  it('routes progress events from the stream to the call that is waiting', async () => {
    const fetchMock = vi.fn(async (_url: string, init: { body: string }) => {
      // The engine echoes the request id it was given; the stream keys
      // progress frames by it, which is what this asserts.
      const params = (JSON.parse(init.body) as { params: { requestId: number } }).params;
      latestStream().onmessage?.({
        data: JSON.stringify({
          id: params.requestId,
          event: 'progress',
          payload: {
            stage: 'decode',
            label: 'Decoding',
            stageFraction: 0.5,
            overallFraction: 0.1,
            message: null,
          },
        }),
      });
      return { ok: true, status: 200, json: async () => ({ result: { id: 'source-1' } }) };
    });
    vi.stubGlobal('fetch', fetchMock);

    const { ipc } = await freshIpc();
    const stages: string[] = [];
    await ipc.engine.analyze('song.wav', {}, { onProgress: (p) => stages.push(p.stage) });

    expect(stages).toEqual(['decode']);
  });
});
