// SPDX-License-Identifier: AGPL-3.0-or-later
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

// Keep the browser's Host header: the API's CSRF check compares it with Origin.
// (Vite's string shorthand would set changeOrigin and rewrite it.)
const apiProxy = {
  '/api': { target: process.env.OPENCHART_API_URL ?? 'http://127.0.0.1:8000', changeOrigin: false },
};

export default defineConfig({
  plugins: [react()],
  server: { proxy: apiProxy },
  preview: { proxy: apiProxy },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test-setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
  },
});
