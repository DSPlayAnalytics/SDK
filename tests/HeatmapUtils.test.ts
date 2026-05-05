import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { HeatmapDados, HeatmapUtils } from '../src';
import type { EventoNormalizado, PaginaDados } from '../src';

const criarPaginaDados = (sobrescritas: Partial<PaginaDados> = {}): PaginaDados => ({
  eventos: [],
  visualizacoes: 0,
  segundos: 0,
  timestamp_inicial: null,
  timestamp_final: null,
  ...sobrescritas,
});

const eventoClick = (): EventoNormalizado => ({
  tipo: 'click',
  timestamp: 1000,
  dados: { x: 1, y: 2, elemento_id: 'x', elemento_tipo: 'button' },
});

describe('HeatmapDados.from_dict', () => {
  it('calcula totais de visualizacoes, cliques e tempo por pagina', () => {
    const dados = HeatmapDados.from_dict({
      id_registro: 'registro-local',
      timestamp_inicial: 1000,
      timestamp_final: 7000,
      paginas: {
        '/': [criarPaginaDados({ visualizacoes: 2, segundos: 10, eventos: [eventoClick()] })],
        '/sobre': [criarPaginaDados({ visualizacoes: 1, segundos: 5, eventos: [eventoClick()] })],
        '/projetos': [criarPaginaDados({ visualizacoes: 3, segundos: 8 })],
      },
    });

    expect(dados.get_total_visualizacoes?.()).toBe(6);
    expect(dados.get_total_cliques?.()).toBe(2);
    expect(dados.get_total_tempo_segundos?.()).toBe(23);
    expect(dados.get_duracao_sessao_segundos?.()).toBe(6);
  });

  it('gera valores padrao seguros quando campos opcionais nao sao enviados', () => {
    const dados = HeatmapDados.from_dict({});

    expect(dados.id_registro).toEqual(expect.any(String));
    expect(dados.paginas).toEqual({});
    expect(dados.get_duracao_sessao_segundos?.()).toBeNull();
  });

  it('calcula totais considerando paginas dinamicas', () => {
    const dados = HeatmapDados.from_dict({
      paginas: {
        '/blog/artigo': [
          criarPaginaDados({
            visualizacoes: 4,
            segundos: 30,
            eventos: [eventoClick()],
          }),
        ],
      },
    });

    expect(dados.paginas['/blog/artigo']).toHaveLength(1);
    expect(dados.get_total_visualizacoes?.()).toBe(4);
    expect(dados.get_total_cliques?.()).toBe(1);
    expect(dados.get_total_tempo_segundos?.()).toBe(30);
  });
});

