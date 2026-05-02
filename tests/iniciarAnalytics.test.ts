import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// localStorage polyfill gerenciado pelo setupTests.js; limpa entre testes aqui.

const ioMock = vi.fn(() => ({
  id: 'socket-init',
  emit: vi.fn(),
  on: vi.fn(),
  once: vi.fn(),
  off: vi.fn(),
  disconnect: vi.fn(),
}));

vi.mock('socket.io-client', () => ({ io: ioMock }));

describe('iniciarAnalytics', () => {
  beforeEach(() => {
    vi.resetModules();
    ioMock.mockClear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    for (const k of ['analytics_sdk.user_id', 'analytics_sdk.group_id', 'analytics_sdk.anon_id']) {
      localStorage.removeItem(k);
    }
  });

  it('exige websocketUrl, appId e ambiente', async () => {
    const { iniciarAnalytics } = await import('../src');

    expect(() => (iniciarAnalytics as any)({})).toThrow(/obrigatorios/);
    expect(() =>
      iniciarAnalytics({ websocketUrl: '', appId: 'x', ambiente: 'development' }),
    ).toThrow();
    expect(() =>
      iniciarAnalytics({ websocketUrl: 'u', appId: '', ambiente: 'development' } as any),
    ).toThrow();
  });

  it('configura o WebSocketService e abre conexao com a URL informada', async () => {
    const { iniciarAnalytics, WebSocketService } = await import('../src');

    iniciarAnalytics({
      websocketUrl: 'http://analytics.local:5000',
      appId: 'cliente-x',
      ambiente: 'production',
      debug: false,
      intervaloEnvioMs: 2500,
    });

    expect(ioMock).toHaveBeenCalledWith(
      'http://analytics.local:5000',
      expect.objectContaining({ reconnection: true }),
    );

    const status = WebSocketService.getConnectionStatus();
    expect(status.isConnected).toBe(false); // conexao e async, socket nao disparou 'connect'
    expect(status.pendingData).toBe(0);
  });

  it('userId/groupId passados no config sao hidratados no userStore', async () => {
    const { iniciarAnalytics, userStore } = await import('../src');
    userStore.reset();

    iniciarAnalytics({
      websocketUrl: 'http://analytics.local:5000',
      appId: 'cliente-x',
      ambiente: 'production',
      userId: 'u-ssr',
      groupId: 'org-ssr',
    });

    expect(userStore.getUserId()).toBe('u-ssr');
    expect(userStore.getGroupId()).toBe('org-ssr');
  });

  it('userId/groupId omitidos no config nao sobrescrevem store existente', async () => {
    const { iniciarAnalytics, userStore, identify } = await import('../src');
    userStore.reset();
    identify('u-pre');

    iniciarAnalytics({
      websocketUrl: 'http://analytics.local:5000',
      appId: 'cliente-x',
      ambiente: 'production',
    });

    expect(userStore.getUserId()).toBe('u-pre');
  });
});
