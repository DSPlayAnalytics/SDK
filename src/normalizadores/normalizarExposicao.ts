import type { EventoNormalizado, ContextoNormalizacao } from '../tipos.ts';

export interface EntradaExposicao {
  elementoId: string;
  duracao_ms: number;
  percent_visivel_max?: number;
}

export function normalizarExposicao(
  entrada: EntradaExposicao,
  contexto: ContextoNormalizacao = {},
): EventoNormalizado | null {
  if (!entrada.elementoId) return null;
  if (!Number.isFinite(entrada.duracao_ms) || entrada.duracao_ms <= 0) return null;

  const now = contexto.now ?? Date.now;
  const dados: Record<string, unknown> = {
    elemento_id: entrada.elementoId,
    duracao_ms: Math.round(entrada.duracao_ms),
  };

  if (Number.isFinite(entrada.percent_visivel_max as number)) {
    dados.percent_visivel_max = Math.max(0, Math.min(100, Math.round(entrada.percent_visivel_max as number)));
  }

  return {
    tipo: 'element_exposure',
    timestamp: now(),
    dados,
  };
}
