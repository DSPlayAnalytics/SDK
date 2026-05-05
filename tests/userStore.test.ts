/**
 * Schema 1.2 (v0.4): UserStore mantem identidade persistente do usuario
 * (localStorage + fallback memoria) e fornece guard PII opcional.
 *
 * Decisoes (memoria roadmap SDK v0.4):
 *  - userId/groupId: persistem em localStorage; resetam via reset()
 *  - anonId: regenerado a cada reset(); persistente entre tabs (localStorage)
 *  - traits: NAO persistem — viajam so no envelope do __identify event
 *  - PII: regex log-only em debug; SDK nao bloqueia (cliente assina termos)
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { UserStore, criarUserStoreMemoria } from '../src/identidade/userStore';

const KEY_USER = 'analytics_sdk.user_id';
const KEY_GROUP = 'analytics_sdk.group_id';
const KEY_ANON = 'analytics_sdk.anon_id';

function limparStorage() {
  for (const k of [KEY_USER, KEY_GROUP, KEY_ANON]) localStorage.removeItem(k);
}

beforeEach(() => {
  limparStorage();
  vi.restoreAllMocks();
});

afterEach(() => {
  limparStorage();
});

describe('UserStore — anonId', () => {
  it('cria anonId no primeiro getAnonId e persiste', () => {
    const store = new UserStore();
    const a = store.getAnonId();
    const b = store.getAnonId();
    expect(a).toBe(b);
    expect(localStorage.getItem(KEY_ANON)).toBe(a);
  });

  it('reusa anonId existente em localStorage', () => {
    localStorage.setItem(KEY_ANON, 'anon-existente-123');
    const store = new UserStore();
    expect(store.getAnonId()).toBe('anon-existente-123');
  });

  it('formato uuid', () => {
    const store = new UserStore();
    const id = store.getAnonId();
    expect(id).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i);
  });
});

describe('UserStore — userId', () => {
  it('comeca como null', () => {
    const store = new UserStore();
    expect(store.getUserId()).toBeNull();
  });

  it('setUserId persiste em localStorage', () => {
    const store = new UserStore();
    store.setUserId('u-42');
    expect(store.getUserId()).toBe('u-42');
    expect(localStorage.getItem(KEY_USER)).toBe('u-42');
  });

  it('setUserId substitui valor anterior (nao mistura)', () => {
    const store = new UserStore();
    store.setUserId('u-1');
    store.setUserId('u-2');
    expect(store.getUserId()).toBe('u-2');
  });

  it('hidrata de localStorage no construtor', () => {
    localStorage.setItem(KEY_USER, 'u-pre-existente');
    const store = new UserStore();
    expect(store.getUserId()).toBe('u-pre-existente');
  });

  it('rejeita userId nao-string', () => {
    const store = new UserStore();
    store.setUserId(42);
    expect(store.getUserId()).toBeNull();
  });

  it('rejeita userId vazio ou whitespace', () => {
    const store = new UserStore();
    store.setUserId('');
    expect(store.getUserId()).toBeNull();
    store.setUserId('   ');
    expect(store.getUserId()).toBeNull();
  });
});

describe('UserStore — groupId', () => {
  it('comeca como null e persiste apos setGroupId', () => {
    const store = new UserStore();
    expect(store.getGroupId()).toBeNull();
    store.setGroupId('acme-corp');
    expect(store.getGroupId()).toBe('acme-corp');
    expect(localStorage.getItem(KEY_GROUP)).toBe('acme-corp');
  });

  it('hidrata de localStorage', () => {
    localStorage.setItem(KEY_GROUP, 'org-pre');
    const store = new UserStore();
    expect(store.getGroupId()).toBe('org-pre');
  });
});

describe('UserStore — reset', () => {
  it('reset() apaga userId e groupId', () => {
    const store = new UserStore();
    store.setUserId('u-42');
    store.setGroupId('org-z');
    store.reset();
    expect(store.getUserId()).toBeNull();
    expect(store.getGroupId()).toBeNull();
    expect(localStorage.getItem(KEY_USER)).toBeNull();
    expect(localStorage.getItem(KEY_GROUP)).toBeNull();
  });

  it('reset() gera novo anonId', () => {
    const store = new UserStore();
    const antes = store.getAnonId();
    store.reset();
    const depois = store.getAnonId();
    expect(depois).not.toBe(antes);
    expect(localStorage.getItem(KEY_ANON)).toBe(depois);
  });
});

describe('UserStore — fallback memoria sem localStorage', () => {
  it('criarUserStoreMemoria nao usa localStorage', () => {
    // Simula ambiente SSR ou storage indisponivel.
    const store = criarUserStoreMemoria();
    store.setUserId('u-mem');
    expect(store.getUserId()).toBe('u-mem');
    // Localstorage real nao deve ter sido tocado.
    expect(localStorage.getItem(KEY_USER)).toBeNull();
  });

  it('UserStore funciona quando localStorage lanca (storage cheia)', () => {
    const setItemReal = Storage.prototype.setItem;
    Storage.prototype.setItem = vi.fn(() => {
      throw new Error('QuotaExceededError');
    });
    try {
      const store = new UserStore();
      // Nao deve lancar
      store.setUserId('u-x');
      // Memoria interna mantem valor mesmo com storage falhando
      expect(store.getUserId()).toBe('u-x');
    } finally {
      Storage.prototype.setItem = setItemReal;
    }
  });
});

describe('UserStore — PII guard', () => {
  it('detectarPII retorna chaves suspeitas', () => {
    const store = new UserStore();
    const traits = {
      name: 'Alice',
      contact_email: 'alice@example.com',
      cpf: '123.456.789-00',
      phone: '+55 11 98765-4321',
      plan: 'pro',
    };
    const suspeitas = store.detectarPII(traits);
    expect(suspeitas).toContain('contact_email');
    expect(suspeitas).toContain('cpf');
    expect(suspeitas).toContain('phone');
    expect(suspeitas).not.toContain('name');
    expect(suspeitas).not.toContain('plan');
  });

  it('detectarPII retorna [] quando nao ha PII obvia', () => {
    const store = new UserStore();
    expect(store.detectarPII({ plan: 'pro', value: 99 })).toEqual([]);
    expect(store.detectarPII({})).toEqual([]);
  });

  it('detectarPII ignora valores nao-string', () => {
    const store = new UserStore();
    expect(store.detectarPII({ age: 30, active: true, meta: null })).toEqual([]);
  });
});
