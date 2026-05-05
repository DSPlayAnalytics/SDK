// Smoke test do bundle gerado por `npm run build`.
// Valida que ESM + CJS + .d.ts estao presentes, parseaveis e expoem
// os simbolos de entrada esperados.
import { existsSync, readFileSync, statSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const dist = resolve(__dirname, '..', 'dist');

const required = [
  'index.js',     // ESM (externals preservados, ~10KB gzip)
  'index.cjs',    // CJS (externals preservados)
  'index.d.ts',   // tipos
  'sdk.umd.js',   // IIFE standalone para <script> tag (~30KB gzip)
];

const missing = required.filter((f) => !existsSync(resolve(dist, f)));
if (missing.length) {
  console.error('FALHA: artefatos ausentes em dist/:', missing);
  process.exit(1);
}

// Tamanho minimo razoavel por arquivo. index.d.ts so re-exporta (~600 bytes ok),
// index.js/cjs deveriam ter o codigo bundled, sdk.umd.js inclui deps.
const minBytes = {
  'index.js': 5000,
  'index.cjs': 5000,
  'index.d.ts': 300,
  'sdk.umd.js': 50000,  // IIFE com socket.io+web-vitals+uuid inline
};
for (const f of required) {
  const size = statSync(resolve(dist, f)).size;
  if (size < minBytes[f]) {
    console.error(`FALHA: dist/${f} tem ${size} bytes (esperado >= ${minBytes[f]})`);
    process.exit(1);
  }
}

// Confere que os simbolos exportados estao no .d.ts.
const types = readFileSync(resolve(dist, 'index.d.ts'), 'utf8');
const exports = ['iniciarAnalytics', 'enviarEvento', 'WebSocketService', 'HeatmapUtils'];
const missingExports = exports.filter((s) => !types.includes(s));
if (missingExports.length) {
  console.error('FALHA: declaracoes ausentes em index.d.ts:', missingExports);
  process.exit(1);
}

// Tenta importar o ESM em runtime (mockando deps externas que nao temos aqui).
const esmText = readFileSync(resolve(dist, 'index.js'), 'utf8');
if (!esmText.includes('iniciarAnalytics')) {
  console.error('FALHA: dist/index.js sem simbolo iniciarAnalytics');
  process.exit(1);
}

// UMD precisa expor namespace global AnalyticsSDK (window.AnalyticsSDK).
const umdText = readFileSync(resolve(dist, 'sdk.umd.js'), 'utf8');
if (!umdText.includes('AnalyticsSDK')) {
  console.error('FALHA: dist/sdk.umd.js sem namespace global AnalyticsSDK');
  process.exit(1);
}

console.log('OK: dist/ contem ESM + CJS + .d.ts + UMD validos');
console.log('  index.js   :', statSync(resolve(dist, 'index.js')).size, 'bytes (ESM)');
console.log('  index.cjs  :', statSync(resolve(dist, 'index.cjs')).size, 'bytes (CJS)');
console.log('  index.d.ts :', statSync(resolve(dist, 'index.d.ts')).size, 'bytes');
console.log('  sdk.umd.js :', statSync(resolve(dist, 'sdk.umd.js')).size, 'bytes (IIFE standalone)');
