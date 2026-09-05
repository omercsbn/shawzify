import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { Analyzing } from './Analyzing';
import { Compatibility } from './Compatibility';
import { Controls } from './Controls';
import { PianoRoll } from './PianoRoll';
import { ShawzinDiagram } from './ShawzinDiagram';
import { Waveform } from './Waveform';
import { MeterRow, Segmented, Slider, Toggle, formatBytes, formatTime } from './primitives';
import { arrangementFixture, instrumentFixture, sourceFixture } from '@/test/fixtures';
import { useStore } from '@/state/store';

describe('formatting helpers', () => {
  it('formats times as m:ss', () => {
    expect(formatTime(0)).toBe('0:00');
    expect(formatTime(9)).toBe('0:09');
    expect(formatTime(65)).toBe('1:05');
    expect(formatTime(222)).toBe('3:42');
  });

  it('never renders a negative or NaN time', () => {
    expect(formatTime(-5)).toBe('0:00');
    expect(formatTime(Number.NaN)).toBe('0:00');
  });

  it('formats byte sizes', () => {
    expect(formatBytes(512)).toBe('512 B');
    expect(formatBytes(2048)).toBe('2 KB');
    expect(formatBytes(1_500_000)).toBe('1.4 MB');
  });
});

describe('Compatibility panel', () => {
  it('shows both the original and optimized scores', () => {
    render(<Compatibility arrangement={arrangementFixture} advanced={false} />);
    expect(screen.getByText('Original')).toBeInTheDocument();
    expect(screen.getByText('Optimized')).toBeInTheDocument();
    expect(screen.getByText('51')).toBeInTheDocument();
    expect(screen.getByText('91')).toBeInTheDocument();
  });

  it('names the recommended scale and transposition', () => {
    render(<Compatibility arrangement={arrangementFixture} advanced={false} />);
    expect(screen.getByText('Major')).toBeInTheDocument();
    expect(screen.getByText('-12 semitones')).toBeInTheDocument();
  });

  it('breaks the score down rather than showing one opaque number', () => {
    render(<Compatibility arrangement={arrangementFixture} advanced={false} />);
    for (const label of [
      'Pitch Coverage',
      'Melody Preservation',
      'Rhythm Preservation',
      'Harmony Preservation',
    ]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
  });

  it('offers alternative scales only in advanced view, and reports them', async () => {
    const onScalePick = vi.fn();
    const { rerender } = render(
      <Compatibility arrangement={arrangementFixture} advanced={false} onScalePick={onScalePick} />,
    );
    expect(screen.queryByText('Other scales considered')).not.toBeInTheDocument();

    rerender(
      <Compatibility arrangement={arrangementFixture} advanced onScalePick={onScalePick} />,
    );
    expect(screen.getByText('Other scales considered')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /Minor/ }));
    expect(onScalePick).toHaveBeenCalledWith('min', -9);
  });
});

