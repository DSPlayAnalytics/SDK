import { describe, expect, it } from 'vitest';

import { normalizarPageExit } from '../../src/normalizadores/normalizarPageExit.ts';

describe('normalizarPageExit', () => {
  it('gera evento page_exit com page_id, duracao_ms e motivo', () => {
    const normalizado = normalizarPageExit(
      { pageId: '/', duracao_ms: 4500, motivo: 'navegacao' },
      { now: () => 77 },
    );
    expect(normalizado).toEqual({
      tipo: 'page_exit',
      timestamp: 77,
      dados: { page_id: '/', duracao_ms: 4500, motivo: 'navegacao' },
    });
  });

  it('descarta motivo invalido', () => {
    expect(
      normalizarPageExit({ pageId: '/', duracao_ms: 10, motivo: 'outro' as any }),
    ).toBeNull();
  });

  it('descarta duracao negativa ou nao-numero', () => {
    expect(normalizarPageExit({ pageId: '/', duracao_ms: -1, motivo: 'unmount' })).toBeNull();
    expect(normalizarPageExit({ pageId: '/', duracao_ms: NaN, motivo: 'unmount' })).toBeNull();
  });

  it('aceita duracao zero', () => {
    const normalizado = normalizarPageExit({ pageId: '/', duracao_ms: 0, motivo: 'aba_fechada' });
    expect(normalizado?.dados.duracao_ms).toBe(0);
  });
});
