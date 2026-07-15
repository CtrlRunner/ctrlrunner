import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { viteSingleFile } from 'vite-plugin-singlefile';
import path from 'path';

// Builds the static test report as ONE self-contained index.html
// (all JS/CSS inlined) so the Python side ships a single asset and
// render_html() only has to splice the report data into it.
export default defineConfig({
  base: '',
  plugins: [react(), viteSingleFile()],
  build: {
    outDir: path.resolve(__dirname, '../src/ctrlrunner/reporting/_static/report'),
    emptyOutDir: true,
    chunkSizeWarningLimit: 10000,
  },
});
