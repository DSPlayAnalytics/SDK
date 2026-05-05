import { onCLS, onINP, onLCP } from 'web-vitals';
import type { Metric } from 'web-vitals';

import { HeatmapUtils } from './HeatmapUtils.tsx';
import { normalizarWebVital } from './normalizadores/normalizarWebVital.ts';
import type { NomeWebVital } from './tipos.ts';

let registrado = false;

function encaminhar(metric: Metric) {
  const nome = metric.name as NomeWebVital;
  const evento = normalizarWebVital({
    nome,
    valor: metric.value,
    rating: metric.rating,
    id: metric.id,
  });
  if (evento) {
    HeatmapUtils.empilharEventoNoAtivo(evento);
  }
}

/**
 * Registra os callbacks do web-vitals. Idempotente — chamar varias vezes nao adiciona listeners extras.
 *
 * Por padrao, web-vitals v3+ so emite LCP/CLS/INP quando a pagina fica oculta
 * (`pagehide`/visibility change), pra garantir valores finais estaveis. Isso
 * funciona bem em prod onde o usuario eventualmente sai/troca aba, mas em dev
 * deixa o dashboard zerado por longos periodos.
 *
 * `reportAllChanges: true` faz a lib emitir tambem updates intermediarios
 * (cada novo LCP candidate, cada layout shift, cada interacao). Em prod isso
 * gera 3-5x mais eventos por sessao — aceito como tradeoff por feedback
 * em real-time. Pra contas de alto volume, desligar via env futuro.
 */
export function iniciarWebVitals(): void {
  if (registrado) return;
  registrado = true;
  const opts = { reportAllChanges: true };
  onLCP(encaminhar, opts);
  onCLS(encaminhar, opts);
  onINP(encaminhar, opts);
}

/**
 * Reseta o estado de registro. Uso previsto: apenas em testes.
 */
export function resetarWebVitalsParaTeste(): void {
  registrado = false;
}
