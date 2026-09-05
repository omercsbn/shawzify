/**
 * A crash in the UI must never be a blank window.
 *
 * Without this, any render-time exception leaves an empty page with the real
 * cause only visible in a devtools console the user is unlikely to open --
 * which is exactly the "silently swallow the exception" failure the rest of
 * the app is built to avoid.
 */

import { Component, type ErrorInfo, type ReactNode } from 'react';

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
  stack: string | null;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null, stack: null };

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    this.setState({ stack: info.componentStack ?? null });
    // Also to the console, so a developer with devtools open sees it in context.
    console.error('SHAWZIFY interface error', error, info.componentStack);
  }

  render(): ReactNode {
    const { error, stack } = this.state;
    if (!error) return this.props.children;

    return (
      <div className="h-full flex items-center justify-center p-8 bg-ink-900">
        <div className="max-w-2xl w-full">
          <h1 className="text-lg font-medium text-paper">The SHAWZIFY interface hit an error.</h1>
          <p className="mt-2 text-sm text-paper-dim">
            The engine is unaffected — the command line still works, and reloading usually
            clears this.
          </p>
          <div className="mt-4 surface p-3">
            <div className="text-sm text-red-300 font-mono break-words">{error.message}</div>
            {(error.stack || stack) && (
              <details className="mt-2">
                <summary className="text-2xs text-paper-faint cursor-pointer hover:text-paper-dim">
                  Technical details
                </summary>
                <pre className="mt-2 text-[10px] leading-tight text-paper-faint whitespace-pre-wrap max-h-72 overflow-y-auto select-text">
                  {error.stack}
                  {stack}
                </pre>
              </details>
            )}
          </div>
          <div className="mt-4 flex gap-2">
            <button
              type="button"
              className="btn-primary"
              onClick={() => window.location.reload()}
            >
              Reload
            </button>
            <button
              type="button"
              className="btn-ghost"
              onClick={() => this.setState({ error: null, stack: null })}
            >
              Try to continue
            </button>
          </div>
        </div>
      </div>
    );
  }
}
