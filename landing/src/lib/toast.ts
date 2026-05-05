/**
 * toast.ts — helper imperativo pra notificacoes flutuantes.
 *
 * Uso:
 *   import { showToast } from '~/lib/toast';
 *   showToast('Key copiada', { variant: 'success' });
 *
 * Requer <ToastContainer /> renderizado uma vez na arvore (Base.astro).
 * Se region/template nao existirem (ex: pagina que nao herda Base),
 * a chamada e' no-op silencioso — nao queremos quebrar o fluxo do user
 * por falta de UI auxiliar.
 *
 * `durationMs: 0` desabilita auto-dismiss (toasts persistentes pra erros
 * que precisam de acao). Default 4s — tempo curto suficiente pra ler
 * uma frase, longo suficiente pra perceber.
 */
export type ToastVariant = 'success' | 'error' | 'info' | 'warning';

export interface ShowToastOptions {
  variant?: ToastVariant;
  durationMs?: number;
}

interface VariantStyles {
  box: string[];
  dot: string[];
}

const VARIANT_STYLES: Record<ToastVariant, VariantStyles> = {
  success: {
    box: ['border-success-500/40', 'bg-success-500/10'],
    dot: ['bg-success-400'],
  },
  error: {
    box: ['border-danger-500/40', 'bg-danger-500/10'],
    dot: ['bg-danger-400'],
  },
  info: {
    box: ['border-info-500/40', 'bg-info-500/10'],
    dot: ['bg-info-400'],
  },
  warning: {
    box: ['border-warning-500/40', 'bg-warning-500/10'],
    dot: ['bg-warning-400'],
  },
};

const REGION_ID = 'ds-toast-region';
const TEMPLATE_ID = 'ds-toast-tpl';
const DEFAULT_DURATION_MS = 4000;
const FADE_OUT_MS = 200;

export function showToast(message: string, options: ShowToastOptions = {}): HTMLElement | null {
  const { variant = 'info', durationMs = DEFAULT_DURATION_MS } = options;

  const region = document.getElementById(REGION_ID);
  const tpl = document.getElementById(TEMPLATE_ID) as HTMLTemplateElement | null;
  if (!region || !tpl) return null;

  const node = tpl.content.firstElementChild?.cloneNode(true) as HTMLElement | undefined;
  if (!node) return null;

  const styles = VARIANT_STYLES[variant];
  node.classList.add(...styles.box);

  const icon = node.querySelector<HTMLElement>('[data-slot="icon"]');
  if (icon) icon.classList.add(...styles.dot);

  const messageEl = node.querySelector<HTMLElement>('[data-slot="message"]');
  if (messageEl) messageEl.textContent = message;

  let dismissed = false;
  const close = () => {
    if (dismissed) return;
    dismissed = true;
    node.classList.add('opacity-0');
    setTimeout(() => node.remove(), FADE_OUT_MS);
  };

  const closeBtn = node.querySelector<HTMLButtonElement>('[data-slot="close"]');
  closeBtn?.addEventListener('click', close);

  region.appendChild(node);

  if (durationMs > 0) {
    setTimeout(close, durationMs);
  }

  return node;
}
