import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const lerCss = (caminhoRelativo: string) => {
  const absoluto = resolve(__dirname, '..', caminhoRelativo);
  return readFileSync(absoluto, 'utf-8');
};

const MIN_768 = String.raw`@media\s+(?:screen\s+and\s+)?\(min-width:\s*768px\)`;
const MIN_600 = String.raw`@media\s+(?:screen\s+and\s+)?\(min-width:\s*600px\)`;
const MIN_1024 = String.raw`@media\s+(?:screen\s+and\s+)?\(min-width:\s*1024px\)`;
const MIN_480 = String.raw`@media\s+(?:screen\s+and\s+)?\(min-width:\s*480px\)`;

describe('estilizacao mobile-first', () => {
  describe('index.css', () => {
    const css = lerCss('index.css');

    it('expoe variavel de touch target minimo de 44px', () => {
      expect(css).toMatch(/--touch-target-min:\s*44px/);
    });

    it('aplica tipografia fluida com clamp em h1, h2, h3 e body', () => {
      expect(css).toMatch(/--fluid-h1:\s*clamp\(/);
      expect(css).toMatch(/--fluid-h2:\s*clamp\(/);
      expect(css).toMatch(/--fluid-h3:\s*clamp\(/);
      expect(css).toMatch(/--fluid-body:\s*clamp\(/);
      expect(css).toMatch(/font-size:\s*var\(--fluid-h1\)/);
    });

    it('garante touch target minimo em todos os botoes', () => {
      expect(css).toMatch(/button[\s\S]{0,80}min-height:\s*var\(--touch-target-min\)/);
      expect(css).toMatch(/button[\s\S]{0,120}min-width:\s*var\(--touch-target-min\)/);
    });

    it('inclui media query mobile-first com min-width', () => {
      expect(css).toMatch(new RegExp(MIN_768));
    });

    it('aplica box-sizing border-box global', () => {
      expect(css).toMatch(/\*\s*,\s*\*::before\s*,\s*\*::after\s*\{[\s\S]*?box-sizing:\s*border-box/);
    });
  });

  describe('cards.css', () => {
    const css = lerCss('styles/cards.css');

    it('card-carousel comeca em 100% (mobile) e cresce para 70% via min-width 768px', () => {
      expect(css).toMatch(/\.card-carousel\s*\{[^}]*width:\s*100%/);
      expect(css).toMatch(new RegExp(`${MIN_768}[\\s\\S]*?\\.card-carousel[\\s\\S]*?width:\\s*70%`));
    });

    it('projects-grid escala 1col -> 2col -> auto-fit conforme breakpoints', () => {
      expect(css).toMatch(/\.projects-grid\s*\{[^}]*grid-template-columns:\s*1fr/);
      expect(css).toMatch(new RegExp(`${MIN_600}[\\s\\S]*?\\.projects-grid[\\s\\S]*?repeat\\(2,\\s*1fr\\)`));
      expect(css).toMatch(new RegExp(`${MIN_1024}[\\s\\S]*?\\.projects-grid[\\s\\S]*?minmax\\(min\\(280px,\\s*100%\\),\\s*1fr\\)`));
    });

    it('carousel-pager fica fora do card e tem botoes compactos com toque seguro', () => {
      expect(css).toMatch(/\.carousel-pager\s*\{[\s\S]*?position:\s*absolute/);
      expect(css).toMatch(/\.carousel-pager__btn\s*\{[\s\S]*?min-width:\s*32px/);
      expect(css).toMatch(/\.carousel-pager__btn\s*\{[\s\S]*?min-height:\s*32px/);
      expect(css).toMatch(/\.carousel-pager__btn:focus-visible:not\(:disabled\)[\s\S]*?box-shadow:[\s\S]*?rgba\(99,\s*102,\s*241/);
    });

    it('carousel-pager dot ativo expande e tem indicador visual diferenciado', () => {
      expect(css).toMatch(/\.carousel-pager__dot--active\s*\{[\s\S]*?width:\s*16px/);
      expect(css).toMatch(/\.carousel-pager__dot--active\s*\{[\s\S]*?background:\s*linear-gradient/);
    });

    it('carousel-pager dot tem hit area expandida via ::before sem afetar layout', () => {
      expect(css).toMatch(/\.carousel-pager__dot::before\s*\{[\s\S]*?position:\s*absolute[\s\S]*?inset:\s*-9px/);
    });

    it('page-root reserva espaco inferior para a carousel-pager e respeita safe-area iOS', () => {
      expect(css).toMatch(/\.page-root\s*\{[\s\S]*?padding:[\s\S]*?56px/);
      expect(css).toMatch(/\.page-root\s*\{[\s\S]*?safe-area-inset-bottom/);
    });

    it('project-tile substitui project-card-container com estrutura BEM', () => {
      expect(css).toMatch(/\.project-tile\s*\{[\s\S]*?perspective:\s*1000px/);
      expect(css).toMatch(/\.project-tile__face--front\s*\{[\s\S]*?background:\s*linear-gradient/);
      expect(css).toMatch(/\.project-tile__face--back\s*\{[\s\S]*?background:\s*linear-gradient/);
      expect(css).toMatch(/\.project-tile__chip\s*\{/);
      expect(css).toMatch(/\.project-tile__action--primary\s*\{/);
      expect(css).not.toMatch(/\.project-card-container\s*\{/);
    });

    it('skill-badge tem microinteracoes (hover lift, focus-visible, active press)', () => {
      expect(css).toMatch(/\.skill-badge:hover[\s\S]*?transform:[\s\S]*?translateY\(-3px\)/);
      expect(css).toMatch(/\.skill-badge:focus-visible[\s\S]*?box-shadow:[\s\S]*?rgba\(99,\s*102,\s*241/);
      expect(css).toMatch(/\.skill-badge:active[\s\S]*?transform:[\s\S]*?scale\(0\.98\)/);
    });

    it('skill-badge anima entrada com keyframes e respeita prefers-reduced-motion', () => {
      expect(css).toMatch(/@keyframes\s+skillFadeIn/);
      expect(css).toMatch(/animation:\s*skillFadeIn/);
      expect(css).toMatch(/@media\s*\(prefers-reduced-motion:\s*reduce\)/);
    });

    it('skill-badge tem touch target minimo', () => {
      expect(css).toMatch(/\.skill-badge\s*\{[\s\S]*?min-height:\s*var\(--touch-target-min\)/);
    });

    it('contact-list e tech-btn tambem tem foco visivel acessivel', () => {
      expect(css).toMatch(/\.contact-list\s+a:focus-visible[\s\S]*?box-shadow:[\s\S]*?rgba\(99,\s*102,\s*241/);
      expect(css).toMatch(/\.tech-btn:focus-visible[\s\S]*?box-shadow:[\s\S]*?rgba\(99,\s*102,\s*241/);
    });

    it('NAO contem mais a regra hostil de remocao global de padding/margin em mobile', () => {
      expect(css).not.toMatch(/\.card-carousel\s+\*\s*\{[^}]*padding:\s*0\s*!important/);
      expect(css).not.toMatch(/\.card-carousel\s+\*\s*\{[^}]*margin:\s*0\s*!important/);
    });

    it('NAO esconde icones SVG em mobile', () => {
      expect(css).not.toMatch(/\.skill-icon[\s\S]{0,500}display:\s*none\s*!important/);
    });

    it('garante que video de fundo nunca captura pointer', () => {
      expect(css).toMatch(/\.background-video[\s\S]*?pointer-events:\s*none/);
    });

    it('avatar e responsivo (96px mobile, 140px desktop)', () => {
      expect(css).toMatch(/\.avatar\s*\{[\s\S]*?width:\s*96px/);
      expect(css).toMatch(new RegExp(`${MIN_768}[\\s\\S]*?\\.avatar[\\s\\S]*?width:\\s*140px`));
    });
  });
});
