import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import Projects from '../pages/Projects';

afterEach(() => {
  cleanup();
});

describe('pagina Projects (mobile-first)', () => {
  it('renderiza com a classe page-root para layout responsivo', () => {
    const { container } = render(<Projects />);
    expect(container.querySelector('.page-root')).not.toBeNull();
  });

  it('lista de projetos usa classe projects-grid (sem styles inline de coluna fixa)', () => {
    render(<Projects />);
    const lista = screen.getByText('Projetos').closest('#projects_card')?.querySelector('#projects_list');
    expect(lista).not.toBeNull();
    expect(lista?.classList.contains('projects-grid')).toBe(true);
    const inline = lista?.getAttribute('style') ?? '';
    expect(inline).not.toMatch(/grid-template-columns/i);
    expect(inline).not.toMatch(/minmax\(400px/i);
  });

  it('cards de projeto sao renderizados como project-tile acessiveis por teclado', () => {
    const { container } = render(<Projects />);
    const tiles = container.querySelectorAll('.project-tile');
    expect(tiles.length).toBeGreaterThan(0);
    tiles.forEach((tile) => {
      expect(tile.getAttribute('role')).toBe('button');
      expect(tile.getAttribute('tabIndex')).toBe('0');
      expect(tile.getAttribute('aria-pressed')).toBe('false');
      expect(tile.getAttribute('aria-label')).toBeTruthy();
    });
  });

  it('cards de projeto alternam aria-pressed ao acionar via Enter', () => {
    const { container } = render(<Projects />);
    const tile = container.querySelector('.project-tile');
    if (!tile) throw new Error('project-tile nao encontrado');
    expect(tile.getAttribute('aria-pressed')).toBe('false');
    fireEvent.keyDown(tile, { key: 'Enter' });
    expect(tile.getAttribute('aria-pressed')).toBe('true');
  });

  it('cards expoem estrutura semantica BEM (face front/back, header, chips, actions)', () => {
    const { container } = render(<Projects />);
    expect(container.querySelector('.project-tile__face--front')).not.toBeNull();
    expect(container.querySelector('.project-tile__face--back')).not.toBeNull();
    expect(container.querySelector('.project-tile__header')).not.toBeNull();
    expect(container.querySelector('.project-tile__chips')).not.toBeNull();
    expect(container.querySelector('.project-tile__actions')).not.toBeNull();
  });

  it('chips de tecnologia nao usam mais styles inline gigantes', () => {
    const { container } = render(<Projects />);
    const chips = container.querySelectorAll('.project-tile__chip');
    expect(chips.length).toBeGreaterThan(0);
    chips.forEach((chip) => {
      const style = chip.getAttribute('style') ?? '';
      expect(style).not.toMatch(/padding:\s*12px\s*16px/i);
      expect(style).not.toMatch(/background-?color:/i);
    });
  });

  it('botoes de acao no verso usam classes em vez de styles inline', () => {
    const { container } = render(<Projects />);
    const acoes = container.querySelectorAll('.project-tile__action');
    expect(acoes.length).toBeGreaterThan(0);
    acoes.forEach((btn) => {
      const style = btn.getAttribute('style') ?? '';
      expect(style).not.toMatch(/background-?color:/i);
      expect(btn.getAttribute('type')).toBe('button');
    });
  });
});
