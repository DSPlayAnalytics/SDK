import { HeatmapUtils } from './HeatmapUtils.tsx';
import { normalizarCustom } from './normalizadores/normalizarCustom.ts';

/**
 * Empilha um evento customizado na pagina ativa. Valores aceitos sao primitivos
 * (string, number, boolean, null). Objetos/arrays/funcoes sao descartados — evita
 * enviar dados sensiveis acidentalmente.
 *
 * Retorna `true` se o evento foi empilhado, `false` se nao ha pagina ativa ou
 * se o nome/propriedades foram rejeitados pelo normalizador.
 */
export function enviarEvento(nome: string, propriedades?: Record<string, unknown>): boolean {
  const evento = normalizarCustom({ nome, propriedades });
  if (!evento) return false;
  return HeatmapUtils.empilharEventoNoAtivo(evento);
}
