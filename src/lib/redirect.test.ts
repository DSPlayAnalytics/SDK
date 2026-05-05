import { describe, expect, test } from 'vitest';
import { resolverDestinoPosLogin } from './redirect';

const FALLBACK = 'https://app.dsplayground.com.br/cliente/metricas';

function qs(s: string): URLSearchParams {
  return new URL('https://x/?' + s).searchParams;
}

describe('resolverDestinoPosLogin', () => {
  test('sem next retorna fallback', () => {
    expect(resolverDestinoPosLogin(qs(''), FALLBACK)).toBe(FALLBACK);
  });

  test('next path-only valido em /cliente/* eh aceito', () => {
    expect(resolverDestinoPosLogin(qs('next=/cliente/configuracoes'), FALLBACK))
      .toBe('/cliente/configuracoes');
    expect(resolverDestinoPosLogin(qs('next=/cliente/exportar'), FALLBACK))
      .toBe('/cliente/exportar');
  });

  test('next absoluto bloqueado (open-redirect)', () => {
    expect(resolverDestinoPosLogin(qs('next=https://evil.com/login'), FALLBACK))
      .toBe(FALLBACK);
    expect(resolverDestinoPosLogin(qs('next=http://evil'), FALLBACK))
      .toBe(FALLBACK);
  });

  test('next protocolo-relativo bloqueado (//evil)', () => {
    expect(resolverDestinoPosLogin(qs('next=//evil.com/x'), FALLBACK))
      .toBe(FALLBACK);
  });

  test('next path mas fora de /cliente/ bloqueado', () => {
    expect(resolverDestinoPosLogin(qs('next=/admin'), FALLBACK)).toBe(FALLBACK);
    expect(resolverDestinoPosLogin(qs('next=/cliente'), FALLBACK)).toBe(FALLBACK);
    expect(resolverDestinoPosLogin(qs('next=/'), FALLBACK)).toBe(FALLBACK);
  });

  test('next com @ (url userinfo trick) bloqueado', () => {
    expect(resolverDestinoPosLogin(qs('next=/cliente/x@evil.com/'), FALLBACK))
      .toBe(FALLBACK);
  });

  test('next com backslash-tricks bloqueado', () => {
    expect(resolverDestinoPosLogin(qs('next=/\\evil.com'), FALLBACK))
      .toBe(FALLBACK);
  });

  // Fluxo de cadastro: usa o mesmo helper. fallback e' DASHBOARD_URL com
  // ?welcome=true (cadastro mostra onboarding). Quando next valido vem
  // junto, ele tem precedencia (cliente queria ir pra outro lugar).
  describe('fluxo de cadastro', () => {
    const FALLBACK_CADASTRO = 'https://app.dsplayground.com.br/cliente/metricas?welcome=true';

    test('next /cliente/* valido tem precedencia sobre fallback com welcome', () => {
      expect(resolverDestinoPosLogin(qs('next=/cliente/configuracoes'), FALLBACK_CADASTRO))
        .toBe('/cliente/configuracoes');
    });

    test('sem next, cai no fallback com welcome', () => {
      expect(resolverDestinoPosLogin(qs(''), FALLBACK_CADASTRO))
        .toBe(FALLBACK_CADASTRO);
    });

    test('cadastro com plano + next: next ainda ganha (next nao se mistura com plano)', () => {
      // ?plano=pro e' usado pra mostrar banner; nao afeta destino pos-cadastro
      expect(resolverDestinoPosLogin(qs('plano=pro&next=/cliente/exportar'), FALLBACK_CADASTRO))
        .toBe('/cliente/exportar');
    });
  });
});
