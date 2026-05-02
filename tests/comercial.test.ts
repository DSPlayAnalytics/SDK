/**
 * v0.4 helpers comerciais: trackPurchase, trackSignup, trackConversion.
 * Emitem eventos __purchase, __signup, __conversion no buffer global.
 * Campos value/currency/plan viajam no payload; metadata sanitizada (só primitivos).
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

function pegarEvento(heatmap: any, nome: string) {
  return (heatmap.getDados().paginas['/']?.[0]?.eventos ?? []).find(
    (e: any) => e.tipo === 'custom' && e.dados.nome === nome,
  );
}

describe('trackPurchase', () => {
  it('emite __purchase com value e currency', async () => {
    const { modulo, heatmap } = await carregarSdk();

    const ok = modulo.trackPurchase(99.9, 'BRL');
    expect(ok).toBe(true);

    const ev = pegarEvento(heatmap, '__purchase');
    expect(ev).toBeDefined();
    expect(ev.dados.propriedades).toMatchObject({ value: 99.9, currency: 'BRL' });
    heatmap.parar();
  });

  it('inclui metadata sanitizada no payload', async () => {
    const { modulo, heatmap } = await carregarSdk();

    modulo.trackPurchase(49.0, 'USD', { plan: 'pro', trial: false });

    const ev = pegarEvento(heatmap, '__purchase');
    expect(ev.dados.propriedades).toMatchObject({
      value: 49.0,
      currency: 'USD',
      plan: 'pro',
      trial: false,
    });
    heatmap.parar();
  });

  it('retorna false para value nao-finito', async () => {
    const { modulo, heatmap } = await carregarSdk();

    expect(modulo.trackPurchase(NaN, 'BRL')).toBe(false);
    expect(modulo.trackPurchase(Infinity, 'BRL')).toBe(false);
    expect(modulo.trackPurchase(-1, 'BRL')).toBe(false);
    heatmap.parar();
  });

  it('retorna false para currency vazia', async () => {
    const { modulo, heatmap } = await carregarSdk();

    expect(modulo.trackPurchase(10, '')).toBe(false);
    expect(modulo.trackPurchase(10, '   ')).toBe(false);
    heatmap.parar();
  });

  it('descarta metadata com objetos/arrays/funcoes', async () => {
    const { modulo, heatmap } = await carregarSdk();

    modulo.trackPurchase(10, 'BRL', {
      nested: { a: 1 } as any,
      arr: [1, 2] as any,
      fn: (() => {}) as any,
      ok: 'sim',
    });

    const ev = pegarEvento(heatmap, '__purchase');
    expect(ev.dados.propriedades).not.toHaveProperty('nested');
    expect(ev.dados.propriedades).not.toHaveProperty('arr');
    expect(ev.dados.propriedades).not.toHaveProperty('fn');
    expect(ev.dados.propriedades).toHaveProperty('ok', 'sim');
    heatmap.parar();
  });
});

describe('trackSignup', () => {
  it('emite __signup com plan', async () => {
    const { modulo, heatmap } = await carregarSdk();

    const ok = modulo.trackSignup('pro');
    expect(ok).toBe(true);

    const ev = pegarEvento(heatmap, '__signup');
    expect(ev).toBeDefined();
    expect(ev.dados.propriedades).toMatchObject({ plan: 'pro' });
    heatmap.parar();
  });

  it('inclui metadata sanitizada', async () => {
    const { modulo, heatmap } = await carregarSdk();

    modulo.trackSignup('enterprise', { source: 'landing', seats: 10 });

    const ev = pegarEvento(heatmap, '__signup');
    expect(ev.dados.propriedades).toMatchObject({
      plan: 'enterprise',
      source: 'landing',
      seats: 10,
    });
    heatmap.parar();
  });

  it('retorna false para plan vazio/whitespace', async () => {
    const { modulo, heatmap } = await carregarSdk();

    expect(modulo.trackSignup('')).toBe(false);
    expect(modulo.trackSignup('   ')).toBe(false);
    heatmap.parar();
  });
});

describe('trackConversion', () => {
  it('emite __conversion com type e value opcional', async () => {
    const { modulo, heatmap } = await carregarSdk();

    const ok = modulo.trackConversion('trial_start', 0);
    expect(ok).toBe(true);

    const ev = pegarEvento(heatmap, '__conversion');
    expect(ev).toBeDefined();
    expect(ev.dados.propriedades).toMatchObject({ type: 'trial_start', value: 0 });
    heatmap.parar();
  });

  it('omite value quando nao fornecido', async () => {
    const { modulo, heatmap } = await carregarSdk();

    modulo.trackConversion('feature_used');

    const ev = pegarEvento(heatmap, '__conversion');
    expect(ev.dados.propriedades).toHaveProperty('type', 'feature_used');
    expect(ev.dados.propriedades).not.toHaveProperty('value');
    heatmap.parar();
  });

  it('inclui metadata sanitizada', async () => {
    const { modulo, heatmap } = await carregarSdk();

    modulo.trackConversion('upgrade', 199, { from: 'free', to: 'pro' });

    const ev = pegarEvento(heatmap, '__conversion');
    expect(ev.dados.propriedades).toMatchObject({
      type: 'upgrade',
      value: 199,
      from: 'free',
      to: 'pro',
    });
    heatmap.parar();
  });

  it('retorna false para type vazio', async () => {
    const { modulo, heatmap } = await carregarSdk();

    expect(modulo.trackConversion('')).toBe(false);
    expect(modulo.trackConversion('   ')).toBe(false);
    heatmap.parar();
  });

  it('retorna false para value nao-finito quando fornecido', async () => {
    const { modulo, heatmap } = await carregarSdk();

    expect(modulo.trackConversion('ev', NaN)).toBe(false);
    expect(modulo.trackConversion('ev', Infinity)).toBe(false);
    heatmap.parar();
  });
});
