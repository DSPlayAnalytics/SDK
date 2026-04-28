import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { HeatmapUtils } from '../src';
import type { HeatmapDados } from '../src';

const contarPorTipo = (dados: HeatmapDados, pageId: string, tipo: string) =>
  (dados.paginas[pageId]?.[0]?.eventos ?? []).filter((e) => e.tipo === tipo).length;

describe('Diagnostico — coleta temporal com emissao de delta', () => {
  beforeEach(() => {
    vi.useFakeTimers({ now: new Date('2026-04-17T23:30:00Z') });
    vi.spyOn(console, 'log').mockImplementation(() => {});
    HeatmapUtils.resetarRegistro();
    document.body.innerHTML = '';
  });

  afterEach(() => {
    vi.runOnlyPendingTimers();
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('emite apenas o que aconteceu entre ticks (nao cumulativo)', async () => {
    const raiz = document.createElement('div');
    const botao = document.createElement('button');
    botao.id = 'btn-diag';
    raiz.appendChild(botao);
    document.body.appendChild(raiz);

    Object.defineProperty(raiz, 'scrollHeight', { configurable: true, value: 2000 });
    Object.defineProperty(raiz, 'clientHeight', { configurable: true, value: 500 });
    Object.defineProperty(raiz, 'scrollTop', { configurable: true, writable: true, value: 0 });

    const emitidos: HeatmapDados[] = [];

    const heatmap = new HeatmapUtils(raiz, null, '/');
    heatmap.configurarColecaoTempoReal((dados) => {
      emitidos.push(JSON.parse(JSON.stringify(dados)));
    }, 5000);
    heatmap.iniciarColecaoTempoReal();
    heatmap.iniciar();

    await vi.advanceTimersByTimeAsync(1000);
    botao.dispatchEvent(new MouseEvent('click', { bubbles: true, clientX: 10, clientY: 20 }));
    await vi.advanceTimersByTimeAsync(500);
    (raiz as any).scrollTop = 400;
    raiz.dispatchEvent(new Event('scroll', { bubbles: true }));
    await vi.advanceTimersByTimeAsync(3500); // 1º tick em ~5s

    botao.dispatchEvent(new MouseEvent('click', { bubbles: true, clientX: 40, clientY: 50 }));
    await vi.advanceTimersByTimeAsync(5000); // 2º tick em ~10s

    await vi.advanceTimersByTimeAsync(5000); // 3º tick em ~15s

    expect(emitidos.length).toBeGreaterThanOrEqual(3);

    // 1º tick: 1 page_view + 1 click + 1 scroll_depth (marco 25)
    expect(contarPorTipo(emitidos[0], '/', 'page_view')).toBe(1);
    expect(contarPorTipo(emitidos[0], '/', 'click')).toBe(1);
    expect(contarPorTipo(emitidos[0], '/', 'scroll_depth')).toBeGreaterThanOrEqual(1);
    expect(emitidos[0].paginas['/']?.[0]?.visualizacoes).toBe(1);

    // 2º tick: 0 page_view novo, 1 click novo, 0 scroll_depth novo
    expect(contarPorTipo(emitidos[1], '/', 'page_view')).toBe(0);
    expect(contarPorTipo(emitidos[1], '/', 'click')).toBe(1);
    expect(contarPorTipo(emitidos[1], '/', 'scroll_depth')).toBe(0);
    expect(emitidos[1].paginas['/']?.[0]?.visualizacoes).toBe(0);

    // 3º tick: sem novos eventos
    expect(contarPorTipo(emitidos[2], '/', 'click')).toBe(0);
    expect(emitidos[2].paginas['/']?.[0]?.visualizacoes).toBe(0);

    // soma dos deltas bate com totais
    const totalClicks = emitidos.reduce((acc, d) => acc + contarPorTipo(d, '/', 'click'), 0);
    const totalViews = emitidos.reduce((acc, d) => acc + (d.paginas['/']?.[0]?.visualizacoes ?? 0), 0);
    expect(totalClicks).toBe(2);
    expect(totalViews).toBe(1);
  });

  it('parar() emite residuo final com page_exit', async () => {
    const raiz = document.createElement('div');
    const botao = document.createElement('button');
    raiz.appendChild(botao);
    document.body.appendChild(raiz);

    const emitidos: HeatmapDados[] = [];

    const heatmap = new HeatmapUtils(raiz, null, '/');
    heatmap.configurarColecaoTempoReal((dados) => {
      emitidos.push(JSON.parse(JSON.stringify(dados)));
    }, 5000);
    heatmap.iniciarColecaoTempoReal();
    heatmap.iniciar();

    botao.dispatchEvent(new MouseEvent('click', { bubbles: true, clientX: 1, clientY: 2 }));
    await vi.advanceTimersByTimeAsync(5000); // 1º tick com click
    botao.dispatchEvent(new MouseEvent('click', { bubbles: true, clientX: 3, clientY: 4 }));
    await vi.advanceTimersByTimeAsync(2000);

    heatmap.parar();

    const clicksPorTick = emitidos.map((d) => contarPorTipo(d, '/', 'click'));
    expect(clicksPorTick).toEqual([1, 1]);
    expect(contarPorTipo(emitidos[emitidos.length - 1], '/', 'page_exit')).toBe(1);
  });
});
