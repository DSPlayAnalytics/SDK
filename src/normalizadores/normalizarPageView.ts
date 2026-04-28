import type { EventoNormalizado, ContextoNormalizacao } from '../tipos.ts';

export interface EntradaPageView {
  pageId: string;
  path: string;
  title?: string;
}

export function normalizarPageView(
  entrada: EntradaPageView,
  contexto: ContextoNormalizacao = {},
): EventoNormalizado | null {
  if (!entrada.pageId || !entrada.path) return null;

  const now = contexto.now ?? Date.now;
  const dados: Record<string, unknown> = {
    page_id: entrada.pageId,
    path: entrada.path,
  };
  if (entrada.title) dados.title = entrada.title;

  return {
    tipo: 'page_view',
    timestamp: now(),
    dados,
  };
}
