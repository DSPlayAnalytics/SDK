import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { HeatmapDadosTipo } from '../src';
import { StorageMemoria } from '../src/filaAnalytics.ts';

type Handler = (...args: any[]) => void;

class SocketMock {
  id = 'socket-teste';
  handlers = new Map<string, Handler[]>();
  onceHandlers = new Map<string, Handler[]>();
  emit = vi.fn();
  disconnect = vi.fn(() => {
    this.trigger('disconnect', 'io client disconnect');
  });

  on(evento: string, handler: Handler) {
    const handlers = this.handlers.get(evento) ?? [];
    handlers.push(handler);
    this.handlers.set(evento, handlers);
    return this;
  }

  once(evento: string, handler: Handler) {
    const handlers = this.onceHandlers.get(evento) ?? [];
    handlers.push(handler);
    this.onceHandlers.set(evento, handlers);
    return this;
  }

  off(evento: string, handler: Handler) {
    this.handlers.set(evento, (this.handlers.get(evento) ?? []).filter((i) => i !== handler));
    this.onceHandlers.set(evento, (this.onceHandlers.get(evento) ?? []).filter((i) => i !== handler));
    return this;
  }

  trigger(evento: string, ...args: any[]) {
    for (const handler of this.handlers.get(evento) ?? []) handler(...args);
    const onceHandlers = this.onceHandlers.get(evento) ?? [];
    this.onceHandlers.delete(evento);
    for (const handler of onceHandlers) handler(...args);
  }
}

const socketsCriados: SocketMock[] = [];
const ioMock = vi.fn(() => {
  const socket = new SocketMock();
  socketsCriados.push(socket);
  return socket;
});

vi.mock('socket.io-client', () => ({ io: ioMock }));

const criarDadosAnalytics = (id = 'registro-teste'): HeatmapDadosTipo => ({
  id_registro: id,
  timestamp_inicial: 1000,
  timestamp_final: 2000,
  paginas: {},
});

const configuracaoComStorageMemoria = () => ({
  websocketUrl: 'http://localhost:5000',
  appId: 'portfolio-teste',
  ambiente: 'development' as const,
  debug: false,
  intervaloEnvioMs: 5000,
  storageFila: new StorageMemoria(),
});

const carregarServicoConfigurado = async () => {
  const modulo = await import('../src');
  modulo.WebSocketService.configurar(configuracaoComStorageMemoria());
  return modulo.WebSocketService;
};