describe('Analyzing screen', () => {
  it('lists every pipeline stage', () => {
    render(<Analyzing progress={null} title="Song.mp3" />);
    for (const label of [
      'Loading audio',
      'Separating stems',
      'Transcribing notes',
      'Optimizing arrangement',
      'Encoding performance',
    ]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
  });

  it('shows the real reported percentage, not a made-up one', () => {
    render(
      <Analyzing
        title="Song.mp3"
        progress={{
          stage: 'transcribe',
          label: 'Transcribing notes',
          stageFraction: 0.5,
          overallFraction: 0.42,
          message: 'Found 128 notes',
        }}
      />,
    );
    expect(screen.getByText('42%')).toBeInTheDocument();
    expect(screen.getByText('Found 128 notes')).toBeInTheDocument();
  });

  it('offers a cancel action when one is available', async () => {
    const onCancel = vi.fn();
    render(<Analyzing progress={null} title="x" onCancel={onCancel} />);
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(onCancel).toHaveBeenCalled();
  });
});

describe('primitives', () => {
  it('Segmented reports the chosen value', async () => {
    const onChange = vi.fn();
    render(
      <Segmented
        label="Mode"
        value="balanced"
        options={[
          { value: 'melody', label: 'Melody' },
          { value: 'balanced', label: 'Balanced' },
        ]}
        onChange={onChange}
      />,
    );
    expect(screen.getByRole('button', { name: 'Balanced' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    await userEvent.click(screen.getByRole('button', { name: 'Melody' }));
    expect(onChange).toHaveBeenCalledWith('melody');
  });

  it('Toggle exposes switch semantics', async () => {
    const onChange = vi.fn();
    render(<Toggle label="Preserve melody" checked={false} onChange={onChange} />);
    const toggle = screen.getByRole('switch', { name: 'Preserve melody' });
    expect(toggle).toHaveAttribute('aria-checked', 'false');
    await userEvent.click(toggle);
    expect(onChange).toHaveBeenCalledWith(true);
  });

  it('Slider reports numeric values', async () => {
    const onChange = vi.fn();
    render(<Slider label="Complexity" value={50} min={0} max={100} onChange={onChange} />);
    const slider = screen.getByLabelText('Complexity');
    expect(slider).toHaveValue('50');
  });

  it('MeterRow clamps out-of-range values', () => {
    render(<MeterRow label="Coverage" value={140} />);
    expect(screen.getByText('100.0%')).toBeInTheDocument();
  });
});

describe('Waveform', () => {
  it('renders without a waveform payload', () => {
    const { container } = render(
      <Waveform waveform={null} duration={0} playhead={0} />,
    );
    expect(container.querySelector('canvas')).toBeTruthy();
  });

  it('seeks to the clicked position', async () => {
    const onSeek = vi.fn();
    render(
      <Waveform
        waveform={sourceFixture.waveform!}
        duration={30}
        playhead={5}
        onSeek={onSeek}
      />,
    );
    const slider = screen.getByRole('slider', { name: 'Seek' });
    slider.focus();
    await userEvent.keyboard('{ArrowRight}');
    expect(onSeek).toHaveBeenCalledWith(10);
  });

  it('shows the playhead and total time', () => {
    render(
      <Waveform waveform={sourceFixture.waveform!} duration={222} playhead={65} />,
    );
    expect(screen.getByText('1:05')).toBeInTheDocument();
    expect(screen.getByText('3:42')).toBeInTheDocument();
  });
});

describe('PianoRoll', () => {
  it('renders a legend explaining every marker colour', () => {
    render(
      <PianoRoll
        arrangement={arrangementFixture}
        sourceEvents={sourceFixture.events!}
        duration={30}
        playhead={0}
        selected={null}
      />,
    );
    for (const label of [
      'Played as written',
      'Moved to fit',
      'Arpeggiated',
      'Removed',
    ]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
  });

  it('handles an arrangement that is not ready yet', () => {
    const { container } = render(
      <PianoRoll
        arrangement={null}
        sourceEvents={[]}
        duration={0}
        playhead={0}
        selected={null}
      />,
    );
    expect(container.querySelector('canvas')).toBeTruthy();
  });
});

describe('ShawzinDiagram', () => {
  it('marks the held fret and plucked string', () => {
    const { container } = render(
      <ShawzinDiagram fret="12" strings="2" noteNames={['G4']} />,
    );
    expect(screen.getByText('G4')).toBeInTheDocument();
    expect(within(container).getByText('Sky')).toBeInTheDocument();
    expect(within(container).getByText('Earth')).toBeInTheDocument();
  });

  it('renders an open-string event', () => {
    render(<ShawzinDiagram fret="0" strings="1" noteNames={['C3']} />);
    expect(screen.getByText('C3')).toBeInTheDocument();
  });
});

describe('Controls', () => {
  it('lists every arrangement mode', () => {
    render(<Controls instrument={instrumentFixture} />);
    for (const mode of ['Melody', 'Balanced', 'Chordal', 'Virtuoso']) {
      expect(screen.getByRole('button', { name: mode })).toBeInTheDocument();
    }
  });

  it('changing mode calls reArrange with only that change', async () => {
    const reArrange = vi.fn();
    useStore.setState({ reArrange });
    render(<Controls instrument={instrumentFixture} />);
    await userEvent.click(screen.getByRole('button', { name: 'Chordal' }));
    expect(reArrange).toHaveBeenCalledWith({ mode: 'chordal' });
  });

  it('hides advanced controls until asked', async () => {
    useStore.setState({ advanced: false, reArrange: vi.fn() });
    render(<Controls instrument={instrumentFixture} />);
    expect(screen.queryByLabelText('Quantization')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Advanced' }));
    expect(screen.getByLabelText('Quantization')).toBeInTheDocument();
  });

  it('offers Auto for scale and transpose', () => {
    useStore.setState({ advanced: false, reArrange: vi.fn() });
    render(<Controls instrument={instrumentFixture} />);
    const scale = screen.getByLabelText('Scale') as HTMLSelectElement;
    expect(Array.from(scale.options).map((o) => o.value)).toContain('auto');
    expect(Array.from(scale.options).map((o) => o.text)).toContain('Pentatonic Minor');
  });
});
