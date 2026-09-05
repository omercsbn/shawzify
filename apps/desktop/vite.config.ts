import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'node:path';

// Tauri serves the frontend from a fixed port in dev and from ../dist in release.
export default defineConfig({
  plugins: [react()],
  clearScreen: false,
  server: {
    port: 5173,
    strictPort: true,
    host: '127.0.0.1', // never expose the dev server beyond this machine
    watch: { ignored: ['**/src-tauri/**', '**/engine/**'] },
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'src'),
      '@shawzify/shared-types': path.resolve(__dirname, '../../packages/shared-types/index.ts'),
    },
  },
  build: {
    target: 'chrome110',
    outDir: 'dist',
    sourcemap: false,
    chunkSizeWarningLimit: 900,
  },
});
