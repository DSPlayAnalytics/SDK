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
 * As metricas sao entregues pela lib em momentos especificos (LCP apos 1st paint, CLS no page lifecycle, etc.).
 * Quando uma metrica chega, o evento `web_vital` e empilhado no HeatmapUtils ativo.
 */
export function iniciarWebVitals(): void {
  if (registrado) return;
  registrado = true;
  onLCP(encaminhar);
  onCLS(encaminhar);
  onINP(encaminhar);
}

/**
 * Reseta o estado de registro. Uso previsto: apenas em testes.
 */
export function resetarWebVitalsParaTeste(): void {
  registrado = false;
}
