import type { EventoNormalizado, ContextoNormalizacao, NomeWebVital, RatingWebVital } from '../tipos.ts';

export interface EntradaWebVital {
  nome: NomeWebVital;
  valor: number;
  rating?: RatingWebVital;
  id?: string;
}

const NOMES_VALIDOS: ReadonlyArray<NomeWebVital> = ['LCP', 'CLS', 'INP'];
const RATINGS_VALIDOS: ReadonlyArray<RatingWebVital> = ['good', 'needs-improvement', 'poor'];

export function normalizarWebVital(
  entrada: EntradaWebVital,
  contexto: ContextoNormalizacao = {},
): EventoNormalizado | null {
  if (!NOMES_VALIDOS.includes(entrada.nome)) return null;
  if (!Number.isFinite(entrada.valor) || entrada.valor < 0) return null;

  const now = contexto.now ?? Date.now;
  const dados: Record<string, unknown> = {
    nome: entrada.nome,
    valor: entrada.valor,
  };
  if (entrada.rating && RATINGS_VALIDOS.includes(entrada.rating)) {
    dados.rating = entrada.rating;
  }
  if (entrada.id) dados.id = entrada.id;

  return {
    tipo: 'web_vital',
    timestamp: now(),
    dados,
  };
}
