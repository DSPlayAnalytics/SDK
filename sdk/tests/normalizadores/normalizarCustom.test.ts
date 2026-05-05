import { describe, expect, it } from 'vitest';

import { normalizarCustom } from '../../src/normalizadores/normalizarCustom.ts';

describe('normalizarCustom', () => {
  it('gera evento custom com nome e propriedades primitivas', () => {
    const normalizado = normalizarCustom(
      { nome: 'checkout_iniciado', propriedades: { plano: 'pro', preco: 99.9, recorrente: true, cupom: null } },
      { now: () => 1 },
    );
    expect(normalizado).toEqual({
      tipo: 'custom',
      timestamp: 1,
      dados: {
        nome: 'checkout_iniciado',
        propriedades: { plano: 'pro', preco: 99.9, recorrente: true, cupom: null },
      },
    });
  });

  it('descarta quando nome e vazio ou nao-string', () => {
    expect(normalizarCustom({ nome: '' })).toBeNull();
    expect(normalizarCustom({ nome: 123 as any })).toBeNull();
  });

  it('remove valores nao-primitivos (objeto, array, funcao)', () => {
    const normalizado = normalizarCustom({
      nome: 'compra',
      propriedades: {
        plano: 'pro',
        itens: [1, 2, 3] as any,
        usuario: { email: 'a@b.com' } as any,
        callback: (() => 1) as any,
      },
    });
    expect(normalizado?.dados.propriedades).toEqual({ plano: 'pro' });
  });

  it('trunca nome longo e strings longas', () => {
    const nomeLongo = 'x'.repeat(200);
    const stringLonga = 'y'.repeat(1000);
    const normalizado = normalizarCustom({ nome: nomeLongo, propriedades: { texto: stringLonga } });
    expect((normalizado?.dados.nome as string).length).toBe(64);
    const props = normalizado?.dados.propriedades as Record<string, string>;
    expect(props.texto.length).toBe(512);
  });
});
