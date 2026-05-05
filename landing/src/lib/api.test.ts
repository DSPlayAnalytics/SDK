import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import {
  alterarEmail, alterarSenha,
  cadastrar, confirmarRecuperarSenha, listarExports, login,
  obterConfiguracoes, solicitarMagicLink, solicitarRecuperarSenha,
  urlDashboard, urlDownloadExport,
} from './api';

const API_URL = 'https://api.dsplayground.com.br';

function fetchMock(status: number, body: unknown): typeof fetch {
  return vi.fn(async () => {
    return new Response(JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    });
  });
}

describe('cadastrar()', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', fetchMock(201, {
      status: 'success',
      user: { id: 'u1', site_id: 's1', email: 'd@x.com', papel: 'admin' },
      site: { id: 's1', slug: 'acme', nome: 'ACME', bucket_name: 'cliente_acme', plano: 'free' },
    }));
  });
  afterEach(() => vi.unstubAllGlobals());

  test('faz POST em /cliente/auth/cadastro com credentials include', async () => {
    const r = await cadastrar({
      email: 'd@x.com', senha: 'secret-123',
      nome_site: 'ACME', slug: 'acme',
    }, { apiUrl: API_URL });

    expect(r.ok).toBe(true);
    if (r.ok) expect(r.user.email).toBe('d@x.com');

    expect(fetch).toHaveBeenCalledWith(
      `${API_URL}/cliente/auth/cadastro`,
      expect.objectContaining({
        method: 'POST',
        credentials: 'include',
        headers: expect.objectContaining({ 'Content-Type': 'application/json' }),
        body: JSON.stringify({
          email: 'd@x.com', senha: 'secret-123',
          nome_site: 'ACME', slug: 'acme',
        }),
      }),
    );
  });

  test('mapeia 409 EMAIL_JA_CADASTRADO em ErrorResult tipado', async () => {
    vi.stubGlobal('fetch', fetchMock(409, {
      status: 'error', code: 'EMAIL_JA_CADASTRADO', message: 'email ja existe',
    }));

    const r = await cadastrar({
      email: 'd@x.com', senha: 'secret-123',
      nome_site: 'ACME', slug: 'acme',
    }, { apiUrl: API_URL });

    expect(r.ok).toBe(false);
    if (!r.ok) {
      expect(r.code).toBe('EMAIL_JA_CADASTRADO');
      expect(r.status).toBe(409);
    }
  });

  test('400 SLUG_INVALIDO retorna code do backend', async () => {
    vi.stubGlobal('fetch', fetchMock(400, {
      status: 'error', code: 'SLUG_INVALIDO', message: 'slug invalido',
    }));
    const r = await cadastrar({
      email: 'd@x.com', senha: 'secret-123',
      nome_site: 'ACME', slug: 'AC',
    }, { apiUrl: API_URL });
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.code).toBe('SLUG_INVALIDO');
  });

  test('falha de rede retorna code REDE', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('network'); }));
    const r = await cadastrar({
      email: 'd@x.com', senha: 'secret-123',
      nome_site: 'ACME', slug: 'acme',
    }, { apiUrl: API_URL });
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.code).toBe('REDE');
  });
});

describe('login()', () => {
  afterEach(() => vi.unstubAllGlobals());

  test('faz POST em /cliente/auth/login com credentials include', async () => {
    vi.stubGlobal('fetch', fetchMock(200, {
      status: 'success',
      user: { id: 'u1', site_id: 's1', email: 'd@x.com', papel: 'admin' },
    }));
    const r = await login({ email: 'd@x.com', senha: 'secret-123' }, { apiUrl: API_URL });
    expect(r.ok).toBe(true);
    expect(fetch).toHaveBeenCalledWith(
      `${API_URL}/cliente/auth/login`,
      expect.objectContaining({ method: 'POST', credentials: 'include' }),
    );
  });

  test('401 retorna code CREDENCIAIS_INVALIDAS', async () => {
    vi.stubGlobal('fetch', fetchMock(401, {
      status: 'error', code: 'CREDENCIAIS_INVALIDAS', message: 'email ou senha incorretos',
    }));
    const r = await login({ email: 'd@x.com', senha: 'errada' }, { apiUrl: API_URL });
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.code).toBe('CREDENCIAIS_INVALIDAS');
  });
});


