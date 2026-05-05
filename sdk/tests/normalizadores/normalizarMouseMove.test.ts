import { describe, expect, it } from 'vitest';

import { normalizarMouseMove } from '../../src/normalizadores/normalizarMouseMove.ts';

const criarEvento = (pageX: number, pageY: number): MouseEvent => {
  const evento = new MouseEvent('mousemove');
  Object.defineProperty(evento, 'pageX', { value: pageX });
  Object.defineProperty(evento, 'pageY', { value: pageY });
  return evento;
};

describe('normalizarMouseMove', () => {
  it('emite evento quando nao ha ultimoTimestamp', () => {
    const normalizado = normalizarMouseMove(criarEvento(10, 20), {
      ultimoTimestamp: null,
      taxaPorSegundo: 5,
      now: () => 1000,
    });
    expect(normalizado).toEqual({
      tipo: 'mouse_move',
      timestamp: 1000,
      dados: { x: 10, y: 20 },
    });
  });

  it('descarta quando dentro da janela de amostragem (taxa=5 -> intervalo minimo 200ms)', () => {
    const normalizado = normalizarMouseMove(criarEvento(1, 1), {
      ultimoTimestamp: 900,
      taxaPorSegundo: 5,
      now: () => 1050,
    });
    expect(normalizado).toBeNull();
  });

  it('aceita apos o intervalo minimo', () => {
    const normalizado = normalizarMouseMove(criarEvento(2, 3), {
      ultimoTimestamp: 900,
      taxaPorSegundo: 5,
      now: () => 1101,
    });
    expect(normalizado).not.toBeNull();
    expect(normalizado?.timestamp).toBe(1101);
  });

  it('taxa zero e tratada como 1', () => {
    const normalizado = normalizarMouseMove(criarEvento(0, 0), {
      ultimoTimestamp: 0,
      taxaPorSegundo: 0,
      now: () => 999,
    });
    expect(normalizado).toBeNull();
  });
});
