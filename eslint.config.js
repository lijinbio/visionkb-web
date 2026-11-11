import js from '@eslint/js';
import globals from 'globals';

export default [
  { ignores: ['**/static/js/vendor/**', 'node_modules/**', '.venv/**', 'build/**', 'dist/**'] },
  js.configs.recommended,
  {
    files: ['src/visionkb_web/static/js/**/*.js'],
    languageOptions: { ecmaVersion: 2023, sourceType: 'module', globals: { ...globals.browser } },
    rules: {
      'no-unused-vars': ['error', { argsIgnorePattern: '^_' }],
      'no-restricted-properties': ['error',
        { object: 'window', property: 'localStorage', message: 'The Claude key and chat stay in sessionStorage.' },
        { object: 'document', property: 'write' }],
      'no-restricted-globals': ['error', { name: 'localStorage', message: 'Use sessionStorage (design §4).' }, 'eval'],
      'no-implied-eval': 'error',
      'no-new-func': 'error',
      eqeqeq: ['error', 'always'],
    },
  },
  {
    // layout.js alone may use localStorage, for UI preferences ({width, mode}); never the Claude key or the chat.
    files: ['src/visionkb_web/static/js/layout.js'],
    rules: {
      'no-restricted-properties': ['error', { object: 'document', property: 'write' }],
      'no-restricted-globals': ['error', 'eval'],
    },
  },
  {
    files: ['tests/js/**/*.mjs', 'scripts/**/*.mjs', 'eslint.config.js'],
    languageOptions: { ecmaVersion: 2023, sourceType: 'module', globals: { ...globals.node } },
  },
];