describe('urlDashboard()', () => {
  const DASH = 'https://app.dsplayground.com.br/cliente/metricas';

  test('sem query devolve a URL base inalterada', () => {
    expect(urlDashboard(DASH)).toBe(DASH);
  });

  test('com query vazia devolve a URL base inalterada', () => {
    expect(urlDashboard(DASH, {})).toBe(DASH);
  });

  test('adiciona query string com ? quando URL nao tem', () => {
    expect(urlDashboard(DASH, { welcome: 'true' })).toBe(`${DASH}?welcome=true`);
  });

  test('usa & quando URL ja tem query', () => {
    const url = `${DASH}?ref=signup`;
    expect(urlDashboard(url, { plano: 'free' })).toBe(`${url}&plano=free`);
  });

  test('escapa valores com URL-encode', () => {
    const out = urlDashboard(DASH, { ref: 'a b c' });
    expect(out).toContain('ref=a+b+c');
  });
});

describe('listarExports()', () => {
  afterEach(() => vi.unstubAllGlobals());

  test('GET /cliente/exportar com cookie e retorna lista de dias', async () => {
    vi.stubGlobal('fetch', fetchMock(200, {
      arquivos: [
        { dia: '2026-04-30', key: 'acme/2026/04/30.lp.gz' },
        { dia: '2026-05-01', key: 'acme/2026/05/01.lp.gz' },
      ],
    }));

    const r = await listarExports({ apiUrl: API_URL });

    expect(r.ok).toBe(true);
    if (r.ok) {
      expect(r.arquivos).toHaveLength(2);
      expect(r.arquivos[0].dia).toBe('2026-04-30');
    }
    expect(fetch).toHaveBeenCalledWith(
      `${API_URL}/cliente/exportar`,
      expect.objectContaining({
        method: 'GET',
        credentials: 'include',
      }),
    );
  });

  test('mapeia 401 em NAO_AUTENTICADO', async () => {
    vi.stubGlobal('fetch', fetchMock(401, ''));
    const r = await listarExports({ apiUrl: API_URL });
    expect(r.ok).toBe(false);
    if (!r.ok) {
      expect(r.code).toBe('NAO_AUTENTICADO');
      expect(r.status).toBe(401);
    }
  });

  test('mapeia falha de rede em REDE', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('offline'); }));
    const r = await listarExports({ apiUrl: API_URL });
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.code).toBe('REDE');
  });

  test('arquivos lista vazia quando bucket nao tem nada', async () => {
    vi.stubGlobal('fetch', fetchMock(200, { arquivos: [] }));
    const r = await listarExports({ apiUrl: API_URL });
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.arquivos).toEqual([]);
  });
});

describe('urlDownloadExport()', () => {
  test('constroi URL absoluta para dia ISO', () => {
    expect(urlDownloadExport(API_URL, '2026-04-30'))
      .toBe(`${API_URL}/cliente/exportar/2026-04-30`);
  });

  test('rejeita dia mal formado', () => {
    expect(() => urlDownloadExport(API_URL, 'abc')).toThrow(/dia/i);
    expect(() => urlDownloadExport(API_URL, '2026/04/30')).toThrow(/dia/i);
  });
});

describe('obterConfiguracoes()', () => {
  afterEach(() => vi.unstubAllGlobals());

  test('GET /cliente/auth/configuracoes retorna shape completo', async () => {
    vi.stubGlobal('fetch', fetchMock(200, {
      user: { id: 'u1', email: 'd@x.com', papel: 'admin' },
      site: { id: 's1', slug: 'acme', nome: 'ACME', ambiente: 'production',
              plano: 'medio', bucket_name: 'cliente_acme' },
      publishable_keys: [
        { key_id: 'k1', valor: 'pk_production_abc', nome: 'principal',
          ambiente: 'production' },
      ],
      quota: { eventos_por_minuto: 5000, eventos_por_dia: 1_000_000,
               emissoes_jwt_por_minuto: 5, retencao_dias: 90 },
      consumo: { eventos_hoje: 42 },
      cardinalidade: { atual: 1234, limite: 50_000 },
    }));

    const r = await obterConfiguracoes({ apiUrl: API_URL });

    expect(r.ok).toBe(true);
    if (r.ok) {
      expect(r.user.email).toBe('d@x.com');
      expect(r.site.slug).toBe('acme');
      expect(r.publishable_keys).toHaveLength(1);
      expect(r.publishable_keys[0].valor).toBe('pk_production_abc');
      expect(r.quota.retencao_dias).toBe(90);
      expect(r.consumo.eventos_hoje).toBe(42);
      expect(r.cardinalidade.atual).toBe(1234);
      expect(r.cardinalidade.limite).toBe(50_000);
    }
    expect(fetch).toHaveBeenCalledWith(
      `${API_URL}/cliente/auth/configuracoes`,
      expect.objectContaining({ method: 'GET', credentials: 'include' }),
    );
  });

  test('mapeia 401 em NAO_AUTENTICADO', async () => {
    vi.stubGlobal('fetch', fetchMock(401, ''));
    const r = await obterConfiguracoes({ apiUrl: API_URL });
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.code).toBe('NAO_AUTENTICADO');
  });
});

