import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ErrorBoundary } from './ErrorBoundary';
import { ShawzinPicker } from './ShawzinPicker';
import { MatchNotice } from './SourceInput';
import { StructureBar, StructurePanel } from './Structure';
import { arrangementFixture } from '@/test/fixtures';
import { useStore } from '@/state/store';

const structure = arrangementFixture.structure!;
const suggestions = arrangementFixture.shawzinSuggestions;
const profile = arrangementFixture.musicProfile;

beforeEach(() => {
  useStore.setState({ reArrange: vi.fn(), arranging: false, expandedShawzin: null });
});

describe('MatchNotice', () => {
  it('says nothing when the match is certain', () => {
    const { container } = render(
      <MatchNotice confidence={1} reason="Local file." title="Song" />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it('reports an imperfect match with its reason', () => {
    render(
      <MatchNotice
        confidence={0.72}
        reason="Duration is 9s off; this may be a different edit."
        title="Ed Sheeran - Photograph"
      />,
    );
    expect(screen.getByText('72%')).toBeInTheDocument();
    expect(screen.getByText('Ed Sheeran - Photograph')).toBeInTheDocument();
    expect(screen.getByText(/different edit/)).toBeInTheDocument();
  });

  it('flags a genuinely uncertain match', () => {
    render(<MatchNotice confidence={0.35} reason="Probably a different version." title="X" />);
    expect(screen.getByText('35%')).toBeInTheDocument();
  });
});

describe('StructureBar', () => {
  it('renders one control per section, labelled by role', () => {
    render(<StructureBar structure={structure} duration={30} />);
    const buttons = screen.getAllByRole('button');
    expect(buttons).toHaveLength(structure.segments.length);
    expect(buttons[0]).toHaveAttribute('title', expect.stringContaining('intro'));
    expect(buttons[1]).toHaveAttribute('title', expect.stringContaining('chorus'));
  });

  it('reports the recognisability and repeat count in the tooltip', () => {
    render(<StructureBar structure={structure} duration={30} />);
    const chorus = screen.getAllByRole('button')[1];
    expect(chorus).toHaveAttribute('title', expect.stringContaining('94% recognisable'));
    expect(chorus).toHaveAttribute('title', expect.stringContaining('repeats 2'));
  });

  it('seeks to a section when clicked', async () => {
    const onSeek = vi.fn();
    render(<StructureBar structure={structure} duration={30} onSeek={onSeek} />);
    await userEvent.click(screen.getAllByRole('button')[1]);
    expect(onSeek).toHaveBeenCalledWith(12);
  });

  it('renders nothing without segments', () => {
    const { container } = render(
      <StructureBar
        structure={{ segments: [], hookIndex: null, hook: null, backend: 'events' }}
        duration={30}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});

describe('StructurePanel', () => {
  it('names where the hook is', () => {
    render(
      <StructurePanel structure={structure} duration={30} focusWindow={null} overLimit={false} />,
    );
    expect(screen.getByText('hook at 0:12')).toBeInTheDocument();
  });

  it('offers both focus modes and reports the choice', async () => {
    const reArrange = vi.fn();
    useStore.setState({ reArrange });
    render(
      <StructurePanel structure={structure} duration={30} focusWindow={null} overLimit={false} />,
    );
    expect(screen.getByRole('button', { name: 'Full Song' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    await userEvent.click(screen.getByRole('button', { name: 'Hook Only' }));
    expect(reArrange).toHaveBeenCalledWith({ focus: 'hook' });
  });

  it('explains what Hook Only is arranging', () => {
    useStore.setState({ options: { ...useStore.getState().options, focus: 'hook' } });
    render(
      <StructurePanel
        structure={structure}
        duration={274}
        focusWindow={[16.5, 256.5]}
        overLimit={false}
      />,
    );
    expect(screen.getByText(/0:16/)).toBeInTheDocument();
    expect(screen.getByText(/most likely to recognise/)).toBeInTheDocument();
  });

  it('says a long song will be split, and that Hook Only avoids it', () => {
    useStore.setState({ options: { ...useStore.getState().options, focus: 'full' } });
    render(
      <StructurePanel structure={structure} duration={400} focusWindow={null} overLimit />,
    );
    expect(screen.getByText(/split into parts/)).toBeInTheDocument();
  });

  it('says nothing is being left out when the song fits', () => {
    useStore.setState({ options: { ...useStore.getState().options, focus: 'full' } });
    render(
      <StructurePanel structure={structure} duration={30} focusWindow={null} overLimit={false} />,
    );
    expect(screen.getByText(/nothing is being left out/)).toBeInTheDocument();
  });

  it('stays hidden when there is no real structure to show', () => {
    const { container } = render(
      <StructurePanel
        structure={{ segments: [structure.segments[0]], hookIndex: 0, hook: null, backend: 'e' }}
        duration={30}
        focusWindow={null}
        overLimit={false}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});

describe('ShawzinPicker', () => {
  it('ranks the variants with scores and polyphony', () => {
    render(<ShawzinPicker suggestions={suggestions} profile={profile} current="dax" />);
    expect(screen.getByText("Dax's Shawzin")).toBeInTheDocument();
    expect(screen.getByText('86')).toBeInTheDocument();
    expect(screen.getByText(/3 notes at once/)).toBeInTheDocument();
    expect(screen.getByText(/1 note at a time/)).toBeInTheDocument();
  });

  it('shows the measured profile that drove the ranking', () => {
    render(<ShawzinPicker suggestions={suggestions} profile={profile} current="dax" />);
    expect(screen.getByText(/2\.4 notes\/s/)).toBeInTheDocument();
    expect(screen.getByText(/18% chords/)).toBeInTheDocument();
  });

  it('warns how many notes a variant would drop', () => {
    render(<ShawzinPicker suggestions={suggestions} profile={profile} current="dax" />);
    expect(screen.getByText('-12 notes')).toBeInTheDocument();
  });

  it('suggests switching when a better variant is available', async () => {
    const reArrange = vi.fn();
    useStore.setState({ reArrange });
    render(<ShawzinPicker suggestions={suggestions} profile={profile} current="corbu" />);
    expect(screen.getByText(/suits this better/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /Use Dax's Shawzin/ }));
    expect(reArrange).toHaveBeenCalledWith({ shawzinVariant: 'dax' });
  });

  it('does not nag when the best variant is already selected', () => {
    render(<ShawzinPicker suggestions={suggestions} profile={profile} current="dax" />);
    expect(screen.queryByText(/suits this better/)).not.toBeInTheDocument();
  });

  it('expands to show the reasoning, and can arrange for that variant', async () => {
    const reArrange = vi.fn();
    useStore.setState({ reArrange });
    render(<ShawzinPicker suggestions={suggestions} profile={profile} current="dax" />);

    await userEvent.click(screen.getByRole('button', { expanded: false, name: /Corbu Shawzin/ }));
    expect(screen.getByText(/every chord becomes a fast arpeggio/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Arrange for this Shawzin' }));
    expect(reArrange).toHaveBeenCalledWith({ shawzinVariant: 'corbu' });
  });

  it('renders nothing without suggestions', () => {
    const { container } = render(
      <ShawzinPicker suggestions={[]} profile={profile} current="dax" />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});

describe('ErrorBoundary', () => {
  function Boom(): never {
    throw new Error('kaboom in render');
  }

  it('shows the error instead of a blank page', () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
    render(
      <ErrorBoundary>
        <Boom />
      </ErrorBoundary>,
    );
    expect(screen.getByText(/hit an error/)).toBeInTheDocument();
    expect(screen.getByText('kaboom in render')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Reload' })).toBeInTheDocument();
    spy.mockRestore();
  });

  it('renders its children when nothing goes wrong', () => {
    render(
      <ErrorBoundary>
        <p>all good</p>
      </ErrorBoundary>,
    );
    expect(screen.getByText('all good')).toBeInTheDocument();
  });
});
