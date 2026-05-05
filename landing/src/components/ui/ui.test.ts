/**
 * TDD do mini design system. Renderiza cada component via
 * experimental_AstroContainer e valida atributos chave (a11y, classes,
 * estado).
 *
 * Foco aqui nao e visual regression — e' contrato API + a11y. Visual
 * fica pro `astro check` + dogfood manual no browser.
 */
import { experimental_AstroContainer as AstroContainer } from 'astro/container';
import { describe, expect, test } from 'vitest';

import Badge from './Badge.astro';
import Breadcrumbs from './Breadcrumbs.astro';
import Button from './Button.astro';
import Card from './Card.astro';
import ChartCard from './ChartCard.astro';
import EmptyState from './EmptyState.astro';
import FormError from './FormError.astro';
import Input from './Input.astro';
import MetricCard from './MetricCard.astro';
import Section from './Section.astro';
import Stepper from './Stepper.astro';
import Tabs from './Tabs.astro';
import ToastContainer from './ToastContainer.astro';

async function render(component: any, props: Record<string, unknown> = {}, slots?: Record<string, string>) {
  const container = await AstroContainer.create();
  return container.renderToString(component, { props, slots });
}

describe('Button', () => {
  test('renderiza <button> por default com variant primary', async () => {
    const html = await render(Button, {}, { default: 'Entrar' });
    expect(html).toMatch(/<button[^>]*type="button"/);
    expect(html).toContain('btn-primary');
    expect(html).toContain('Entrar');
  });

  test('renderiza <a> quando href passado', async () => {
    const html = await render(Button, { href: '/cadastro', variant: 'secondary' }, { default: 'Criar conta' });
    expect(html).toMatch(/<a[^>]*href="\/cadastro"/);
    expect(html).toContain('btn-secondary');
    // Nao deve ter <button>
    expect(html).not.toMatch(/<button/);
  });

  test('type submit muda atributo', async () => {
    const html = await render(Button, { type: 'submit' }, { default: 'OK' });
    expect(html).toMatch(/type="submit"/);
  });

  test('disabled aplica atributo', async () => {
    const html = await render(Button, { disabled: true }, { default: 'OK' });
    expect(html).toContain('disabled');
  });

  test('data-cta passa pro elemento (rastreamento)', async () => {
    const html = await render(Button, { 'data-cta': 'hero-cadastro' }, { default: 'Criar' });
    expect(html).toContain('data-cta="hero-cadastro"');
  });

  test('size sm aplica classes menores', async () => {
    const html = await render(Button, { size: 'sm' }, { default: 'X' });
    expect(html).toContain('text-xs');
  });

  test('fullWidth adiciona w-full', async () => {
    const html = await render(Button, { fullWidth: true }, { default: 'X' });
    expect(html).toContain('w-full');
  });

  test('variant ghost usa estilo neutro', async () => {
    const html = await render(Button, { variant: 'ghost' }, { default: 'X' });
    expect(html).not.toContain('btn-primary');
    expect(html).not.toContain('btn-secondary');
    expect(html).toContain('text-slate-300');
  });
});

describe('Card', () => {
  test('renderiza <article> por default', async () => {
    const html = await render(Card, {}, { default: '<p>conteudo</p>' });
    expect(html).toMatch(/^<article/);
    expect(html).toContain('rounded-xl');
    expect(html).toContain('border-slate-800');
  });

  test('accent aplica borda brand', async () => {
    const html = await render(Card, { accent: true }, { default: 'x' });
    expect(html).toContain('border-brand-400');
    expect(html).toContain('ring-brand-500/40');
  });

  test('padding tight reduz', async () => {
    const html = await render(Card, { padding: 'tight' }, { default: 'x' });
    expect(html).toContain('p-4');
    expect(html).not.toMatch(/\bp-6\b/);
  });

  test('as="li" muda tag', async () => {
    const html = await render(Card, { as: 'li' }, { default: 'x' });
    expect(html).toMatch(/^<li/);
  });
});

