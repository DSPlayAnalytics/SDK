import type { EventoNormalizado, ContextoNormalizacao, MarcoScroll } from '../tipos.ts';

export interface EntradaScroll {
  marco: MarcoScroll;
  maxPercent: number;
}

const MARCOS_VALIDOS: ReadonlyArray<MarcoScroll> = [25, 50, 75, 100];

export function normalizarScroll(
  entrada: EntradaScroll,
  contexto: ContextoNormalizacao = {},
): EventoNormalizado | null {
  if (!MARCOS_VALIDOS.includes(entrada.marco)) return null;
  if (!Number.isFinite(entrada.maxPercent)) return null;

  const now = contexto.now ?? Date.now;
  return {
    tipo: 'scroll_depth',
    timestamp: now(),
    dados: {
      marco: entrada.marco,
      max_percent: Math.max(0, Math.min(100, Math.round(entrada.maxPercent))),
    },
  };
}
