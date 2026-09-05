/** Small shared pieces. Kept minimal on purpose -- this is not a UI kit. */

import { motion } from 'framer-motion';
import type { ReactNode } from 'react';

/**
 * A panel sizes to its content by default. `grow` opts into filling the
 * remaining height -- without that distinction, panels stacked in a scrolling
 * column compress into each other instead of scrolling.
 */
export function Panel({
  title,
  action,
  children,
  className = '',
  dense = false,
  grow = false,
}: {
  title?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
  dense?: boolean;
  grow?: boolean;
}) {
  return (
    <section className={`surface flex flex-col ${className}`}>
      {title && (
        <header className="flex items-center justify-between px-4 h-10 border-b divider shrink-0">
          <h2 className="label">{title}</h2>
          {action}
        </header>
      )}
      <div
        className={`${grow ? 'flex-1 min-h-0 flex flex-col' : ''} ${dense ? '' : 'p-4'}`}
      >
        {children}
      </div>
    </section>
  );
}

export function Stat({
  label,
  value,
  hint,
  tone = 'default',
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  tone?: 'default' | 'amber' | 'cyan' | 'dim';
}) {
  const toneClass =
    tone === 'amber'
      ? 'text-amber-bright'
      : tone === 'cyan'
        ? 'text-cyan'
        : tone === 'dim'
          ? 'text-paper-dim'
          : 'text-paper';
  return (
    <div className="min-w-0">
      <div className="label mb-1">{label}</div>
      <div className={`text-[15px] font-medium tabular-nums truncate ${toneClass}`}>{value}</div>
      {hint && <div className="text-2xs text-paper-faint mt-0.5 truncate">{hint}</div>}
    </div>
  );
}

/** A labelled bar. `tone` shifts hue as the value gets worse. */
export function MeterRow({
  label,
  value,
  suffix = '%',
}: {
  label: string;
  value: number;
  suffix?: string;
}) {
  const pct = Math.max(0, Math.min(100, value));
  const hue = pct >= 85 ? 'bg-amber' : pct >= 65 ? 'bg-amber-deep' : 'bg-paper-faint';
  return (
    <div className="flex items-center gap-3">
      <div className="w-40 shrink-0 text-xs text-paper-dim">{label}</div>
      <div className="flex-1 h-1 rounded-full bg-white/[0.07] overflow-hidden">
        <motion.div
          className={`h-full ${hue}`}
          initial={{ width: 0 }}
          animate={{ width: `${pct}%` }}
          transition={{ duration: 0.45, ease: [0.22, 1, 0.36, 1] }}
        />
      </div>
      <div className="w-12 text-right text-xs tabular-nums text-paper">
        {pct.toFixed(1)}
        {suffix}
      </div>
    </div>
  );
}

export function Slider({
  label,
  value,
  min,
  max,
  step = 1,
  onChange,
  format,
  disabled,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step?: number;
  onChange: (value: number) => void;
  format?: (value: number) => string;
  disabled?: boolean;
}) {
  return (
    <label className="block">
      <div className="flex items-baseline justify-between mb-1">
        <span className="label">{label}</span>
        <span className="text-xs tabular-nums text-paper-dim">
          {format ? format(value) : value}
        </span>
      </div>
      <input
        type="range"
        className="w-full"
        min={min}
        max={max}
        step={step}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(Number(e.target.value))}
        aria-label={label}
      />
    </label>
  );
}

export function Segmented<T extends string>({
  options,
  value,
  onChange,
  label,
}: {
  options: { value: T; label: string; title?: string }[];
  value: T;
  onChange: (value: T) => void;
  label?: string;
}) {
  return (
    <div>
      {label && <div className="label mb-1.5">{label}</div>}
      <div className="segmented" role="group" aria-label={label}>
        {options.map((option) => (
          <button
            key={option.value}
            type="button"
            title={option.title}
            data-active={option.value === value}
            aria-pressed={option.value === value}
            onClick={() => onChange(option.value)}
          >
            {option.label}
          </button>
        ))}
      </div>
    </div>
  );
}

export function Toggle({
  label,
  checked,
  onChange,
  hint,
  disabled,
}: {
  label: string;
  checked: boolean;
  onChange: (value: boolean) => void;
  hint?: string;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className="flex items-center justify-between w-full text-left group disabled:opacity-40"
    >
      <span className="min-w-0">
        <span className="block text-sm text-paper">{label}</span>
        {hint && <span className="block text-2xs text-paper-faint mt-0.5">{hint}</span>}
      </span>
      <span
        className={`relative shrink-0 ml-3 w-9 h-5 rounded-full transition-colors duration-150 ${
          checked ? 'bg-amber/80' : 'bg-white/[0.1]'
        }`}
      >
        <motion.span
          className="absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-ink-900"
          animate={{ x: checked ? 16 : 0 }}
          transition={{ type: 'spring', stiffness: 520, damping: 34 }}
        />
      </span>
    </button>
  );
}

export function Select<T extends string>({
  label,
  value,
  options,
  onChange,
  disabled,
}: {
  label: string;
  value: T;
  options: { value: T; label: string }[];
  onChange: (value: T) => void;
  disabled?: boolean;
}) {
  return (
    <label className="block">
      <span className="label block mb-1.5">{label}</span>
      <select
        className="field w-full appearance-none pr-7 bg-[url('data:image/svg+xml;utf8,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 12 12%22 fill=%22%23A9A69F%22><path d=%22M3 4.5 6 8l3-3.5z%22/></svg>')] bg-no-repeat bg-[right_0.5rem_center]"
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value as T)}
        aria-label={label}
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  );
}

export function Skeleton({ className = '' }: { className?: string }) {
  return (
    <div className={`rounded-md bg-white/[0.045] animate-pulse ${className}`} aria-hidden="true" />
  );
}

export function EmptyHint({ children }: { children: ReactNode }) {
  return (
    <div className="h-full flex items-center justify-center text-center px-6">
      <p className="text-sm text-paper-faint max-w-xs text-balance">{children}</p>
    </div>
  );
}

export function formatTime(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return '0:00';
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, '0')}`;
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(0)} KB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
}
