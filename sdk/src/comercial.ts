import { HeatmapUtils } from './HeatmapUtils.tsx';
import type { EventoNormalizado } from './tipos.ts';

function emitirEventoComercial(nome: string, propriedades: Record<string, unknown>): void {
  const evento: EventoNormalizado = {
    tipo: 'custom',
    timestamp: Date.now(),
    dados: { nome, propriedades },
  };
  HeatmapUtils.empilharEventoNoAtivo(evento);
}

function sanitizarMetadata(meta: Record<string, unknown> | undefined): Record<string, unknown> {
  if (!meta || typeof meta !== 'object' || Array.isArray(meta)) return {};
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(meta)) {
    if (v === null || typeof v === 'boolean' || typeof v === 'string') {
      out[k] = v;
    } else if (typeof v === 'number' && Number.isFinite(v)) {
      out[k] = v;
    }
  }
  return out;
}

/**
 * Registra uma compra/transação monetária.
 * Emite evento interno `__purchase` com `value` (>= 0) e `currency` (ex.: "BRL").
 */
export function trackPurchase(
  value: number,
  currency: string,
  metadata?: Record<string, unknown>,
): boolean {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < 0) return false;
  if (typeof currency !== 'string' || !currency.trim()) return false;
  emitirEventoComercial('__purchase', {
    value,
    currency: currency.trim().toUpperCase(),
    ...sanitizarMetadata(metadata),
  });
  return true;
}

/**
 * Registra o cadastro de um novo usuário.
 * Emite evento interno `__signup` com o `plan` escolhido.
 */
export function trackSignup(plan: string, metadata?: Record<string, unknown>): boolean {
  if (typeof plan !== 'string' || !plan.trim()) return false;
  emitirEventoComercial('__signup', {
    plan: plan.trim(),
    ...sanitizarMetadata(metadata),
  });
  return true;
}

/**
 * Registra uma conversão genérica. `type` identifica o evento (ex.: "trial_start",
 * "upgrade"). `value` é opcional; quando fornecido deve ser um número finito >= 0.
 */
export function trackConversion(
  type: string,
  value?: number,
  metadata?: Record<string, unknown>,
): boolean {
  if (typeof type !== 'string' || !type.trim()) return false;
  if (value !== undefined) {
    if (typeof value !== 'number' || !Number.isFinite(value)) return false;
  }
  const props: Record<string, unknown> = {
    type: type.trim(),
    ...sanitizarMetadata(metadata),
  };
  if (value !== undefined) props.value = value;
  emitirEventoComercial('__conversion', props);
  return true;
}
