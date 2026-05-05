import { defineConfig } from 'vite';
import { fileURLToPath } from 'url';
import { dirname, resolve } from 'path';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

/**
 * Build standalone (IIFE) — bundle unico pronto para <script src="">.
 *
 * Diferente do build de biblioteca (vite.config.js), este formato:
 *   - inline todas as dependencias (socket.io-client, web-vitals, uuid)
 *   - exporta o namespace global `window.AnalyticsSDK`
 *   - alvo: sites HTML estaticos sem build pipeline (Webflow, Wix-like,
 *     blogs, paginas de marketing, etc.)
 *
 * Tamanho esperado: ~80-120 KB minificado, ~25-35 KB gzip.
 *
 * Uso:
 *   <script src="https://.../sdk.umd.js" defer></script>
 *   <script>
 *     window.addEventListener('load', () => {
 *       AnalyticsSDK.iniciarAnalytics({ ... });
 *     });
 *   </script>
 */
export default defineConfig({
  build: {
    outDir: resolve(__dirname, 'dist'),
    emptyOutDir: false,
    minify: 'esbuild',
    sourcemap: true,
    target: 'es2020',
    lib: {
      entry: resolve(__dirname, 'src/index.ts'),
      name: 'AnalyticsSDK',
      formats: ['iife'],
      fileName: () => 'sdk.umd.js',
    },
    rollupOptions: {
      // Sem externals — IIFE precisa ser standalone.
      external: [],
    },
  },
});
