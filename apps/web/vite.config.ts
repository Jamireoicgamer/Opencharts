// SPDX-License-Identifier: AGPL-3.0-or-later
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

// Keep the browser's Host header: the API's CSRF check compares it with Origin.
// (Vite's string shorthand would set changeOrigin and rewrite it.)
const apiProxy = {
  '/api': { target: process.env.OPENCHART_API_URL ?? 'http://127.0.0.1:8000', changeOrigin: false },
};

// The production Content-Security-Policy (deploy/nginx.conf), so browser
// tests against `vite preview` catch anything that breaks it.
const PRODUCTION_CSP =
  "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'";

export default defineConfig({
  plugins: [react()],
  server: { proxy: apiProxy },
  preview: { proxy: apiProxy, headers: { 'Content-Security-Policy': PRODUCTION_CSP } },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test-setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
  },
});
