import { describe, expect, it } from 'vitest';

import { normalizarPageView } from '../../src/normalizadores/normalizarPageView.ts';

describe('normalizarPageView', () => {
  it('gera evento page_view canonico', () => {
    const normalizado = normalizarPageView(
      { pageId: '/', path: '/', title: 'Home' },
      { now: () => 42 },
    );
    expect(normalizado).toEqual({
      tipo: 'page_view',
      timestamp: 42,
      dados: { page_id: '/', path: '/', title: 'Home' },
    });
  });

  it('omite title quando nao fornecido', () => {
    const normalizado = normalizarPageView({ pageId: '/sobre', path: '/sobre' });
    expect(normalizado?.dados).toEqual({ page_id: '/sobre', path: '/sobre' });
  });

  it('descarta quando pageId ou path ausentes', () => {
    expect(normalizarPageView({ pageId: '', path: '/' })).toBeNull();
    expect(normalizarPageView({ pageId: '/', path: '' })).toBeNull();
  });
});
