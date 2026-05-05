/**
 * @vitest-environment happy-dom
 */
import { describe, expect, test, vi } from 'vitest';
import { aplicarEstadoLogado, criarFetcherMe } from './nav-auth';

function montarNav(): Document {
  document.body.innerHTML = `
    <header>
      <div id="nav-deslogado" class="hidden">
        <a href="/cliente/login">Entrar</a>
        <a href="/cliente/cadastro">Criar conta</a>
      </div>
      <div id="nav-logado" class="hidden">
        <a href="https://app.dsplayground.com.br">Painel</a>
        <a href="/cliente/configuracoes">Configurações</a>
        <button id="logout">Sair</button>
      </div>
    </header>
  `;
  return document;
}

describe('aplicarEstadoLogado', () => {
  test('logado: mostra nav-logado e esconde nav-deslogado', async () => {
    const doc = montarNav();
    const fetcher = vi.fn().mockResolvedValue({
      ok: true,
      user: { user_id: 'u1', site_id: 's1', email: 'd@x.com', papel: 'admin' },
    });

    const r = await aplicarEstadoLogado(fetcher, doc);

    expect(r.logado).toBe(true);
    expect(doc.getElementById('nav-logado')!.classList.contains('hidden')).toBe(false);
    expect(doc.getElementById('nav-deslogado')!.classList.contains('hidden')).toBe(true);
  });

  test('deslogado: mostra nav-deslogado', async () => {
    const doc = montarNav();
    const fetcher = vi.fn().mockResolvedValue({ ok: false, status: 401 });

    const r = await aplicarEstadoLogado(fetcher, doc);

    expect(r.logado).toBe(false);
    expect(doc.getElementById('nav-deslogado')!.classList.contains('hidden')).toBe(false);
    expect(doc.getElementById('nav-logado')!.classList.contains('hidden')).toBe(true);
  });

  test('falha de rede assume deslogado (preserva visitante)', async () => {
    const doc = montarNav();
    const fetcher = vi.fn().mockResolvedValue({ ok: false, status: 0 });

    const r = await aplicarEstadoLogado(fetcher, doc);

    expect(r.logado).toBe(false);
    expect(doc.getElementById('nav-deslogado')!.classList.contains('hidden')).toBe(false);
  });

  test('sem elementos no DOM retorna deslogado sem erro', async () => {
    document.body.innerHTML = '';
    const fetcher = vi.fn();
    const r = await aplicarEstadoLogado(fetcher, document);
    expect(r.logado).toBe(false);
    expect(fetcher).not.toHaveBeenCalled();
  });

  test('500 do backend trata como deslogado (defensivo)', async () => {
    const doc = montarNav();
    const fetcher = vi.fn().mockResolvedValue({ ok: false, status: 500 });

    const r = await aplicarEstadoLogado(fetcher, doc);

    expect(r.logado).toBe(false);
  });
});

describe('criarFetcherMe', () => {
  test('faz GET /cliente/auth/me com credentials include', async () => {
    const stub = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ user_id: 'u', site_id: 's', email: 'x', papel: 'admin' }),
    });
    const f = criarFetcherMe('https://api.test', stub as any);

    const r = await f();

    expect(r.ok).toBe(true);
    expect(stub).toHaveBeenCalledWith(
      'https://api.test/cliente/auth/me',
      expect.objectContaining({ method: 'GET', credentials: 'include' }),
    );
  });

  test('401 vira { ok: false, status: 401 }', async () => {
    const stub = vi.fn().mockResolvedValue({ ok: false, status: 401 });
    const f = criarFetcherMe('https://api.test', stub as any);
    const r = await f();
    expect(r).toEqual({ ok: false, status: 401 });
  });

  test('rede joga sequer chega no json — mapeia status 0', async () => {
    const stub = vi.fn().mockRejectedValue(new Error('network down'));
    const f = criarFetcherMe('https://api.test', stub as any);
    const r = await f();
    expect(r).toEqual({ ok: false, status: 0 });
  });
});
