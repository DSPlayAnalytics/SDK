/**
 * Tracking de CTAs do landing.
 *
 * Padrao: anote botoes/links com `data-cta="<nome>"` no HTML. O Layout chama
 * `attachCtaTracking(document, sdk.enviarEvento)` apos o SDK carregar e cada
 * click bubbles ate aqui — emite `cta_clicado` com `{ cta, path }`.
 *
 * Mantem-se separado do SDK pra ser unit-testavel sem mockar o pacote.
 */

export type EventEmitter = (
  name: string,
  payload: Record<string, unknown>,
) => void;

export function ctaFromTarget(target: EventTarget | null): string | null {
  if (!(target instanceof Element)) return null;
  const el = target.closest('[data-cta]');
  return el?.getAttribute('data-cta') ?? null;
}

export function attachCtaTracking(
  root: Document | Element,
  emit: EventEmitter,
): () => void {
  const listener = (e: Event) => {
    const cta = ctaFromTarget(e.target);
    if (!cta) return;
    emit('cta_clicado', {
      cta,
      path: typeof location !== 'undefined' ? location.pathname : '',
    });
  };
  root.addEventListener('click', listener, true);
  return () => root.removeEventListener('click', listener, true);
}
