import type { EventoNormalizado, ContextoNormalizacao } from '../tipos.ts';

export interface EntradaCustom {
  nome: string;
  propriedades?: Record<string, unknown>;
}

const LIMITE_NOME = 64;
const LIMITE_PROPRIEDADES = 32;
const LIMITE_STRING = 512;

/**
 * Aceita primitivos (string/number/boolean/null). Descarta objetos, arrays,
 * functions e undefined — evita serializar acidentalmente dados sensiveis ou
 * estruturas que nao sao apropriadas para um envio de analytics.
 */
function sanitizarValor(valor: unknown): unknown {
  if (valor === null) return null;
  if (typeof valor === 'boolean') return valor;
  if (typeof valor === 'number') return Number.isFinite(valor) ? valor : undefined;
  if (typeof valor === 'string') return valor.slice(0, LIMITE_STRING);
  return undefined;
}

export function normalizarCustom(
  entrada: EntradaCustom,
  contexto: ContextoNormalizacao = {},
): EventoNormalizado | null {
  if (!entrada.nome || typeof entrada.nome !== 'string') return null;
  const nome = entrada.nome.slice(0, LIMITE_NOME);

  const propriedades: Record<string, unknown> = {};
  if (entrada.propriedades && typeof entrada.propriedades === 'object' && !Array.isArray(entrada.propriedades)) {
    let count = 0;
    for (const [chave, valor] of Object.entries(entrada.propriedades)) {
      if (count >= LIMITE_PROPRIEDADES) break;
      const sanitizado = sanitizarValor(valor);
      if (sanitizado !== undefined) {
        propriedades[chave] = sanitizado;
        count += 1;
      }
    }
  }

  const now = contexto.now ?? Date.now;
  return {
    tipo: 'custom',
    timestamp: now(),
    dados: { nome, propriedades },
  };
}
