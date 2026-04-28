import { describe, expect, it } from 'vitest';

import { normalizarHover } from '../../src/normalizadores/normalizarHover.ts';

describe('normalizarHover', () => {
  it('gera evento hover com elemento_id, duracao_ms e elemento_tipo', () => {
    const normalizado = normalizarHover(
      { elementoId: 'card-plano-pro', duracao_ms: 1234.6, elemento_tipo: 'div' },
      { now: () => 10 },
    );
    expect(normalizado).toEqual({
      tipo: 'hover',
      timestamp: 10,
      dados: {
        elemento_id: 'card-plano-pro',
        elemento_tipo: 'div',
        duracao_ms: 1235,
      },
    });
  });

  it('descarta quando elementoId vazio', () => {
    expect(normalizarHover({ elementoId: '', duracao_ms: 1000 })).toBeNull();
  });

  it('descarta quando duracao nao e positiva', () => {
    expect(normalizarHover({ elementoId: 'x', duracao_ms: 0 })).toBeNull();
    expect(normalizarHover({ elementoId: 'x', duracao_ms: -5 })).toBeNull();
    expect(normalizarHover({ elementoId: 'x', duracao_ms: NaN })).toBeNull();
  });

  it('default elemento_tipo quando nao fornecido', () => {
    const normalizado = normalizarHover({ elementoId: 'x', duracao_ms: 100 });
    expect(normalizado?.dados.elemento_tipo).toBe('desconhecido');
  });
});