describe('Input', () => {
  test('label associada via for/id (a11y obrigatorio)', async () => {
    const html = await render(Input, { id: 'email', label: 'Email' });
    expect(html).toMatch(/<label[^>]*for="email"/);
    expect(html).toMatch(/<input[^>]*id="email"/);
  });

  test('name herda do id quando nao passado', async () => {
    const html = await render(Input, { id: 'senha', label: 'Senha' });
    expect(html).toContain('name="senha"');
  });

  test('hint vira <p> com aria-describedby', async () => {
    const html = await render(Input, {
      id: 'slug',
      label: 'Apelido',
      hint: 'Use letras minusculas',
    });
    expect(html).toContain('aria-describedby="slug-hint"');
    expect(html).toMatch(/<p[^>]*id="slug-hint"[^>]*>Use letras minusculas/);
  });

  test('required, type, autocomplete passam pro <input>', async () => {
    const html = await render(Input, {
      id: 'email',
      label: 'Email',
      type: 'email',
      required: true,
      autocomplete: 'email',
    });
    expect(html).toContain('type="email"');
    expect(html).toContain('autocomplete="email"');
    expect(html).toMatch(/<input[^>]*required/);
  });
});

describe('FormError', () => {
  test('hidden por default + role=alert', async () => {
    const html = await render(FormError, { id: 'erro' }, { default: 'mensagem' });
    expect(html).toContain('role="alert"');
    expect(html).toContain('hidden');
    expect(html).toContain('id="erro"');
  });

  test('variant warning usa amber', async () => {
    const html = await render(FormError, { id: 'aviso', variant: 'warning' });
    expect(html).toContain('border-amber-500/40');
    expect(html).not.toContain('border-red-500');
  });

  test('variant success usa emerald', async () => {
    const html = await render(FormError, { id: 'ok', variant: 'success' });
    expect(html).toContain('border-emerald-500/40');
  });
});

describe('Section', () => {
  test('default e <section> max-6xl com padding md', async () => {
    const html = await render(Section, {}, { default: 'x' });
    expect(html).toMatch(/^<section/);
    expect(html).toContain('max-w-6xl');
    expect(html).toMatch(/\bpy-16\b/);
  });

  test('narrow reduz pra max-md (forms)', async () => {
    const html = await render(Section, { narrow: true }, { default: 'x' });
    expect(html).toContain('max-w-md');
    expect(html).not.toContain('max-w-6xl');
  });

  test('spacing lg aplica py maior pra hero', async () => {
    const html = await render(Section, { spacing: 'lg' }, { default: 'x' });
    expect(html).toMatch(/\bpy-20\b/);
  });

  test('as="main" troca tag semantica', async () => {
    const html = await render(Section, { as: 'main' }, { default: 'x' });
    expect(html).toMatch(/^<main/);
  });
});

describe('Badge', () => {
  test('renderiza <span> com variant neutral por default', async () => {
    const html = await render(Badge, {}, { default: 'production' });
    expect(html).toMatch(/^<span/);
    expect(html).toContain('bg-slate-800');
    expect(html).toContain('text-slate-200');
    expect(html).toContain('production');
    expect(html).toContain('data-variant="neutral"');
  });

  test('variant success usa tokens semanticos', async () => {
    const html = await render(Badge, { variant: 'success' }, { default: 'OK' });
    expect(html).toContain('bg-success-500/15');
    expect(html).toContain('text-success-200');
    expect(html).not.toContain('bg-slate-800');
  });

  test('variant danger usa danger-*', async () => {
    const html = await render(Badge, { variant: 'danger' }, { default: 'X' });
    expect(html).toContain('bg-danger-500/15');
    expect(html).toContain('ring-danger-500/30');
  });

  test('size md aumenta padding/text', async () => {
    const html = await render(Badge, { size: 'md' }, { default: 'X' });
    expect(html).toContain('text-sm');
    expect(html).toContain('px-2.5');
  });

  test('dot=true adiciona indicador circular escondido pra a11y', async () => {
    const html = await render(Badge, { variant: 'success', dot: true }, { default: 'Ativo' });
    // Atributos podem vir em qualquer ordem — checar presenca individual
    expect(html).toContain('aria-hidden="true"');
    expect(html).toContain('bg-success-400');
    expect(html).toMatch(/h-1\.5[^"]*w-1\.5[^"]*rounded-full/);
  });

  test('dot=false (default) nao renderiza indicador', async () => {
    const html = await render(Badge, {}, { default: 'X' });
    expect(html).not.toContain('aria-hidden="true"');
  });
});

