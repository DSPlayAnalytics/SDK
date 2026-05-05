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

  it('enfileira evento quando nao ha pagina ativa e drena no proximo iniciar()', async () => {
    // A partir de 0.3.1: eventos disparados antes do controller mount (ex.
    // app_carregado em apps que registram analytics no module-load) sao
    // bufferados ate a primeira pagina ativar — preserva o early signal.
    const modulo = await import('../src');
    modulo.HeatmapUtils.resetarRegistro();
    document.body.innerHTML = '';

    const aceito = modulo.enviarEvento('sem_pagina_ainda', { x: 1 });
    expect(aceito).toBe(true);

    const heatmap = new modulo.HeatmapUtils(document.body, null, '/');
    heatmap.iniciar();
    const drenado = (heatmap.getDados().paginas['/']?.[0]?.eventos ?? [])
      .find((e) => e.tipo === 'custom' && e.dados.nome === 'sem_pagina_ainda');
    expect(drenado?.dados.propriedades).toMatchObject({ x: 1 });
    heatmap.parar();
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
