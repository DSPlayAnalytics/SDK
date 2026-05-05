import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, waitFor, act } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import EmbedWidget from '../pages/EmbedWidget';

vi.mock('react-chartjs-2', () => ({
  Bar: ({ data }) => (
    <div data-testid="bar-chart">{JSON.stringify(data.labels)}</div>
  ),
}));

function renderWidget(path) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/widget/:siteId/:graficoId" element={<EmbedWidget />} />
      </Routes>
    </MemoryRouter>
  );
}

describe('EmbedWidget', () => {
  let postMessageSpy;

  beforeEach(() => {
    globalThis.fetch = vi.fn();
    postMessageSpy = vi.fn();
    Object.defineProperty(window, 'parent', {
      configurable: true,
      get() {
        return { postMessage: postMessageSpy };
      },
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renderiza estado de carregamento inicialmente', () => {
    globalThis.fetch.mockImplementation(() => new Promise(() => {}));
    renderWidget('/widget/site-1/eventos_por_minuto?token=tok');
    expect(screen.getByRole('status')).toHaveTextContent(/carregando/i);
  });

  it('renderiza grafico quando dados chegam', async () => {
    globalThis.fetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({
        site_id: 'site-1',
        grafico_id: 'eventos_por_minuto',
        pontos: [{ page_type: 'home', totais: { visualizacoes: 42 } }],
      }),
    });
    renderWidget('/widget/site-1/eventos_por_minuto?token=tok');
    await waitFor(() => {
      expect(screen.getByTestId('bar-chart')).toBeInTheDocument();
    });
    expect(postMessageSpy).toHaveBeenCalledWith(
      expect.objectContaining({ tipo: 'embed.pronto', site_id: 'site-1' }),
      '*'
    );
  });

  it('mostra erro de token e dispara postMessage em 401', async () => {
    globalThis.fetch.mockResolvedValueOnce({ ok: false, status: 401 });
    renderWidget('/widget/site-1/eventos_por_minuto?token=expirado');
    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent(/expirada/i);
    });
    expect(postMessageSpy).toHaveBeenCalledWith(
      { tipo: 'embed.token_expirado' },
      '*'
    );
  });

  it('mostra "sem dados" quando pontos vazio', async () => {
    globalThis.fetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({ pontos: [] }),
    });
    renderWidget('/widget/site-1/eventos_por_minuto?token=tok');
    await waitFor(() => {
      expect(screen.getByRole('status')).toHaveTextContent(/sem dados/i);
    });
  });

  it('mostra erro quando token ausente na URL', async () => {
    renderWidget('/widget/site-1/eventos_por_minuto');
    await waitFor(() => {
      expect(screen.getByRole('alert')).toBeInTheDocument();
    });
    expect(globalThis.fetch).not.toHaveBeenCalled();
  });

  it('aceita postMessage embed.token_renovado e refaz fetch', async () => {
    globalThis.fetch
      .mockResolvedValueOnce({ ok: false, status: 401 })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({
          pontos: [{ page_type: 'home', totais: { visualizacoes: 7 } }],
        }),
      });
    renderWidget('/widget/site-1/eventos_por_minuto?token=expirado');
    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent(/expirada/i);
    });

    await act(async () => {
      window.dispatchEvent(
        new MessageEvent('message', {
          data: { tipo: 'embed.token_renovado', token: 'novo' },
        })
      );
    });

    await waitFor(() => {
      expect(screen.getByTestId('bar-chart')).toBeInTheDocument();
    });
  });
});
