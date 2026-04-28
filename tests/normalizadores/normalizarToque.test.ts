import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { normalizarToque } from '../../src/normalizadores/normalizarToque.ts';

describe('normalizarToque', () => {
  const originalElementFromPoint = (document as any).elementFromPoint;

  beforeEach(() => {
    (document as any).elementFromPoint = vi.fn(() => null);
  });

  afterEach(() => {
    (document as any).elementFromPoint = originalElementFromPoint;
    vi.restoreAllMocks();
  });

  it('produz evento touch canonico usando elementFromPoint', () => {
    const alvo = document.createElement('a');
    alvo.setAttribute('data-analytics-id', 'link-card');
    (document as any).elementFromPoint = vi.fn(() => alvo);

    const touch = {
      clientX: 10,
      clientY: 20,
      pageX: 30,
      pageY: 40,
    } as Touch;

    const evento = { touches: [touch] } as unknown as TouchEvent;
    const normalizado = normalizarToque(evento, { now: () => 500 });

    expect(normalizado).toEqual({
      tipo: 'touch',
      timestamp: 500,
      dados: {
        x: 30,
        y: 40,
        elemento_id: 'link-card',
        elemento_tipo: 'a',
      },
    });
  });

  it('retorna null quando nao ha toque', () => {
    const evento = { touches: [] } as unknown as TouchEvent;
    expect(normalizarToque(evento)).toBeNull();
  });

  it('marca elemento_id como desconhecido quando elementFromPoint retorna null', () => {
    (document as any).elementFromPoint = vi.fn(() => null);
    const evento = {
      touches: [{ clientX: 0, clientY: 0, pageX: 0, pageY: 0 } as Touch],
    } as unknown as TouchEvent;
    const normalizado = normalizarToque(evento);
    expect(normalizado?.dados.elemento_id).toBe('desconhecido');
  });
});
