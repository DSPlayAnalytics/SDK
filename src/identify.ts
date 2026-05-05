/**
 * Identidade no SDK (v0.4):
 *
 *   identify(userId, traits?) — associa eventos subsequentes a um user.
 *   group(orgId, traits?)     — agrupa user em uma organizacao (B2B).
 *   reset()                   — logout / "esquecer tudo" (LGPD).
 *
 * Cada chamada emite um evento custom reservado (`__identify`, `__group`,
 * `__reset`) — backend conhece o prefixo `__` e enriquece. Traits viajam
 * apenas no payload do evento, NAO persistem em storage local
 * (politica anti-PII em README).
 */
import { HeatmapUtils } from './HeatmapUtils.tsx';
import type { EventoNormalizado } from './tipos.ts';
import { userStore } from './identidade/userStore.ts';

/**
 * Sanitiza traits pra primitivos serializaveis. Mesma politica do
 * normalizarCustom (objetos/arrays/funcoes descartados — defesa contra
 * envio acidental de DOM nodes ou closures).
 */
function sanitizarTraits(traits: Record<string, unknown> | undefined): Record<string, unknown> {
  if (!traits || typeof traits !== 'object' || Array.isArray(traits)) return {};
  const out: Record<string, unknown> = {};
  for (const [chave, valor] of Object.entries(traits)) {
    if (valor === null) {
      out[`trait_${chave}`] = null;
    } else if (typeof valor === 'boolean' || typeof valor === 'string') {
      out[`trait_${chave}`] = valor;
    } else if (typeof valor === 'number' && Number.isFinite(valor)) {
      out[`trait_${chave}`] = valor;
    }
  }
  return out;
}

function emitirEventoSdk(nome: string, propriedades: Record<string, unknown>): void {
  const evento: EventoNormalizado = {
    tipo: 'custom',
    timestamp: Date.now(),
    dados: { nome, propriedades },
  };
  HeatmapUtils.empilharEventoNoAtivo(evento);
}

/**
 * Associa eventos subsequentes a um user. `traits` viajam no envelope mas
 * nao persistem (politica PII). Chamadas repetidas substituem o userId.
 *
 * @returns true se aceito; false se userId vazio/whitespace.
 */
export function identify(userId: string, traits?: Record<string, unknown>): boolean {
  if (typeof userId !== 'string' || !userId.trim()) return false;
  userStore.setUserId(userId);
  emitirEventoSdk('__identify', {
    user_id: userId.trim(),
    ...sanitizarTraits(traits),
  });
  return true;
}

/**
 * Associa user atual a uma organizacao (B2B SaaS). Persiste groupId pra
 * que envelopes seguintes carreguem o campo.
 */
export function group(groupId: string, traits?: Record<string, unknown>): boolean {
  if (typeof groupId !== 'string' || !groupId.trim()) return false;
  userStore.setGroupId(groupId);
  emitirEventoSdk('__group', {
    group_id: groupId.trim(),
    ...sanitizarTraits(traits),
  });
  return true;
}

/**
 * Logout / esquecimento. Apaga userId + groupId, regenera anonId. Eventos
 * pos-reset nao linkam com sessao anterior — atende LGPD direito ao
 * esquecimento sem precisar do servidor.
 */
export function reset(): void {
  userStore.reset();
  emitirEventoSdk('__reset', {});
}
