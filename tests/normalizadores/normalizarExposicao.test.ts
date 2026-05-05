import { describe, expect, it } from 'vitest';

import { normalizarExposicao } from '../../src/normalizadores/normalizarExposicao.ts';

describe('normalizarExposicao', () => {
  it('gera evento element_exposure com percent_visivel_max opcional', () => {
    const normalizado = normalizarExposicao(
      { elementoId: 'hero', duracao_ms: 4200, percent_visivel_max: 75.4 },
      { now: () => 1 },
    );
    expect(normalizado).toEqual({
      tipo: 'element_exposure',
      timestamp: 1,
      dados: {
        elemento_id: 'hero',
        duracao_ms: 4200,
        percent_visivel_max: 75,
      },
    });
  });

  it('omite percent_visivel_max quando nao fornecido', () => {
    const normalizado = normalizarExposicao({ elementoId: 'x', duracao_ms: 100 });
    expect(normalizado?.dados).toEqual({ elemento_id: 'x', duracao_ms: 100 });
  });

  it('descarta quando elementoId vazio', () => {
    expect(normalizarExposicao({ elementoId: '', duracao_ms: 100 })).toBeNull();
  });

  it('descarta quando duracao nao e positiva', () => {
    expect(normalizarExposicao({ elementoId: 'x', duracao_ms: 0 })).toBeNull();
  });
});
