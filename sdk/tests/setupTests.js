import '@testing-library/jest-dom/vitest';
import { vi } from 'vitest';

class IntersectionObserverMock {
  constructor(callback) {
    this.callback = callback;
  }

  observe() {}
  unobserve() {}
  disconnect() {}
  takeRecords() { return []; }
}

vi.stubGlobal('IntersectionObserver', IntersectionObserverMock);

// jsdom 26 + vitest expoe `localStorage` como objeto sem metodos Storage —
// polyfill minimal compativel com `Storage` interface. Evita pular testes
// que usam localStorage real (FilaAnalytics, UserStore).
class StoragePolyfill {
  constructor() {
    this._mapa = new Map();
  }
  get length() { return this._mapa.size; }
  key(i) { return Array.from(this._mapa.keys())[i] ?? null; }
  getItem(k) { return this._mapa.has(k) ? this._mapa.get(k) : null; }
  setItem(k, v) { this._mapa.set(String(k), String(v)); }
  removeItem(k) { this._mapa.delete(String(k)); }
  clear() { this._mapa.clear(); }
}

if (typeof globalThis.localStorage !== 'object'
    || typeof globalThis.localStorage?.setItem !== 'function') {
  vi.stubGlobal('localStorage', new StoragePolyfill());
}
if (typeof globalThis.sessionStorage !== 'object'
    || typeof globalThis.sessionStorage?.setItem !== 'function') {
  vi.stubGlobal('sessionStorage', new StoragePolyfill());
}
