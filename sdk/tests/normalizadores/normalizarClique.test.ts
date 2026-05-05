import { describe, expect, it } from 'vitest';

import { normalizarClique } from '../../src/normalizadores/normalizarClique.ts';

describe('normalizarClique', () => {
  it('produz evento click canonico com x/y/elemento_id/elemento_tipo', () => {
    const botao = document.createElement('button');
    botao.setAttribute('data-analytics-id', 'cta-comprar');

    const evento = new MouseEvent('click', { bubbles: true });
    Object.defineProperty(evento, 'target', { value: botao });
    Object.defineProperty(evento, 'pageX', { value: 42 });
    Object.defineProperty(evento, 'pageY', { value: 99 });

    const normalizado = normalizarClique(evento, { now: () => 1000 });
    expect(normalizado).toEqual({
      tipo: 'click',
      timestamp: 1000,
      dados: {
        x: 42,
        y: 99,
        elemento_id: 'cta-comprar',
        elemento_tipo: 'button',
      },
    });
  });

  it('retorna null quando target e nulo', () => {
    const evento = new MouseEvent('click');
    Object.defineProperty(evento, 'target', { value: null });
    expect(normalizarClique(evento)).toBeNull();
  });

  it('nao envia innerText do elemento (campo sensivel)', () => {
    const botao = document.createElement('button');
    botao.id = 'btn';
    botao.textContent = 'Senha: abc123';

    const evento = new MouseEvent('click');
    Object.defineProperty(evento, 'target', { value: botao });

    const normalizado = normalizarClique(evento);
    const dadosComoString = JSON.stringify(normalizado?.dados ?? {});
    expect(dadosComoString).not.toContain('abc123');
    expect(dadosComoString).not.toContain('Senha');
  });
});
