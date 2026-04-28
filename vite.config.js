import { defineConfig } from 'vite';
import dts from 'vite-plugin-dts';
import { fileURLToPath } from 'url';
import { dirname, resolve } from 'path';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

/**
 * Build da biblioteca SDK. Entry unico em `src/index.ts`.
 * Saida em `dist/` com ESM + CJS + declaracoes `.d.ts`.
 *
 * Externals: `react`, `react-dom`, `socket.io-client`, `uuid`, `web-vitals` —
 * nao sao empacotados; o consumidor resolve no proprio bundler.
 *
 * Tests rodam via `npm run test` (vitest com jsdom + setupTests.js).
 */
export default defineConfig({
  plugins: [
    dts({
      outDir: 'dist',
      insertTypesEntry: true,
      tsconfigPath: resolve(__dirname, 'tsconfig.json'),
      include: ['src/**/*'],
      exclude: ['tests/**/*', 'examples/**/*'],
    }),
  ],
  build: {
    outDir: resolve(__dirname, 'dist'),
    emptyOutDir: true,
    minify: 'esbuild',
    sourcemap: true,
    lib: {
      entry: resolve(__dirname, 'src/index.ts'),
      name: 'AnalyticsSDK',
      formats: ['es', 'cjs'],
      fileName: (format) => `index.${format === 'es' ? 'js' : 'cjs'}`,
    },
    rollupOptions: {
      external: ['react', 'react-dom', 'socket.io-client', 'uuid', 'web-vitals'],
      output: {
        globals: {
          react: 'React',
          'react-dom': 'ReactDOM',
          'socket.io-client': 'socketio',
          uuid: 'uuid',
          'web-vitals': 'webVitals',
        },
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./tests/setupTests.js'],
    include: ['tests/**/*.test.ts'],
  },
});
