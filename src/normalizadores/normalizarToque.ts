import type { EventoNormalizado, ContextoNormalizacao } from '../tipos.ts';
import { obterElementoId, obterElementoTipo } from '../util/obterElementoId.ts';

export function normalizarToque(
  evento: TouchEvent,
  contexto: ContextoNormalizacao = {},
): EventoNormalizado | null {
  const toque = evento.touches?.[0];
  if (!toque) return null;

  const alvo = (typeof document !== 'undefined' && typeof document.elementFromPoint === 'function'
    ? (document.elementFromPoint(toque.clientX, toque.clientY) as HTMLElement | null)
    : null);

  const now = contexto.now ?? Date.now;
  return {
    tipo: 'touch',
    timestamp: now(),
    dados: {
      x: toque.pageX,
      y: toque.pageY,
      elemento_id: obterElementoId(alvo),
      elemento_tipo: obterElementoTipo(alvo),
    },
  };
}
