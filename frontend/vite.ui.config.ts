import path from 'node:path';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';
import { viteSingleFile } from 'vite-plugin-singlefile';

// UI Mode frontend, built like the report: ONE self-contained ui.html
// (all JS/CSS inlined) that render_ui_html() serves after replacing the
// session-token placeholder.
//
// Dev flow: start `python -m pyrunner ui <root>` (note its port), then
// `PYRUNNER_UI_PORT=<port> npm run dev:ui` and open the printed Vite URL
// with `?token=<token>` (the server prints its URL; the token is only
// embedded in the served page, so for HMR development pass it manually).
export default defineConfig({
  base: '',
  plugins: [react(), viteSingleFile()],
  build: {
    outDir: path.resolve(__dirname, '../pyrunner/ui/_static/ui'),
    emptyOutDir: true,
    chunkSizeWarningLimit: 10000,
    rollupOptions: {
      input: path.resolve(__dirname, 'ui.html'),
    },
  },
  server: {
    proxy: {
      '/api': `http://127.0.0.1:${process.env.PYRUNNER_UI_PORT || 8123}`,
      '/pyrunner-artifacts': `http://127.0.0.1:${process.env.PYRUNNER_UI_PORT || 8123}`,
    },
  },
});
