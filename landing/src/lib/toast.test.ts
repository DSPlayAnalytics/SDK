// @vitest-environment happy-dom
/**
 * Testes do helper toast.ts. Precisa de DOM (vitest config padrao e' node)
 * — diretiva acima troca env so neste arquivo.
 *
 * Cobertura: contrato (variants aplicam classes corretas, mensagem renderiza,
 * dismiss manual remove o no), e o no-op silencioso quando o container nao
 * foi montado na pagina.
 */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';

import { showToast } from './toast';

function montarContainer(): void {
  document.body.innerHTML = `
    <div id="ds-toast-region" role="region" aria-live="polite"></div>
    <template id="ds-toast-tpl">
      <div role="status" class="border">
        <span data-slot="icon"></span>
        <p data-slot="message"></p>
        <button data-slot="close" type="button">x</button>
      </div>
    </template>
  `;
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  document.body.innerHTML = '';
});

describe('showToast', () => {
  test('anexa toast ao region com mensagem', () => {
    montarContainer();
    const node = showToast('Key copiada');
    expect(node).not.toBeNull();
    const region = document.getElementById('ds-toast-region')!;
    expect(region.children.length).toBe(1);
    expect(region.querySelector('[data-slot="message"]')!.textContent).toBe('Key copiada');
  });

  test('variant success aplica classes do token', () => {
    montarContainer();
    const node = showToast('OK', { variant: 'success' })!;
    expect(node.classList.contains('border-success-500/40')).toBe(true);
    expect(node.classList.contains('bg-success-500/10')).toBe(true);
    const dot = node.querySelector('[data-slot="icon"]')!;
    expect(dot.classList.contains('bg-success-400')).toBe(true);
  });

  test('variant error usa danger-*', () => {
    montarContainer();
    const node = showToast('Falhou', { variant: 'error' })!;
    expect(node.classList.contains('border-danger-500/40')).toBe(true);
    expect(node.querySelector('[data-slot="icon"]')!.classList.contains('bg-danger-400')).toBe(true);
  });

  test('auto-dismiss apos durationMs default (4000ms + fade 200ms)', () => {
    montarContainer();
    showToast('some');
    expect(document.querySelectorAll('[role="status"]').length).toBe(1);
    vi.advanceTimersByTime(4000);
    // entrou em fade — ainda no DOM, mas com opacity-0
    const node = document.querySelector('[role="status"]') as HTMLElement;
    expect(node.classList.contains('opacity-0')).toBe(true);
    vi.advanceTimersByTime(200);
    expect(document.querySelectorAll('[role="status"]').length).toBe(0);
  });

  test('durationMs=0 desabilita auto-dismiss', () => {
    montarContainer();
    showToast('persistente', { durationMs: 0 });
    vi.advanceTimersByTime(60_000);
    expect(document.querySelectorAll('[role="status"]').length).toBe(1);
  });

  test('clique no botao close dispara dismiss', () => {
    montarContainer();
    const node = showToast('clicavel', { durationMs: 0 })!;
    const btn = node.querySelector<HTMLButtonElement>('[data-slot="close"]')!;
    btn.click();
    expect(node.classList.contains('opacity-0')).toBe(true);
    vi.advanceTimersByTime(200);
    expect(document.querySelectorAll('[role="status"]').length).toBe(0);
  });

  test('multiplos dismiss sao idempotentes (auto-dismiss + clique nao removem 2x)', () => {
    montarContainer();
    const node = showToast('x')!;
    node.querySelector<HTMLButtonElement>('[data-slot="close"]')!.click();
    vi.advanceTimersByTime(4000); // dispara o setTimeout do auto-dismiss tardio
    vi.advanceTimersByTime(200);
    // Deve ter zero — nao explodir tentando remover de novo
    expect(document.querySelectorAll('[role="status"]').length).toBe(0);
  });

  test('no-op silencioso quando container nao esta montado', () => {
    // sem montarContainer — body vazio
    const node = showToast('orfao');
    expect(node).toBeNull();
  });
});