describe('solicitarMagicLink()', () => {
  afterEach(() => vi.unstubAllGlobals());

  test('POST /cliente/auth/magic-link/solicitar com email retorna ok', async () => {
    vi.stubGlobal('fetch', fetchMock(200, { status: 'success', ok: true }));

    const r = await solicitarMagicLink({ email: 'd@x.com' }, { apiUrl: API_URL });

    expect(r.ok).toBe(true);
    expect(fetch).toHaveBeenCalledWith(
      `${API_URL}/cliente/auth/magic-link/solicitar`,
      expect.objectContaining({
        method: 'POST',
        credentials: 'include',
        body: JSON.stringify({ email: 'd@x.com' }),
      }),
    );
  });

  test('200 mesmo pra email-fantasma (anti-enum) — caller nao distingue', async () => {
    vi.stubGlobal('fetch', fetchMock(200, { status: 'success', ok: true }));
    const r = await solicitarMagicLink({ email: 'nao-existe@x.com' }, { apiUrl: API_URL });
    expect(r.ok).toBe(true);
  });

  test('429 vira RATE_LIMIT_EXCEDIDO', async () => {
    vi.stubGlobal('fetch', fetchMock(429, {
      status: 'error', code: 'RATE_LIMIT_EXCEDIDO',
      message: 'muitas solicitacoes — tente novamente em 15min',
    }));
    const r = await solicitarMagicLink({ email: 'd@x.com' }, { apiUrl: API_URL });
    expect(r.ok).toBe(false);
    if (!r.ok) {
      expect(r.code).toBe('RATE_LIMIT_EXCEDIDO');
      expect(r.status).toBe(429);
    }
  });

  test('falha de rede vira REDE', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('offline'); }));
    const r = await solicitarMagicLink({ email: 'd@x.com' }, { apiUrl: API_URL });
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.code).toBe('REDE');
  });
});

describe('solicitarRecuperarSenha()', () => {
  afterEach(() => vi.unstubAllGlobals());

  test('POST /cliente/auth/recuperar-senha/solicitar retorna ok', async () => {
    vi.stubGlobal('fetch', fetchMock(200, { status: 'success', ok: true }));

    const r = await solicitarRecuperarSenha({ email: 'd@x.com' }, { apiUrl: API_URL });

    expect(r.ok).toBe(true);
    expect(fetch).toHaveBeenCalledWith(
      `${API_URL}/cliente/auth/recuperar-senha/solicitar`,
      expect.objectContaining({
        method: 'POST',
        credentials: 'include',
        body: JSON.stringify({ email: 'd@x.com' }),
      }),
    );
  });

  test('200 mesmo pra email-fantasma (anti-enum)', async () => {
    vi.stubGlobal('fetch', fetchMock(200, { status: 'success', ok: true }));
    const r = await solicitarRecuperarSenha({ email: 'fantasma@x.com' }, { apiUrl: API_URL });
    expect(r.ok).toBe(true);
  });

  test('429 vira RATE_LIMIT_EXCEDIDO', async () => {
    vi.stubGlobal('fetch', fetchMock(429, {
      status: 'error', code: 'RATE_LIMIT_EXCEDIDO',
      message: 'muitas solicitacoes — tente novamente em 15min',
    }));
    const r = await solicitarRecuperarSenha({ email: 'd@x.com' }, { apiUrl: API_URL });
    expect(r.ok).toBe(false);
    if (!r.ok) {
      expect(r.code).toBe('RATE_LIMIT_EXCEDIDO');
      expect(r.status).toBe(429);
    }
  });

  test('falha de rede vira REDE', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('offline'); }));
    const r = await solicitarRecuperarSenha({ email: 'd@x.com' }, { apiUrl: API_URL });
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.code).toBe('REDE');
  });
});