describe('HeatmapUtils', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.spyOn(console, 'log').mockImplementation(() => {});
    HeatmapUtils.resetarRegistro();
    document.body.innerHTML = '';
  });

  afterEach(() => {
    vi.runOnlyPendingTimers();
    vi.useRealTimers();
    vi.restoreAllMocks();
    HeatmapUtils.resetarRegistro();
  });

  it('gera page_view no iniciar e page_exit no parar', () => {
    const heatmap = new HeatmapUtils(document.body, null, '/home');
    heatmap.iniciar();
    vi.advanceTimersByTime(1000);
    heatmap.parar();

    const dados = HeatmapUtils.getDadosGlobais();
    const eventos = dados.paginas['/home']?.[0]?.eventos ?? [];
    const tipos = eventos.map((e) => e.tipo);
    expect(tipos[0]).toBe('page_view');
    expect(tipos[tipos.length - 1]).toBe('page_exit');
  });

  it('coleta click como evento normalizado', () => {
    const raiz = document.createElement('div');
    const botao = document.createElement('button');
    botao.setAttribute('data-analytics-id', 'cta-topo');
    raiz.appendChild(botao);
    document.body.appendChild(raiz);

    const heatmap = new HeatmapUtils(raiz, null, '/');
    heatmap.iniciar();
    botao.dispatchEvent(new MouseEvent('click', { bubbles: true, clientX: 5, clientY: 6 }));

    const dados = heatmap.getDados();
    const eventos = dados.paginas['/']?.[0]?.eventos ?? [];
    const click = eventos.find((e) => e.tipo === 'click');
    expect(click).toBeDefined();
    expect(click?.dados.elemento_id).toBe('cta-topo');
    heatmap.parar();
  });

  it('emite scroll_depth apenas em marcos e so uma vez cada', () => {
    const raiz = document.createElement('div');
    document.body.appendChild(raiz);
    Object.defineProperty(raiz, 'scrollHeight', { configurable: true, value: 2000 });
    Object.defineProperty(raiz, 'clientHeight', { configurable: true, value: 500 });
    Object.defineProperty(raiz, 'scrollTop', { configurable: true, writable: true, value: 0 });

    const heatmap = new HeatmapUtils(raiz, null, '/');
    heatmap.iniciar();

    (raiz as any).scrollTop = 400; // ~27% -> marco 25
    raiz.dispatchEvent(new Event('scroll'));
    (raiz as any).scrollTop = 420;
    raiz.dispatchEvent(new Event('scroll')); // nao deve duplicar marco 25
    (raiz as any).scrollTop = 800; // ~53% -> marco 50
    raiz.dispatchEvent(new Event('scroll'));

    const dados = heatmap.getDados();
    const marcos = (dados.paginas['/']?.[0]?.eventos ?? [])
      .filter((e) => e.tipo === 'scroll_depth')
      .map((e) => e.dados.marco);
    expect(marcos).toEqual([25, 50]);
    heatmap.parar();
  });

  it('reseta o registro global entre sessoes de coleta', () => {
    const heatmap = new HeatmapUtils(document.body, null, '/sobre');
    heatmap.iniciar();
    heatmap.getDados();

    expect(HeatmapUtils.getDadosGlobais().paginas['/sobre']).toHaveLength(1);

    HeatmapUtils.resetarRegistro();

    const dados = HeatmapUtils.getDadosGlobais();
    expect(dados.paginas).toEqual({});
  });

  it('coleta dados para paginas dinamicas sem depender de chaves predefinidas', () => {
    const raiz = document.createElement('main');
    document.body.appendChild(raiz);

    const heatmap = new HeatmapUtils(raiz, null, '/blog/artigo');
    heatmap.iniciar();
    heatmap.getDados();

    const dados = HeatmapUtils.getDadosGlobais();

    expect(dados.paginas['/blog/artigo']).toHaveLength(1);
    expect(dados.paginas['/blog/artigo'][0].visualizacoes).toBe(1);
    expect(Object.keys(dados.paginas)).toEqual(['/blog/artigo']);

    heatmap.parar();
  });

  it('empilhaEventoNoAtivo anexa evento externo ao buffer da pagina ativa', () => {
    const heatmap = new HeatmapUtils(document.body, null, '/');
    heatmap.iniciar();

    const aceito = HeatmapUtils.empilharEventoNoAtivo({
      tipo: 'custom',
      timestamp: Date.now(),
      dados: { nome: 'foo', propriedades: {} },
    });

    expect(aceito).toBe(true);
    const dados = heatmap.getDados();
    const custom = (dados.paginas['/']?.[0]?.eventos ?? []).filter((e) => e.tipo === 'custom');
    expect(custom).toHaveLength(1);
    heatmap.parar();
  });

  describe('buffer-and-drain pre-iniciar', () => {
    it('enfileira eventos quando nenhuma pagina ativa e drena no primeiro iniciar()', () => {
      // Cenario: web vital ou enviarEvento dispara antes do controller mount.
      const evento1: EventoNormalizado = {
        tipo: 'web_vital',
        timestamp: 1000,
        dados: { nome: 'LCP', valor: 1800, rating: 'good' },
      };
      const evento2: EventoNormalizado = {
        tipo: 'custom',
        timestamp: 1100,
        dados: { nome: 'app_carregado', propriedades: { rota: '/' } },
      };

      // Sem bufferAtivo, mas evento nao deve ser perdido — fica pendente.
      expect(HeatmapUtils.empilharEventoNoAtivo(evento1)).toBe(true);
      expect(HeatmapUtils.empilharEventoNoAtivo(evento2)).toBe(true);

      const heatmap = new HeatmapUtils(document.body, null, '/');
      heatmap.iniciar();

      const eventos = heatmap.getDados().paginas['/']?.[0]?.eventos ?? [];
      const vital = eventos.find((e) => e.tipo === 'web_vital');
      const custom = eventos.find((e) => e.tipo === 'custom');
      expect(vital?.dados).toMatchObject({ nome: 'LCP', valor: 1800 });
      expect(custom?.dados).toMatchObject({ nome: 'app_carregado' });
      heatmap.parar();
    });

    it('drena pendentes apenas no primeiro iniciar — nao reaplica em paginas seguintes', () => {
      const evento: EventoNormalizado = {
        tipo: 'custom',
        timestamp: 1000,
        dados: { nome: 'evento_inicial', propriedades: {} },
      };

      HeatmapUtils.empilharEventoNoAtivo(evento);

      const primeira = new HeatmapUtils(document.body, null, '/');
      primeira.iniciar();
      primeira.parar();

      const segunda = new HeatmapUtils(document.body, null, '/sobre');
      segunda.iniciar();
      const eventosSegunda = segunda.getDados().paginas['/sobre']?.[0]?.eventos ?? [];
      const vazamento = eventosSegunda.filter((e) => e.tipo === 'custom' && e.dados.nome === 'evento_inicial');
      expect(vazamento).toHaveLength(0);
      segunda.parar();
    });

    it('limita o tamanho do buffer pendente para evitar memory leak', () => {
      // Cap de 100 eventos. Apos isso, descarta os mais novos pra preservar
      // o early signal (LCP, primeiro custom event) que e o motivo do buffer existir.
      const TOTAL = 150;
      for (let i = 0; i < TOTAL; i++) {
        HeatmapUtils.empilharEventoNoAtivo({
          tipo: 'custom',
          timestamp: 1000 + i,
          dados: { nome: `e${i}`, propriedades: {} },
        });
      }

      const heatmap = new HeatmapUtils(document.body, null, '/');
      heatmap.iniciar();
      const drainados = (heatmap.getDados().paginas['/']?.[0]?.eventos ?? [])
        .filter((e) => e.tipo === 'custom');
      expect(drainados.length).toBeLessThanOrEqual(100);
      // Primeiro evento (early) preservado
      expect(drainados[0]?.dados.nome).toBe('e0');
      heatmap.parar();
    });

    it('resetarRegistro limpa pendentes para nao vazar entre testes/sessoes', () => {
      HeatmapUtils.empilharEventoNoAtivo({
        tipo: 'custom',
        timestamp: 1000,
        dados: { nome: 'antes_reset', propriedades: {} },
      });
      HeatmapUtils.resetarRegistro();

      const heatmap = new HeatmapUtils(document.body, null, '/');
      heatmap.iniciar();
      const eventos = heatmap.getDados().paginas['/']?.[0]?.eventos ?? [];
      const sobreviventes = eventos.filter((e) => e.tipo === 'custom' && e.dados.nome === 'antes_reset');
      expect(sobreviventes).toHaveLength(0);
      heatmap.parar();
    });
  });
});
