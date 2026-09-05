import '@testing-library/jest-dom/vitest';

// jsdom has no canvas or ResizeObserver; the visual components only need these
// to not throw, since the tests assert on behaviour rather than on pixels.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver = ResizeObserverStub as unknown as typeof ResizeObserver;

HTMLCanvasElement.prototype.getContext = (() => ({
  setTransform: () => {},
  clearRect: () => {},
  fillRect: () => {},
  strokeRect: () => {},
  beginPath: () => {},
  moveTo: () => {},
  lineTo: () => {},
  stroke: () => {},
  fill: () => {},
  setLineDash: () => {},
  measureText: () => ({ width: 0 }),
  fillText: () => {},
})) as unknown as typeof HTMLCanvasElement.prototype.getContext;

// framer-motion measures keyframes via window.scrollTo, which jsdom does not
// implement. Stubbing it keeps the animation code under test without noise.
if (!window.scrollTo) {
  window.scrollTo = (() => {}) as unknown as typeof window.scrollTo;
}

if (!window.matchMedia) {
  window.matchMedia = ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
}