describe('Tabs', () => {
  const tabs = [
    { id: 'visao', label: 'Visão geral' },
    { id: 'keys', label: 'Chaves' },
    { id: 'plano', label: 'Plano' },
  ];

  test('renderiza tablist com aria-label', async () => {
    const html = await render(Tabs, { tabs, ariaLabel: 'Configurações' });
    expect(html).toMatch(/role="tablist"[^>]*aria-label="Configurações"/);
  });

  test('cada tab tem role, id, aria-controls e data-tab-id', async () => {
    const html = await render(Tabs, { tabs });
    for (const t of tabs) {
      expect(html).toMatch(new RegExp(`role="tab"[^>]*id="tab-${t.id}"`));
      expect(html).toMatch(new RegExp(`aria-controls="panel-${t.id}"`));
      expect(html).toMatch(new RegExp(`data-tab-id="${t.id}"`));
    }
  });

  test('primeira tab fica ativa por default (aria-selected=true, tabindex=0)', async () => {
    const html = await render(Tabs, { tabs });
    expect(html).toMatch(/id="tab-visao"[^>]*aria-controls="panel-visao"[^>]*aria-selected="true"[^>]*tabindex="0"/);
    expect(html).toMatch(/id="tab-keys"[^>]*aria-selected="false"[^>]*tabindex="-1"/);
  });

  test('defaultTab override muda aba ativa', async () => {
    const html = await render(Tabs, { tabs, defaultTab: 'plano' });
    expect(html).toMatch(/id="tab-plano"[^>]*aria-selected="true"/);
    expect(html).toMatch(/id="tab-visao"[^>]*aria-selected="false"/);
  });

  test('paineis tem role=tabpanel + aria-labelledby coerente', async () => {
    const html = await render(Tabs, { tabs });
    for (const t of tabs) {
      expect(html).toMatch(new RegExp(`role="tabpanel"[^>]*id="panel-${t.id}"[^>]*aria-labelledby="tab-${t.id}"`));
    }
  });

  test('paineis inativos vem com hidden', async () => {
    const html = await render(Tabs, { tabs });
    // panel-keys e panel-plano estao inativos -> devem ter hidden
    expect(html).toMatch(/id="panel-keys"[^>]*hidden/);
    expect(html).toMatch(/id="panel-plano"[^>]*hidden/);
    // panel-visao ativo nao deve ter hidden (regex negativa simplificada:
    // verifica que nao ha 'hidden' antes do proximo '>')
    const visaoMatch = html.match(/id="panel-visao"[^>]*>/);
    expect(visaoMatch).not.toBeNull();
    expect(visaoMatch![0]).not.toContain('hidden');
  });

  test('hashSync=true seta data attr pro script ler', async () => {
    const html = await render(Tabs, { tabs, hashSync: true });
    expect(html).toContain('data-hash-sync="true"');
  });

  test('hashSync default e false', async () => {
    const html = await render(Tabs, { tabs });
    expect(html).toContain('data-hash-sync="false"');
  });
});

