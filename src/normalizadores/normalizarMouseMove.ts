import type { EventoNormalizado, ContextoNormalizacao } from '../tipos.ts';

export interface ContextoMouseMove extends ContextoNormalizacao {
  ultimoTimestamp: number | null;
  taxaPorSegundo: number;
}

export function normalizarMouseMove(
  evento: MouseEvent,
  contexto: ContextoMouseMove,
): EventoNormalizado | null {
  const now = contexto.now ?? Date.now;
  const agora = now();
  const taxa = Math.max(1, contexto.taxaPorSegundo);
  const intervaloMinimo = Math.max(1, Math.floor(1000 / taxa));

  if (contexto.ultimoTimestamp != null && agora - contexto.ultimoTimestamp < intervaloMinimo) {
    return null;
  }

  return {
    tipo: 'mouse_move',
    timestamp: agora,
    dados: { x: evento.pageX, y: evento.pageY },
  };
}
