/**
 * What the browser transport has to do differently.
 *
 * Both of these were silently broken: the file buttons and every export button
 * called a native dialog that returns null outside the desktop shell, so in a
 * browser tab they did nothing at all — no file, no error, no toast.
 */
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { Export } from './Export';
import { Home } from './Home';
import { arrangementFixture, instrumentFixture, sourceFixture } from '@/test/fixtures';
import { useStore } from '@/state/store';

// vi.mock is hoisted above the imports, so the doubles have to be too.
const { engineExport, downloadFromCache, uploadFile, pickSavePath, pickFile } = vi.hoisted(() => ({
  engineExport: vi.fn(),
  downloadFromCache: vi.fn(),
  uploadFile: vi.fn(),
  pickSavePath: vi.fn(),
  pickFile: vi.fn(),
}));

vi.mock('@/lib/ipc', async () => {
  const actual = await vi.importActual<typeof import('@/lib/ipc')>('@/lib/ipc');
  return {
    ...actual,
    engine: { ...actual.engine, export: engineExport },
    system: {
      ...actual.system,
      downloadFromCache,
      uploadFile,
      pickSavePath,
      pickFile,
    },
  };
});

beforeEach(() => {
  vi.clearAllMocks();
  engineExport.mockResolvedValue({ path: 'C:/cache/exports/demo.shawzin.txt', kind: 'code' });
  uploadFile.mockResolvedValue('C:/cache/uploads/demo-abc123.wav');
  pickSavePath.mockResolvedValue(null);
  pickFile.mockResolvedValue(null);
  useStore.setState({ transport: 'web', instrument: instrumentFixture, keymap: null });
});

describe('exporting from a browser tab', () => {
  it('exports without a path and downloads the result', async () => {
    const user = userEvent.setup();
    render(<Export arrangement={arrangementFixture} source={sourceFixture} />);

    await user.click(screen.getByRole('button', { name: /^save code$/i }));

    // No native save dialog: the engine writes into its cache and the page
    // downloads from there.
    expect(pickSavePath).not.toHaveBeenCalled();
    expect(engineExport).toHaveBeenCalledWith(sourceFixture.sourceId, 'code');
    expect(downloadFromCache).toHaveBeenCalledWith(
      'C:/cache/exports/demo.shawzin.txt',
      expect.stringContaining('.shawzin.txt'),
    );
  });

  it('still uses the native dialog in the desktop shell', async () => {
    useStore.setState({ transport: 'tauri' });
    pickSavePath.mockResolvedValue('C:/Users/me/song.shawzin.txt');
    const user = userEvent.setup();
    render(<Export arrangement={arrangementFixture} source={sourceFixture} />);

    await user.click(screen.getByRole('button', { name: /^save code$/i }));

    expect(pickSavePath).toHaveBeenCalled();
    expect(engineExport).toHaveBeenCalledWith(
      sourceFixture.sourceId,
      'code',
      'C:/Users/me/song.shawzin.txt',
    );
    expect(downloadFromCache).not.toHaveBeenCalled();
  });
});

describe('opening a file from a browser tab', () => {
  it('offers a file input rather than a dialog that cannot work', async () => {
    const user = userEvent.setup();
    const { container } = render(<Home />);

    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    expect(input).not.toBeNull();

    const file = new File([new Uint8Array([1, 2, 3])], 'song.wav', { type: 'audio/wav' });
    await user.upload(input, file);

    expect(uploadFile).toHaveBeenCalledWith(file);
    expect(pickFile).not.toHaveBeenCalled();
  });
});
