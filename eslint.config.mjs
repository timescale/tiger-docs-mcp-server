// @ts-check

import boilerplatePlugin from '@tigerdata/mcp-boilerplate/eslintPlugin';
import eslint from '@eslint/js';
import { defineConfig } from 'eslint/config';
import { dirname } from 'path';
import tseslint from 'typescript-eslint';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));

export default defineConfig(
  eslint.configs.recommended,
  tseslint.configs.recommended,
  {
    files: ['src/**/*.ts'],
    plugins: {
      'mcp-boilerplate': boilerplatePlugin,
    },
    languageOptions: {
      parserOptions: {
        project: './tsconfig.json',
        tsconfigRootDir: __dirname,
      },
    },
    rules: {
      // Disable base rule for unused vars and use TypeScript-specific one
      'no-unused-vars': 'off',
      '@typescript-eslint/no-unused-vars': [
        'error',
        { argsIgnorePattern: '^_' },
      ],
      '@typescript-eslint/explicit-function-return-type': 'warn',
      '@typescript-eslint/no-inferrable-types': 'warn',
      'prefer-const': 'error',
      // Custom rule to prevent .optional() in inputSchema
      'mcp-boilerplate/no-optional-input-schema': 'error',
    },
  },
  {
    ignores: ['dist/', 'node_modules/', 'migrations/', 'skills/'],
  },
);
