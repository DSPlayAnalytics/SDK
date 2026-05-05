// @vitest-environment happy-dom
import { describe, expect, test, vi, beforeEach } from 'vitest';
import { attachCtaTracking, ctaFromTarget } from './tracking';

describe('ctaFromTarget()', () => {
  beforeEach(() => { document.body.innerHTML = ''; });

  test('retorna o valor de data-cta do elemento clicado', () => {
    document.body.innerHTML = '<button data-cta="hero-cadastro"></button>';
    const el = document.querySelector('button')!;
    expect(ctaFromTarget(el)).toBe('hero-cadastro');
  });

  test('retorna o data-cta do ancestral mais proximo (bubble)', () => {
    document.body.innerHTML = '<a data-cta="precos"><span><i id="filho"></i></span></a>';
    const filho = document.getElementById('filho')!;
    expect(ctaFromTarget(filho)).toBe('precos');
  });

  test('retorna null quando nao tem data-cta na hierarquia', () => {
    document.body.innerHTML = '<button id="x">Clicar</button>';
    expect(ctaFromTarget(document.getElementById('x'))).toBeNull();
  });

  test('retorna null quando target e null', () => {
    expect(ctaFromTarget(null)).toBeNull();
  });
});

describe('attachCtaTracking()', () => {
  beforeEach(() => { document.body.innerHTML = ''; });

  test('emite cta_clicado quando clicam em [data-cta]', () => {
    document.body.innerHTML = '<button data-cta="hero-cadastro"></button>';
    const emit = vi.fn();
    attachCtaTracking(document, emit);
    document.querySelector('button')!.click();
    expect(emit).toHaveBeenCalledTimes(1);
    expect(emit).toHaveBeenCalledWith(
      'cta_clicado',
      expect.objectContaining({ cta: 'hero-cadastro' }),
    );
  });

  test('inclui o path corrente no payload', () => {
    document.body.innerHTML = '<a data-cta="ver-precos"></a>';
    const emit = vi.fn();
    attachCtaTracking(document, emit);
    document.querySelector('a')!.click();
    const payload = emit.mock.calls[0][1] as Record<string, unknown>;
    expect(payload).toHaveProperty('path');
    expect(typeof payload.path).toBe('string');
  });

  test('nao emite quando clicam em elemento sem data-cta', () => {
    document.body.innerHTML = '<button id="x"></button>';
    const emit = vi.fn();
    attachCtaTracking(document, emit);
    document.getElementById('x')!.click();
    expect(emit).not.toHaveBeenCalled();
  });

  test('emite quando o click acontece num filho de [data-cta]', () => {
    document.body.innerHTML = '<a data-cta="hero-precos"><span id="t">Ver planos</span></a>';
    const emit = vi.fn();
    attachCtaTracking(document, emit);
    document.getElementById('t')!.click();
    expect(emit).toHaveBeenCalledWith(
      'cta_clicado',
      expect.objectContaining({ cta: 'hero-precos' }),
    );
  });

  test('detach remove o listener', () => {
    document.body.innerHTML = '<button data-cta="x"></button>';
    const emit = vi.fn();
    const detach = attachCtaTracking(document, emit);
    detach();
    document.querySelector('button')!.click();
    expect(emit).not.toHaveBeenCalled();
  });
});
