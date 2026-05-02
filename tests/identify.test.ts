/**
 * v0.4: identify(userId, traits?), group(orgId, traits?), reset() emitem
 * eventos `__identify`, `__group`, `__reset` no buffer global de eventos
 * (mesmo canal que enviarEvento), e atualizam o UserStore para que
 * envelopes subsequentes carreguem user_id/group_id.
 *
 * Traits viajam no payload do evento mas NUNCA persistem (sem PII no
 * localStorage — politica documentada em README v0.4).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const KEY_USER = 'analytics_sdk.user_id';
const KEY_GROUP = 'analytics_sdk.group_id';
const KEY_ANON = 'analytics_sdk.anon_id';

beforeEach(() => {
  for (const k of [KEY_USER, KEY_GROUP, KEY_ANON]) localStorage.removeItem(k);
  vi.resetModules();
});

afterEach(() => {
  vi.restoreAllMocks();
});

async function carregarSdk() {
  const modulo = await import('../src');
  modulo.HeatmapUtils.resetarRegistro();
  document.body.innerHTML = '';
  const heatmap = new modulo.HeatmapUtils(document.body, null, '/');
  heatmap.iniciar();
  return { modulo, heatmap };
}

describe('identify(userId)', () => {
  it('seta userId no UserStore e emite evento __identify', async () => {
    const { modulo, heatmap } = await carregarSdk();

    modulo.identify('u-42');

    expect(modulo.userStore.getUserId()).toBe('u-42');

    const eventos = heatmap.getDados().paginas['/']?.[0]?.eventos ?? [];
    const id = eventos.find((e) => e.tipo === 'custom' && e.dados.nome === '__identify');
    expect(id).toBeDefined();
    expect(id?.dados.propriedades).toMatchObject({ user_id: 'u-42' });
    heatmap.parar();
  });

  it('inclui traits no payload do evento mas NAO persiste', async () => {
    const { modulo, heatmap } = await carregarSdk();

    modulo.identify('u-42', { plan: 'pro', signup_at: 1700000000 });

    const eventos = heatmap.getDados().paginas['/']?.[0]?.eventos ?? [];
    const id = eventos.find((e) => e.tipo === 'custom' && e.dados.nome === '__identify');
    expect(id?.dados.propriedades).toMatchObject({
      user_id: 'u-42',
      trait_plan: 'pro',
      trait_signup_at: 1700000000,
    });
    // localStorage NAO contem traits — so user_id (politica anti-PII).
    expect(localStorage.getItem('analytics_sdk.trait_plan')).toBeNull();
    heatmap.parar();
  });

  it('chamado 2x com userId diferente substitui (nao mistura)', async () => {
    const { modulo, heatmap } = await carregarSdk();

    modulo.identify('u-1');
    modulo.identify('u-2');

    expect(modulo.userStore.getUserId()).toBe('u-2');
    const eventos = heatmap.getDados().paginas['/']?.[0]?.eventos ?? [];
    const ids = eventos.filter((e) => e.tipo === 'custom' && e.dados.nome === '__identify');
    expect(ids).toHaveLength(2);
    expect(ids[1]?.dados.propriedades).toMatchObject({ user_id: 'u-2' });
    heatmap.parar();
  });

  it('userId vazio/whitespace retorna false e nao seta', async () => {
    const { modulo, heatmap } = await carregarSdk();

    expect(modulo.identify('')).toBe(false);
    expect(modulo.identify('   ')).toBe(false);
    expect(modulo.userStore.getUserId()).toBeNull();
    heatmap.parar();
  });

  it('antes de iniciar() enfileira no buffer pre-iniciar', async () => {
    const modulo = await import('../src');
    modulo.HeatmapUtils.resetarRegistro();
    document.body.innerHTML = '';

    modulo.identify('u-bootstrap', { plan: 'free' });

    const heatmap = new modulo.HeatmapUtils(document.body, null, '/');
    heatmap.iniciar();
    const eventos = heatmap.getDados().paginas['/']?.[0]?.eventos ?? [];
    const id = eventos.find((e) => e.tipo === 'custom' && e.dados.nome === '__identify');
    expect(id?.dados.propriedades).toMatchObject({
      user_id: 'u-bootstrap',
      trait_plan: 'free',
    });
    heatmap.parar();
  });
});

describe('group(orgId)', () => {
  it('seta groupId e emite evento __group', async () => {
    const { modulo, heatmap } = await carregarSdk();

    modulo.group('acme-corp', { plan: 'enterprise' });

    expect(modulo.userStore.getGroupId()).toBe('acme-corp');
    const eventos = heatmap.getDados().paginas['/']?.[0]?.eventos ?? [];
    const ev = eventos.find((e) => e.tipo === 'custom' && e.dados.nome === '__group');
    expect(ev?.dados.propriedades).toMatchObject({
      group_id: 'acme-corp',
      trait_plan: 'enterprise',
    });
    heatmap.parar();
  });

  it('group vazio retorna false', async () => {
    const { modulo, heatmap } = await carregarSdk();
    expect(modulo.group('')).toBe(false);
    expect(modulo.userStore.getGroupId()).toBeNull();
    heatmap.parar();
  });
});

describe('reset()', () => {
  it('apaga userId+groupId, regenera anonId, emite __reset', async () => {
    const { modulo, heatmap } = await carregarSdk();

    modulo.identify('u-42');
    modulo.group('acme');
    const anonAntes = modulo.userStore.getAnonId();

    modulo.reset();

    expect(modulo.userStore.getUserId()).toBeNull();
    expect(modulo.userStore.getGroupId()).toBeNull();
    expect(modulo.userStore.getAnonId()).not.toBe(anonAntes);

    const eventos = heatmap.getDados().paginas['/']?.[0]?.eventos ?? [];
    const reset = eventos.find((e) => e.tipo === 'custom' && e.dados.nome === '__reset');
    expect(reset).toBeDefined();
    heatmap.parar();
  });
});
