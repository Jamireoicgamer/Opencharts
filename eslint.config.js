// SPDX-License-Identifier: AGPL-3.0-or-later
import js from '@eslint/js';
import { defineConfig, globalIgnores } from 'eslint/config';
import reactHooks from 'eslint-plugin-react-hooks';
import globals from 'globals';
import tseslint from 'typescript-eslint';

export default defineConfig(
  globalIgnores(['legacy/', '**/dist/', '**/playwright-report/', '**/test-results/', '.venv/']),
  js.configs.recommended,
  tseslint.configs.strict,
  {
    files: ['**/*.{ts,tsx}'],
    extends: [reactHooks.configs.flat.recommended],
    languageOptions: { globals: globals.browser },
  },
  {
    files: ['*.js', '**/*.config.{js,ts}', '**/scripts/*.mjs'],
    languageOptions: { globals: globals.node },
  },
  {
    files: ['**/public/sw.js'],
    languageOptions: { globals: globals.serviceworker },
  },
);