describe('WebSocketService', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.resetModules();
    socketsCriados.length = 0;
    ioMock.mockClear();
  });

  afterEach(() => {
    vi.runOnlyPendingTimers();
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('recusa operar antes de iniciarAnalytics', async () => {
    const modulo = await import('../src');
    const servico = modulo.WebSocketService;

    const conectado = await servico.connect();
    expect(conectado).toBe(false);
    expect(ioMock).not.toHaveBeenCalled();
  });

  it('conecta usando a URL configurada e emite analytics_data com app_id/ambiente', async () => {
    const servico = await carregarServicoConfigurado();
    const dados = criarDadosAnalytics();

    const envio = servico.sendAnalyticsData(dados);
    await vi.advanceTimersByTimeAsync(0);
    const socket = socketsCriados[0];
    socket.trigger('connect');
    await vi.advanceTimersByTimeAsync(0);
    socket.trigger('analytics_received', { status: 'success' });

    await expect(envio).resolves.toBe(true);

    expect(ioMock).toHaveBeenCalledWith(
      'http://localhost:5000',
      expect.objectContaining({ transports: ['websocket', 'polling'], reconnection: true }),
    );
    // id_registro e reescrito pela FilaAnalytics com o uuid do item; aqui so
    // verificamos que os campos do envelope e do payload foram enviados.
    expect(socket.emit).toHaveBeenCalledWith(
      'analytics_data',
      expect.objectContaining({
        timestamp_inicial: dados.timestamp_inicial,
        timestamp_final: dados.timestamp_final,
        paginas: dados.paginas,
        app_id: 'portfolio-teste',
        ambiente: 'development',
      }),
    );
    expect(await servico.tamanhoFilaOffline()).toBe(0);
  });

  it('mantem dados na fila quando nao conecta', async () => {
    const servico = await carregarServicoConfigurado();
    const envio = servico.sendAnalyticsData(criarDadosAnalytics());

    await vi.advanceTimersByTimeAsync(10000);

    await expect(envio).resolves.toBe(false);
    expect(await servico.tamanhoFilaOffline()).toBe(1);
  });

  it('drena fila apos conectar', async () => {
    const servico = await carregarServicoConfigurado();
    const envio1 = servico.sendAnalyticsData(criarDadosAnalytics('a'));
    await vi.advanceTimersByTimeAsync(10000);
    await expect(envio1).resolves.toBe(false);
    expect(await servico.tamanhoFilaOffline()).toBe(1);

    // nova tentativa de conexao que agora conecta
    const reconexao = servico.connect();
    const socket = socketsCriados.at(-1)!;
    socket.trigger('connect');
    // drenagem emite — simula ack de sucesso
    await vi.advanceTimersByTimeAsync(0);
    socket.trigger('analytics_received', { status: 'success' });
    await reconexao;
    await vi.advanceTimersByTimeAsync(0);

    // id_registro original ('a') e sobrescrito pela fila; validamos que a
    // drenagem emitiu o envelope certo (app_id + campos do payload).
    expect(socket.emit).toHaveBeenCalledWith(
      'analytics_data',
      expect.objectContaining({ app_id: 'portfolio-teste', ambiente: 'development' }),
    );
    expect(await servico.tamanhoFilaOffline()).toBe(0);
  });

  it('limparFilaOffline apaga itens persistidos (LGPD/revogacao de consentimento)', async () => {
    const servico = await carregarServicoConfigurado();
    servico.sendAnalyticsData(criarDadosAnalytics('a'));
    await vi.advanceTimersByTimeAsync(10000); // nao conecta, fica na fila

    expect(await servico.tamanhoFilaOffline()).toBe(1);
    await servico.limparFilaOffline();
    expect(await servico.tamanhoFilaOffline()).toBe(0);
  });

  it('respeita limite configurado descartando os mais antigos', async () => {
    const modulo = await import('../src');
    modulo.WebSocketService.configurar({
      ...configuracaoComStorageMemoria(),
      limiteFilaOffline: 2,
    });

    modulo.WebSocketService.sendAnalyticsData(criarDadosAnalytics('velho-1'));
    modulo.WebSocketService.sendAnalyticsData(criarDadosAnalytics('velho-2'));
    modulo.WebSocketService.sendAnalyticsData(criarDadosAnalytics('novo'));
    await vi.advanceTimersByTimeAsync(10000);

    expect(await modulo.WebSocketService.tamanhoFilaOffline()).toBe(2);
  });

  it('falha de storage no enfileirar: retorna false, emite analytics:enqueue_failed, nao vira unhandled rejection', async () => {
    const modulo = await import('../src');

    const storageQuebrado = new StorageMemoria();
    storageQuebrado.enfileirar = vi.fn(async () => {
      throw new DOMException('quota exceeded', 'QuotaExceededError');
    });

    modulo.WebSocketService.configurar({
      ...configuracaoComStorageMemoria(),
      storageFila: storageQuebrado,
    });

    const eventos: CustomEvent[] = [];
    const listener = (e: Event) => eventos.push(e as CustomEvent);
    window.addEventListener('analytics:enqueue_failed', listener);

    try {
      const envio = modulo.WebSocketService.sendAnalyticsData(criarDadosAnalytics('falha'));
      await expect(envio).resolves.toBe(false);
      expect(eventos).toHaveLength(1);
      expect(eventos[0].detail).toMatchObject({
        idRegistro: 'falha',
        reason: expect.stringContaining('QuotaExceededError'),
      });
    } finally {
      window.removeEventListener('analytics:enqueue_failed', listener);
    }
  });
});
