import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import ClienteLogin from '../pages/ClienteLogin';

function renderLogin(initialPath = '/cliente/login') {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <ClienteLogin />
    </MemoryRouter>
  );
}

describe('ClienteLogin', () => {
  beforeEach(() => {
    globalThis.fetch = vi.fn();
  });

  it('renderiza as duas tabs com magic-link como default', () => {
    renderLogin();
    const tabs = screen.getAllByRole('tab');
    expect(tabs).toHaveLength(2);
    expect(tabs[0]).toHaveAttribute('aria-selected', 'true');
    expect(tabs[0]).toHaveTextContent(/link por e-mail/i);
    expect(tabs[1]).toHaveTextContent(/senha/i);
  });

  it('alterna pra tab de senha e mostra o campo de senha', () => {
    renderLogin();
    fireEvent.click(screen.getByRole('tab', { name: /senha/i }));
    expect(screen.getByLabelText(/senha/i, { selector: 'input' })).toBeInTheDocument();
  });

  it('botao submit fica desabilitado sem email', () => {
    renderLogin();
    const btn = screen.getByRole('button', { name: /receber link/i });
    expect(btn).toBeDisabled();
  });

  it('mostra mensagem de sucesso ao enviar magic-link', async () => {
    globalThis.fetch.mockResolvedValueOnce({
      ok: true, status: 200, json: async () => ({ ok: true }),
    });
    renderLogin();
    fireEvent.change(screen.getByLabelText(/e-mail/i), {
      target: { value: 'dan@acme.test' },
    });
    fireEvent.click(screen.getByRole('button', { name: /receber link/i }));
    await waitFor(() => {
      expect(screen.getByRole('status')).toHaveTextContent(/verifique sua caixa/i);
    });
    expect(globalThis.fetch).toHaveBeenCalledWith(
      expect.stringContaining('/cliente/auth/magic-link/solicitar'),
      expect.objectContaining({ credentials: 'include', method: 'POST' }),
    );
  });

  it('mostra erro 429 ao estourar rate-limit', async () => {
    globalThis.fetch.mockResolvedValueOnce({ ok: false, status: 429, json: async () => ({}) });
    renderLogin();
    fireEvent.change(screen.getByLabelText(/e-mail/i), {
      target: { value: 'dan@acme.test' },
    });
    fireEvent.click(screen.getByRole('button', { name: /receber link/i }));
    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent(/15 minutos/i);
    });
  });

  it('mostra erro 401 ao login com senha incorreta', async () => {
    globalThis.fetch.mockResolvedValueOnce({
      ok: false, status: 401, json: async () => ({ code: 'CREDENCIAIS_INVALIDAS' }),
    });
    renderLogin();
    fireEvent.click(screen.getByRole('tab', { name: /senha/i }));
    fireEvent.change(screen.getByLabelText(/e-mail/i), { target: { value: 'x@y.com' } });
    fireEvent.change(screen.getByLabelText(/senha/i, { selector: 'input' }), {
      target: { value: 'errada' },
    });
    fireEvent.click(screen.getByRole('button', { name: /^entrar$/i }));
    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent(/incorretos/i);
    });
  });

  it('mostra mensagem de link expirado quando ?expirado=1 esta na URL', () => {
    renderLogin('/cliente/login?expirado=1');
    expect(screen.getByRole('alert')).toHaveTextContent(/expirou|ja foi utilizado/i);
  });
});
