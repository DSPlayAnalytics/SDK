import { describe, expect, it } from 'vitest';

import { normalizarWebVital } from '../../src/normalizadores/normalizarWebVital.ts';

describe('normalizarWebVital', () => {
  it('gera evento web_vital com nome, valor, rating e id', () => {
    const normalizado = normalizarWebVital(
      { nome: 'LCP', valor: 2340.5, rating: 'good', id: 'v1' },
      { now: () => 5 },
    );
    expect(normalizado).toEqual({
      tipo: 'web_vital',
      timestamp: 5,
      dados: { nome: 'LCP', valor: 2340.5, rating: 'good', id: 'v1' },
    });
  });

  it('descarta nome fora do conjunto permitido', () => {
    expect(normalizarWebVital({ nome: 'FID' as any, valor: 100 })).toBeNull();
  });

  it('descarta rating invalido e ainda retorna o evento sem rating', () => {
    const normalizado = normalizarWebVital({ nome: 'CLS', valor: 0.12, rating: 'otimo' as any });
    expect(normalizado?.dados.rating).toBeUndefined();
    expect(normalizado?.dados.valor).toBe(0.12);
  });

  it('descarta valor negativo ou NaN', () => {
    expect(normalizarWebVital({ nome: 'INP', valor: -1 })).toBeNull();
    expect(normalizarWebVital({ nome: 'INP', valor: NaN })).toBeNull();
  });
});