describe('confirmarRecuperarSenha()', () => {
  afterEach(() => vi.unstubAllGlobals());

  test('POST /cliente/auth/recuperar-senha/confirmar com token válido retorna user', async () => {
    vi.stubGlobal('fetch', fetchMock(200, {
      status: 'success',
      user: { id: 'u1', site_id: 's1', email: 'd@x.com', papel: 'admin' },
    }));

    const r = await confirmarRecuperarSenha(
      { token: 'tok_abc123', nova_senha: 'nova-senha-123' },
      { apiUrl: API_URL },
    );

    expect(r.ok).toBe(true);
    if (r.ok) expect(r.user.email).toBe('d@x.com');
    expect(fetch).toHaveBeenCalledWith(
      `${API_URL}/cliente/auth/recuperar-senha/confirmar`,
      expect.objectContaining({
        method: 'POST',
        credentials: 'include',
        body: JSON.stringify({ token: 'tok_abc123', nova_senha: 'nova-senha-123' }),
      }),
    );
  });

  test('400 TOKEN_INVALIDO (expirado ou já usado)', async () => {
    vi.stubGlobal('fetch', fetchMock(400, {
      status: 'error', code: 'TOKEN_INVALIDO',
      message: 'link expirado, ja utilizado ou senha muito curta',
    }));
    const r = await confirmarRecuperarSenha(
      { token: 'tok_expirado', nova_senha: 'senha-123' },
      { apiUrl: API_URL },
    );
    expect(r.ok).toBe(false);
    if (!r.ok) {
      expect(r.code).toBe('TOKEN_INVALIDO');
      expect(r.status).toBe(400);
    }
  });

  test('400 SENHA_CURTA', async () => {
    vi.stubGlobal('fetch', fetchMock(400, {
      status: 'error', code: 'SENHA_CURTA',
      message: 'nova_senha precisa ter pelo menos 8 caracteres',
    }));
    const r = await confirmarRecuperarSenha(
      { token: 'tok_ok', nova_senha: 'abc' },
      { apiUrl: API_URL },
    );
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.code).toBe('SENHA_CURTA');
  });

  test('falha de rede vira REDE', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('offline'); }));
    const r = await confirmarRecuperarSenha(
      { token: 'tok_ok', nova_senha: 'senha-valida-123' },
      { apiUrl: API_URL },
    );
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.code).toBe('REDE');
  });
});

describe('alterarSenha()', () => {
  afterEach(() => vi.unstubAllGlobals());

  test('PATCH /cliente/auth/senha com senha correta retorna ok', async () => {
    vi.stubGlobal('fetch', fetchMock(200, { status: 'success', ok: true }));
    const r = await alterarSenha(
      { senha_atual: 'old-secret', nova_senha: 'new-secret-123' },
      { apiUrl: API_URL },
    );
    expect(r.ok).toBe(true);
    expect(fetch).toHaveBeenCalledWith(
      `${API_URL}/cliente/auth/senha`,
      expect.objectContaining({ method: 'PATCH', credentials: 'include' }),
    );
  });

  test('403 SENHA_INVALIDA', async () => {
    vi.stubGlobal('fetch', fetchMock(403, {
      status: 'error', code: 'SENHA_INVALIDA', message: 'senha atual incorreta',
    }));
    const r = await alterarSenha(
      { senha_atual: 'errada', nova_senha: 'new12345' }, { apiUrl: API_URL },
    );
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.code).toBe('SENHA_INVALIDA');
  });

  test('400 SENHA_CURTA', async () => {
    vi.stubGlobal('fetch', fetchMock(400, {
      status: 'error', code: 'SENHA_CURTA', message: 'minimo 8',
    }));
    const r = await alterarSenha(
      { senha_atual: 'old', nova_senha: 'abc' }, { apiUrl: API_URL },
    );
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.code).toBe('SENHA_CURTA');
  });

  test('401 NAO_AUTENTICADO', async () => {
    vi.stubGlobal('fetch', fetchMock(401, {}));
    const r = await alterarSenha(
      { senha_atual: 'a', nova_senha: 'b12345678' }, { apiUrl: API_URL },
    );
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.code).toBe('NAO_AUTENTICADO');
  });
});

describe('alterarEmail()', () => {
  afterEach(() => vi.unstubAllGlobals());

  test('PATCH /cliente/auth/email com senha correta retorna ok', async () => {
    vi.stubGlobal('fetch', fetchMock(200, { status: 'success', ok: true }));
    const r = await alterarEmail(
      { senha_atual: 'secret', novo_email: 'novo@x.com' }, { apiUrl: API_URL },
    );
    expect(r.ok).toBe(true);
  });

  test('409 EMAIL_JA_CADASTRADO', async () => {
    vi.stubGlobal('fetch', fetchMock(409, {
      status: 'error', code: 'EMAIL_JA_CADASTRADO',
    }));
    const r = await alterarEmail(
      { senha_atual: 'secret', novo_email: 'tomado@x.com' }, { apiUrl: API_URL },
    );
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.code).toBe('EMAIL_JA_CADASTRADO');
  });

  test('400 EMAIL_INVALIDO', async () => {
    vi.stubGlobal('fetch', fetchMock(400, {
      status: 'error', code: 'EMAIL_INVALIDO',
    }));
    const r = await alterarEmail(
      { senha_atual: 'secret', novo_email: 'sem-arroba' }, { apiUrl: API_URL },
    );
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.code).toBe('EMAIL_INVALIDO');
  });
});
