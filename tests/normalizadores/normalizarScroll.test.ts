import { describe, expect, it } from 'vitest';

import { normalizarScroll } from '../../src/normalizadores/normalizarScroll.ts';

describe('normalizarScroll', () => {
  it('gera evento scroll_depth com marco e max_percent arredondado', () => {
    const normalizado = normalizarScroll({ marco: 50, maxPercent: 54.7 }, { now: () => 42 });
    expect(normalizado).toEqual({
      tipo: 'scroll_depth',
      timestamp: 42,
      dados: { marco: 50, max_percent: 55 },
    });
  });

  it('descarta marcos invalidos', () => {
    expect(normalizarScroll({ marco: 33 as 25, maxPercent: 40 })).toBeNull();
  });

  it('descarta percentagem invalida', () => {
    expect(normalizarScroll({ marco: 25, maxPercent: NaN })).toBeNull();
  });

  it('limita max_percent a [0,100]', () => {
    expect(normalizarScroll({ marco: 100, maxPercent: 250 })?.dados.max_percent).toBe(100);
    expect(normalizarScroll({ marco: 25, maxPercent: -10 })?.dados.max_percent).toBe(0);
  });
});
