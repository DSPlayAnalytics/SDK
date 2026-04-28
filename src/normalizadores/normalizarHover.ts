import type { EventoNormalizado, ContextoNormalizacao } from '../tipos.ts';

export interface EntradaHover {
  elementoId: string;
  duracao_ms: number;
  elemento_tipo?: string;
}

export function normalizarHover(
  entrada: EntradaHover,
  contexto: ContextoNormalizacao = {},
): EventoNormalizado | null {
  if (!entrada.elementoId) return null;
  if (!Number.isFinite(entrada.duracao_ms) || entrada.duracao_ms <= 0) return null;

  const now = contexto.now ?? Date.now;
  return {
    tipo: 'hover',
    timestamp: now(),
    dados: {
      elemento_id: entrada.elementoId,
      elemento_tipo: entrada.elemento_tipo ?? 'desconhecido',
      duracao_ms: Math.round(entrada.duracao_ms),
    },
  };
}
