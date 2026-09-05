import React from 'react';
import ReactDOM from 'react-dom/client';

import App from './App';
import { ErrorBoundary } from './components/ErrorBoundary';
import './styles/index.css';

// A module-level throw would otherwise leave an empty page with no explanation.
window.addEventListener('error', (event) => {
  const root = document.getElementById('root');
  if (root && root.childElementCount === 0) {
    root.textContent = 'SHAWZIFY could not start: ' + String(event.message);
    root.setAttribute('style', 'padding:2rem;color:#EDEBE6;font:14px system-ui');
  }
});

ReactDOM.createRoot(document.getElementById('root') as HTMLElement).render(
  <React.StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </React.StrictMode>,
);