describe('ToastContainer', () => {
  test('renderiza region com aria-live=polite', async () => {
    const html = await render(ToastContainer);
    expect(html).toMatch(/id="ds-toast-region"[^>]*role="region"[^>]*aria-label="Notificações"[^>]*aria-live="polite"/);
  });

  test('inclui template de toast com slots data-slot', async () => {
    const html = await render(ToastContainer);
    expect(html).toContain('id="ds-toast-tpl"');
    expect(html).toContain('data-slot="icon"');
    expect(html).toContain('data-slot="message"');
    expect(html).toContain('data-slot="close"');
    expect(html).toContain('aria-label="Fechar notificação"');
  });

  test('region usa pointer-events-none pra nao bloquear cliques', async () => {
    const html = await render(ToastContainer);
    expect(html).toMatch(/id="ds-toast-region"[^>]*pointer-events-none/);
  });
});

describe('MetricCard', () => {
  test('renderiza article com label e value', async () => {
    const html = await render(MetricCard, { label: 'Eventos hoje', value: '12.847' });
    expect(html).toMatch(/^<article/);
    expect(html).toContain('Eventos hoje');
    expect(html).toContain('12.847');
    expect(html).toContain('data-metric-card');
  });

  test('uppercase tracking-wide no label e text-3xl tabular-nums no value', async () => {
    const html = await render(MetricCard, { label: 'X', value: '1' });
    expect(html).toContain('uppercase tracking-wide');
    expect(html).toMatch(/text-3xl[^"]*tabular-nums/);
  });

  test('delta up usa cor success', async () => {
    const html = await render(MetricCard, {
      label: 'X', value: '1',
      delta: { value: 18, direction: 'up', label: 'vs ontem' },
    });
    expect(html).toContain('text-success-300');
    expect(html).toContain('↑');
    expect(html).toContain('+18%');
    expect(html).toContain('vs ontem');
  });

  test('delta down usa cor danger', async () => {
    const html = await render(MetricCard, {
      label: 'X', value: '1',
      delta: { value: -5, direction: 'down' },
    });
    expect(html).toContain('text-danger-300');
    expect(html).toContain('↓');
    expect(html).toContain('-5%');
  });

  test('delta flat usa warning + seta horizontal', async () => {
    const html = await render(MetricCard, {
      label: 'X', value: '1',
      delta: { value: 0, direction: 'flat' },
    });
    expect(html).toContain('text-warning-300');
    expect(html).toContain('→');
  });

  test('sparkline gera path SVG com M e L (>=2 pontos)', async () => {
    const html = await render(MetricCard, {
      label: 'X', value: '1',
      sparkline: [10, 20, 15, 25, 18],
    });
    expect(html).toMatch(/<svg[^>]*viewBox="0 0 100 30"/);
    expect(html).toMatch(/<path[^>]*d="M [^"]+L [^"]+/);
    expect(html).toContain('aria-hidden="true"');
  });

  test('sparkline com 1 ponto so nao renderiza svg', async () => {
    const html = await render(MetricCard, {
      label: 'X', value: '1',
      sparkline: [10],
    });
    expect(html).not.toMatch(/<svg[^>]*viewBox="0 0 100 30"/);
  });

  test('hint vai pro title nativo', async () => {
    const html = await render(MetricCard, {
      label: 'X', value: '1',
      hint: 'Quantos eventos chegaram hoje',
    });
    expect(html).toContain('title="Quantos eventos chegaram hoje"');
  });
});

describe('ChartCard', () => {
  test('renderiza title + subtitle no header', async () => {
    const html = await render(ChartCard, { title: 'Eventos por hora', subtitle: 'Últimas 24h' });
    expect(html).toContain('Eventos por hora');
    expect(html).toContain('Últimas 24h');
  });

  test('default state ready esconde loading/empty/error', async () => {
    const html = await render(ChartCard, { title: 'X' });
    expect(html).toContain('data-state="ready"');
    expect(html).toMatch(/js-chart-state-loading[^"]*hidden/);
    expect(html).toMatch(/js-chart-state-empty[^"]*hidden/);
    expect(html).toMatch(/js-chart-state-error[^"]*hidden/);
  });

  test('state loading mostra skeleton bars com animate-pulse', async () => {
    const html = await render(ChartCard, { title: 'X', state: 'loading' });
    expect(html).toContain('data-state="loading"');
    expect(html).toContain('animate-pulse');
    // ready state escondido
    expect(html).toMatch(/js-chart-state-ready[^"]*hidden/);
  });

  test('state empty mostra emptyTitle e emptyDescription', async () => {
    const html = await render(ChartCard, {
      title: 'X', state: 'empty',
      emptyTitle: 'Sem dados', emptyDescription: 'Espere chegar evento',
    });
    expect(html).toContain('Sem dados');
    expect(html).toContain('Espere chegar evento');
  });

  test('state error tem role=alert + errorMessage', async () => {
    const html = await render(ChartCard, {
      title: 'X', state: 'error',
      errorMessage: 'Backend caiu',
    });
    // Tanto a class quanto role="alert" estao no mesmo elemento
    expect(html).toMatch(/<div[^>]*class="js-chart-state-error[^"]*"[^>]*role="alert"/);
    expect(html).toContain('Backend caiu');
  });

  test('action header renderiza link', async () => {
    const html = await render(ChartCard, {
      title: 'X',
      action: { href: '/grafana', label: 'Ver tudo', 'data-cta': 'chart-grafana' },
    });
    expect(html).toMatch(/href="\/grafana"[^>]*data-cta="chart-grafana"/);
    expect(html).toContain('Ver tudo');
  });

  test('height lg aplica h-80', async () => {
    const html = await render(ChartCard, { title: 'X', height: 'lg' });
    expect(html).toContain('h-80');
  });
});

describe('EmptyState', () => {
  test('default neutral renderiza icon + title', async () => {
    const html = await render(EmptyState, { title: 'Nada aqui', icon: '📊' });
    expect(html).toContain('Nada aqui');
    expect(html).toContain('📊');
    expect(html).toContain('border-slate-800');
  });

  test('description renderiza quando passada', async () => {
    const html = await render(EmptyState, {
      title: 'X', description: 'Cole o snippet pra começar',
    });
    expect(html).toContain('Cole o snippet pra começar');
  });

  test('variant danger usa borda danger + role=alert', async () => {
    const html = await render(EmptyState, { title: 'X', variant: 'danger' });
    expect(html).toContain('border-danger-500/30');
    expect(html).toContain('role="alert"');
  });

  test('variant warning usa borda warning sem role=alert', async () => {
    const html = await render(EmptyState, { title: 'X', variant: 'warning' });
    expect(html).toContain('border-warning-500/30');
    expect(html).not.toContain('role="alert"');
  });

  test('action com href renderiza <a>', async () => {
    const html = await render(EmptyState, {
      title: 'X',
      action: { href: '/cadastro', label: 'Criar conta', 'data-cta': 'empty-cadastro' },
    });
    expect(html).toMatch(/<a[^>]*href="\/cadastro"[^>]*data-cta="empty-cadastro"/);
    expect(html).toContain('Criar conta');
  });

  test('action sem href renderiza <button>', async () => {
    const html = await render(EmptyState, {
      title: 'X',
      action: { label: 'Tentar de novo' },
    });
    expect(html).toMatch(/<button[^>]*type="button"/);
    expect(html).toContain('Tentar de novo');
  });
});

describe('Stepper', () => {
  const steps = [
    { id: 'a', label: 'Primeiro' },
    { id: 'b', label: 'Segundo' },
    { id: 'c', label: 'Terceiro' },
  ];

  test('renderiza ol com aria-label', async () => {
    const html = await render(Stepper, { steps, current: 'a', ariaLabel: 'Wizard' });
    expect(html).toMatch(/^<ol[^>]*aria-label="Wizard"/);
  });

  test('cada step tem data-step-id e data-step-state', async () => {
    const html = await render(Stepper, { steps, current: 'b' });
    expect(html).toContain('data-step-id="a"');
    expect(html).toContain('data-step-id="b"');
    expect(html).toContain('data-step-id="c"');
    expect(html).toMatch(/data-step-id="a"[^>]*data-step-state="completed"/);
    expect(html).toMatch(/data-step-id="b"[^>]*data-step-state="current"/);
    expect(html).toMatch(/data-step-id="c"[^>]*data-step-state="pending"/);
  });

  test('current step tem aria-current=step', async () => {
    const html = await render(Stepper, { steps, current: 'b' });
    expect(html).toMatch(/aria-current="step"[^>]*data-step-id="b"|data-step-id="b"[^>]*aria-current="step"/);
  });

  test('completed steps mostram check', async () => {
    const html = await render(Stepper, { steps, current: 'c' });
    // Ambos a e b sao completed, deveriam ter ✓
    const completedCount = (html.match(/✓/g) || []).length;
    expect(completedCount).toBe(2);
  });

  test('current step usa cor brand-300 ring', async () => {
    const html = await render(Stepper, { steps, current: 'a' });
    expect(html).toContain('ring-brand-300');
  });

  test('pending steps usam cor neutra', async () => {
    const html = await render(Stepper, { steps, current: 'a' });
    // b e c sao pending → text-slate-400
    expect(html).toContain('text-slate-400');
  });
});

describe('Breadcrumbs', () => {
  test('renderiza nav com aria-label de trilha', async () => {
    const html = await render(Breadcrumbs, {
      items: [
        { href: '/cliente/painel', label: 'Painel' },
        { label: 'Configurações' },
      ],
    });
    expect(html).toMatch(/<nav[^>]*aria-label="Trilha de navegação"/);
    expect(html).toMatch(/<ol/);
  });

  test('item intermediario com href vira <a>', async () => {
    const html = await render(Breadcrumbs, {
      items: [
        { href: '/cliente/painel', label: 'Painel' },
        { label: 'Atual' },
      ],
    });
    expect(html).toMatch(/<a[^>]*href="\/cliente\/painel"[^>]*>Painel<\/a>/);
  });

  test('ultimo item sempre renderiza como span com aria-current=page', async () => {
    const html = await render(Breadcrumbs, {
      items: [
        { href: '/cliente/painel', label: 'Painel' },
        { label: 'Atual' },
      ],
    });
    expect(html).toMatch(/<span[^>]*aria-current="page"[^>]*>Atual<\/span>/);
  });

  test('separador / aparece entre items mas nao antes do primeiro', async () => {
    const html = await render(Breadcrumbs, {
      items: [
        { href: '/a', label: 'A' },
        { href: '/b', label: 'B' },
        { label: 'C' },
      ],
    });
    // 3 items → 2 separadores
    const separators = (html.match(/aria-hidden="true"[^>]*>\/</g) || []).length;
    expect(separators).toBe(2);
  });

  test('inclui JSON-LD BreadcrumbList', async () => {
    const html = await render(Breadcrumbs, {
      items: [
        { href: '/cliente/painel', label: 'Painel' },
        { label: 'Configurações' },
      ],
    });
    expect(html).toContain('"@type":"BreadcrumbList"');
    expect(html).toContain('"@type":"ListItem"');
    expect(html).toContain('"position":1');
    expect(html).toContain('"position":2');
  });

  test('item sem href no JSON-LD nao tem campo item', async () => {
    const html = await render(Breadcrumbs, {
      items: [{ label: 'Sozinho' }],
    });
    expect(html).toContain('"name":"Sozinho"');
    // ultimo nao tem href -> sem "item" no JSON-LD
    expect(html).toContain('"position":1,"name":"Sozinho"}]');
  });
});
