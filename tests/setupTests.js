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
