import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

describe('enviarEvento', () => {
  beforeEach(() => {
    vi.resetModules();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('empilha evento custom na pagina ativa', async () => {
    const modulo = await import('../src');
    modulo.HeatmapUtils.resetarRegistro();
    document.body.innerHTML = '';

    const heatmap = new modulo.HeatmapUtils(document.body, null, '/');
    heatmap.iniciar();

    const aceito = modulo.enviarEvento('checkout_iniciado', { plano: 'pro', preco: 99.9 });
    expect(aceito).toBe(true);

    const dados = heatmap.getDados();
    const custom = (dados.paginas['/']?.[0]?.eventos ?? []).find((e) => e.tipo === 'custom');
    expect(custom?.dados).toMatchObject({
      nome: 'checkout_iniciado',
      propriedades: { plano: 'pro', preco: 99.9 },
    });
    heatmap.parar();
  });

  it('retorna false quando nao ha pagina ativa', async () => {
    const modulo = await import('../src');
    modulo.HeatmapUtils.resetarRegistro();

    const aceito = modulo.enviarEvento('sem_pagina', { x: 1 });
    expect(aceito).toBe(false);
  });

  it('retorna false quando nome e invalido', async () => {
    const modulo = await import('../src');
    modulo.HeatmapUtils.resetarRegistro();
    document.body.innerHTML = '';

    const heatmap = new modulo.HeatmapUtils(document.body, null, '/');
    heatmap.iniciar();

    const aceito = modulo.enviarEvento('', { x: 1 });
    expect(aceito).toBe(false);
    heatmap.parar();
  });
});
