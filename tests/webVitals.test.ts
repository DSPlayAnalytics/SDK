import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

type Cb = (metric: any) => void;

// vitest >=1.0 aceita apenas 0 ou 1 type args (a assinatura completa da funcao).
const onLCPMock = vi.fn<(cb: Cb) => void>();
const onCLSMock = vi.fn<(cb: Cb) => void>();
const onINPMock = vi.fn<(cb: Cb) => void>();

vi.mock('web-vitals', () => ({
  onLCP: onLCPMock,
  onCLS: onCLSMock,
  onINP: onINPMock,
}));

describe('webVitals', () => {
  beforeEach(() => {
    vi.resetModules();
    onLCPMock.mockReset();
    onCLSMock.mockReset();
    onINPMock.mockReset();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('registra callbacks LCP/CLS/INP na primeira chamada e e idempotente', async () => {
    const { iniciarWebVitals } = await import('../src/webVitals.ts');
    iniciarWebVitals();
    iniciarWebVitals();
    iniciarWebVitals();

    expect(onLCPMock).toHaveBeenCalledTimes(1);
    expect(onCLSMock).toHaveBeenCalledTimes(1);
    expect(onINPMock).toHaveBeenCalledTimes(1);
  });

  it('encaminha metrica LCP normalizada para o HeatmapUtils ativo', async () => {
    const modulo = await import('../src');
    const { iniciarWebVitals, resetarWebVitalsParaTeste } = await import('../src/webVitals.ts');
    resetarWebVitalsParaTeste();
    modulo.HeatmapUtils.resetarRegistro();
    document.body.innerHTML = '';

    iniciarWebVitals();

    const heatmap = new modulo.HeatmapUtils(document.body, null, '/');
    heatmap.iniciar();

    // simula a lib entregando uma metrica LCP
    const cb = onLCPMock.mock.calls[0][0];
    cb({ name: 'LCP', value: 1800, rating: 'good', id: 'v3-lcp-1' });

    const dados = heatmap.getDados();
    const eventos = dados.paginas['/']?.[0]?.eventos ?? [];
    const vital = eventos.find((e) => e.tipo === 'web_vital');
    expect(vital?.dados).toMatchObject({ nome: 'LCP', valor: 1800, rating: 'good' });

    heatmap.parar();
  });

  it('ignora metrica com nome invalido', async () => {
    const modulo = await import('../src');
    const { iniciarWebVitals, resetarWebVitalsParaTeste } = await import('../src/webVitals.ts');
    resetarWebVitalsParaTeste();
    modulo.HeatmapUtils.resetarRegistro();
    document.body.innerHTML = '';

    iniciarWebVitals();
    const heatmap = new modulo.HeatmapUtils(document.body, null, '/');
    heatmap.iniciar();

    const cb = onCLSMock.mock.calls[0][0];
    cb({ name: 'FID', value: 100 } as any); // FID fora do conjunto permitido

    const dados = heatmap.getDados();
    const eventos = dados.paginas['/']?.[0]?.eventos ?? [];
    expect(eventos.filter((e) => e.tipo === 'web_vital')).toHaveLength(0);
    heatmap.parar();
  });
});
