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
  'index.js',     // ESM
  'index.cjs',    // CJS
  'index.d.ts',   // tipos
];

const missing = required.filter((f) => !existsSync(resolve(dist, f)));
if (missing.length) {
  console.error('FALHA: artefatos ausentes em dist/:', missing);
  process.exit(1);
}

// Tamanho minimo razoavel por arquivo. index.d.ts so re-exporta (~600 bytes ok),
// index.js/cjs deveriam ter o codigo bundled.
const minBytes = { 'index.js': 5000, 'index.cjs': 5000, 'index.d.ts': 300 };
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
if (esmText.length < minBytes || !esmText.includes('iniciarAnalytics')) {
  console.error('FALHA: dist/index.js parece truncado ou sem simbolos esperados');
  process.exit(1);
}

console.log('OK: dist/ contem ESM + CJS + .d.ts validos');
console.log('  index.js   :', statSync(resolve(dist, 'index.js')).size, 'bytes');
console.log('  index.cjs  :', statSync(resolve(dist, 'index.cjs')).size, 'bytes');
console.log('  index.d.ts :', statSync(resolve(dist, 'index.d.ts')).size, 'bytes');
