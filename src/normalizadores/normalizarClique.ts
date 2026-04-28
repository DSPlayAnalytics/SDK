import type { EventoNormalizado, ContextoNormalizacao } from '../tipos.ts';
import { obterElementoId, obterElementoTipo } from '../util/obterElementoId.ts';

export function normalizarClique(
  evento: MouseEvent,
  contexto: ContextoNormalizacao = {},
): EventoNormalizado | null {
  const alvo = evento.target as HTMLElement | null;
  if (!alvo) return null;

  const now = contexto.now ?? Date.now;
  return {
    tipo: 'click',
    timestamp: now(),
    dados: {
      x: evento.pageX,
      y: evento.pageY,
      elemento_id: obterElementoId(alvo),
      elemento_tipo: obterElementoTipo(alvo),
    },
  };
}
