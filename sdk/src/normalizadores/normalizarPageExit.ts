import type { EventoNormalizado, ContextoNormalizacao, MotivoSaida } from '../tipos.ts';

export interface EntradaPageExit {
  pageId: string;
  duracao_ms: number;
  motivo: MotivoSaida;
}

const MOTIVOS_VALIDOS: ReadonlyArray<MotivoSaida> = ['navegacao', 'unmount', 'aba_fechada'];

export function normalizarPageExit(
  entrada: EntradaPageExit,
  contexto: ContextoNormalizacao = {},
): EventoNormalizado | null {
  if (!entrada.pageId) return null;
  if (!MOTIVOS_VALIDOS.includes(entrada.motivo)) return null;
  if (!Number.isFinite(entrada.duracao_ms) || entrada.duracao_ms < 0) return null;

  const now = contexto.now ?? Date.now;
  return {
    tipo: 'page_exit',
    timestamp: now(),
    dados: {
      page_id: entrada.pageId,
      duracao_ms: Math.round(entrada.duracao_ms),
      motivo: entrada.motivo,
    },
  };
}
