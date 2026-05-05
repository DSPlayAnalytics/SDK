/**
 * Smoke tests das pages publicas. Foco: o build SSR roda sem erro e os
 * blocos chave (hero, CTA, FAQ, calculadora) renderizam — sem cobrir
 * comportamento JS que precisaria de browser real.
 *
 * As pages que fazem fetch no <script> (cliente/*) ficam fora desse
 * arquivo — AstroContainer nao executa scripts, entao testar so o
 * markup HTML estatico delas teria valor baixo.
 */
import { experimental_AstroContainer as AstroContainer } from 'astro/container';
import { describe, expect, test } from 'vitest';

import Cadastro from '~/pages/cliente/cadastro.astro';
import Changelog from '~/pages/changelog.astro';
import Configuracoes from '~/pages/cliente/configuracoes.astro';
import EsqueciSenha from '~/pages/cliente/esqueci-senha.astro';
import Exportar from '~/pages/cliente/exportar.astro';
import Erro404 from '~/pages/404.astro';
import Login from '~/pages/cliente/login.astro';
import Erro500 from '~/pages/500.astro';
import Index from '~/pages/index.astro';
import Integracoes from '~/pages/integracoes.astro';
import Onboarding from '~/pages/cliente/onboarding.astro';
import Painel from '~/pages/cliente/painel.astro';
import Precos from '~/pages/precos.astro';
import Recursos from '~/pages/recursos.astro';
import Seguranca from '~/pages/seguranca.astro';
import Sobre from '~/pages/sobre.astro';
import Status from '~/pages/status.astro';

async function render(component: any): Promise<string> {
  const container = await AstroContainer.create();
  return container.renderToString(component, {});
}

describe('index.astro (home)', () => {
  test('renderiza sem erro e tem head com title configurado', async () => {
    const html = await render(Index);
    expect(html).toContain('Entenda seu site sem complicar');
  });

  test('hero tem CTA principal pra cadastro', async () => {
    const html = await render(Index);
    expect(html).toMatch(/href="\/cliente\/cadastro"[^>]*data-cta="hero-cadastro"/);
  });

  test('hero tem CTA secundario pra precos', async () => {
    const html = await render(Index);
    expect(html).toMatch(/href="\/precos"[^>]*data-cta="hero-precos"/);
  });

  test('hero tem badge "Feito no Brasil"', async () => {
    const html = await render(Index);
    expect(html).toContain('Feito no Brasil');
  });

  test('mockup do dashboard renderiza com SVG do grafico', async () => {
    const html = await render(Index);
    expect(html).toMatch(/<svg[^>]*viewBox="0 0 400 140"/);
    expect(html).toContain('chart-fill');
  });

  test('comparacao com concorrentes lista GA, Plausible e Fathom', async () => {
    const html = await render(Index);
    expect(html).toContain('Google Analytics');
    expect(html).toContain('Plausible');
    expect(html).toContain('Fathom');
  });

  test('FAQ tem details/summary acessiveis', async () => {
    const html = await render(Index);
    expect(html).toMatch(/<details/);
    expect(html).toMatch(/<summary/);
    expect(html).toContain('Vou precisar de banner de cookie?');
  });

  test('CTA final aponta pra cadastro', async () => {
    const html = await render(Index);
    expect(html).toMatch(/data-cta="footer-cadastro"/);
  });
});

describe('precos.astro', () => {
  test('renderiza com h1 e os 3 planos', async () => {
    const html = await render(Precos);
    expect(html).toContain('Planos simples');
    expect(html).toContain('data-plano="free"');
    expect(html).toContain('data-plano="pro"');
    expect(html).toContain('data-plano="business"');
  });

  test('toggle mensal/anual presente com aria-pressed e botao default mensal', async () => {
    const html = await render(Precos);
    expect(html).toMatch(/data-billing="mensal"[^>]*aria-pressed="true"/);
    expect(html).toMatch(/data-billing="anual"[^>]*aria-pressed="false"/);
  });

  test('plano Pro tem badge "Mais popular"', async () => {
    const html = await render(Precos);
    expect(html).toContain('Mais popular');
  });

  test('precos Pro com data-mensal=99 e data-anual=83 (16% econ)', async () => {
    const html = await render(Precos);
    expect(html).toMatch(/data-mensal="99"[^>]*data-anual="83"/);
  });

  test('plano Business diz "Sob consulta" (sem preco numerico)', async () => {
    const html = await render(Precos);
    const businessSection = html.match(/data-plano="business"[\s\S]*?<\/article>/);
    expect(businessSection).not.toBeNull();
    expect(businessSection![0]).toContain('Sob consulta');
  });

  test('calculadora tem input range com id calc-volume', async () => {
    const html = await render(Precos);
    expect(html).toMatch(/<input[^>]*id="calc-volume"[^>]*type="range"/);
    expect(html).toContain('calc-resultado');
  });

  test('tabela comparativa lista as 3 colunas de plano', async () => {
    const html = await render(Precos);
    expect(html).toMatch(/<table/);
    expect(html).toMatch(/<th[^>]*>Free<\/th>/);
    expect(html).toMatch(/<th[^>]*>Business<\/th>/);
  });

  test('FAQ billing tem perguntas chaves sobre cancelamento e reembolso', async () => {
    const html = await render(Precos);
    expect(html).toContain('Tem multa pra cancelar?');
    expect(html).toContain('Reembolso se eu não gostar?');
  });

  test('CTA do plano Pro vai pra cadastro com query plano=pro', async () => {
    const html = await render(Precos);
    expect(html).toMatch(/href="\/cliente\/cadastro\?plano=pro"/);
  });
});

describe('cliente/painel.astro', () => {
  test('renderiza com title + skeleton inicial + secoes principais escondidas', async () => {
    const html = await render(Painel);
    expect(html).toContain('Painel');
    expect(html).toContain('Carregando dados do seu site');
    // skeleton com aria-busy
    expect(html).toMatch(/id="painel-loading"[^>]*aria-busy="true"/);
    // conteudo e erro escondidos por SSR
    expect(html).toMatch(/id="painel-conteudo"[^>]*hidden/);
    expect(html).toMatch(/id="painel-erro"[^>]*hidden/);
  });

  test('4 KPIs com classes js-card-* pra hidratar', async () => {
    const html = await render(Painel);
    expect(html).toContain('js-card-eventos-hoje');
    expect(html).toContain('js-card-quota');
    expect(html).toContain('js-card-cardinalidade');
    expect(html).toContain('js-card-plano');
  });

  test('ChartCard 24h em estado empty com link pro Grafana', async () => {
    const html = await render(Painel);
    expect(html).toContain('Eventos por hora');
    expect(html).toContain('app.dsplayground.com.br');
    expect(html).toMatch(/data-state="empty"/);
  });

  test('atalhos pra configuracoes/exportar/precos', async () => {
    const html = await render(Painel);
    expect(html).toMatch(/href="\/cliente\/configuracoes"[^>]*data-cta="painel-atalho-keys"/);
    expect(html).toMatch(/href="\/cliente\/exportar"[^>]*data-cta="painel-atalho-exportar"/);
    expect(html).toMatch(/href="\/precos"[^>]*data-cta="painel-atalho-precos"/);
  });

  test('marcado noindex (area logada)', async () => {
    const html = await render(Painel);
    expect(html).toContain('noindex');
  });

  test('live pill com aria-live polite (escondido inicial, JS revela apos load)', async () => {
    const html = await render(Painel);
    expect(html).toMatch(/id="painel-live-pill"[^>]*class="hidden[^"]*"[^>]*aria-live="polite"/);
    expect(html).toContain('id="painel-live-text"');
  });
});

describe('cliente/configuracoes.astro', () => {
  test('renderiza com tabs estruturadas', async () => {
    const html = await render(Configuracoes);
    expect(html).toContain('Configurações');
    expect(html).toMatch(/role="tablist"/);
    // 7 abas (4 ativas + 3 placeholder Fase 2/3)
    expect(html).toMatch(/data-tab-id="visao"/);
    expect(html).toMatch(/data-tab-id="chaves"/);
    expect(html).toMatch(/data-tab-id="plano"/);
    expect(html).toMatch(/data-tab-id="embeds"/);
    expect(html).toMatch(/data-tab-id="faturamento"/);
    expect(html).toMatch(/data-tab-id="time"/);
    expect(html).toMatch(/data-tab-id="perfil"/);
  });

  test('aba embeds tem CTA pra plano Pro', async () => {
    const html = await render(Configuracoes);
    expect(html).toContain('Embeds de gráfico');
    expect(html).toMatch(/data-cta="config-embeds-pro"/);
  });

  test('aba faturamento exibe secao de plano atual e comparacao de planos', async () => {
    const html = await render(Configuracoes);
    expect(html).toContain('Plano atual');
    expect(html).toContain('Comparar planos');
    expect(html).toMatch(/id="fat-planos-grid"/);
  });

  test('aba time descreve papéis previstos (Owner/Editor/Viewer)', async () => {
    const html = await render(Configuracoes);
    expect(html).toContain('Owner');
    expect(html).toContain('Editor');
    expect(html).toContain('Viewer');
  });

  test('aba visao tem 3 MetricCards (eventos hoje, quota, cardinalidade)', async () => {
    const html = await render(Configuracoes);
    expect(html).toContain('js-card-eventos-hoje');
    expect(html).toContain('js-card-quota-pct');
    expect(html).toContain('js-card-cardinalidade-pct');
  });

  test('aba plano tem CTA pra /precos', async () => {
    const html = await render(Configuracoes);
    expect(html).toMatch(/href="\/precos"[^>]*data-cta="config-upgrade"/);
  });

  test('aba plano tem barra de progressbar acessivel pra cardinalidade', async () => {
    const html = await render(Configuracoes);
    expect(html).toMatch(/id="cardinalidade-bar"[^>]*role="progressbar"[^>]*aria-valuemin="0"[^>]*aria-valuemax="100"/);
  });

  test('aba perfil tem 2 forms (email + senha)', async () => {
    const html = await render(Configuracoes);
    expect(html).toMatch(/id="form-email"/);
    expect(html).toMatch(/id="form-senha"/);
    expect(html).toMatch(/id="submit-email"[^>]*data-cta="trocar-email"/);
    expect(html).toMatch(/id="submit-senha"[^>]*data-cta="trocar-senha"/);
  });

  test('hashSync ligado pra deep link nas tabs', async () => {
    const html = await render(Configuracoes);
    expect(html).toContain('data-hash-sync="true"');
  });

  test('skeleton inicial visivel + conteudo escondido', async () => {
    const html = await render(Configuracoes);
    expect(html).toMatch(/id="config-loading"[^>]*aria-busy="true"/);
    expect(html).toMatch(/id="config-conteudo"[^>]*hidden/);
  });

  test('marcado noindex', async () => {
    const html = await render(Configuracoes);
    expect(html).toContain('noindex');
  });
});

describe('cliente/onboarding.astro', () => {
  test('renderiza com titulo e Stepper inicial em key', async () => {
    const html = await render(Onboarding);
    expect(html).toContain('Vamos colocar pra rodar');
    expect(html).toMatch(/data-current-step="key"/);
  });

  test('3 steps no Stepper com IDs corretos', async () => {
    const html = await render(Onboarding);
    expect(html).toContain('data-step-id="key"');
    expect(html).toContain('data-step-id="snippet"');
    expect(html).toContain('data-step-id="evento"');
  });

  test('step containers escondidos por SSR (JS revela apos load)', async () => {
    const html = await render(Onboarding);
    expect(html).toMatch(/id="step-key"[^>]*hidden/);
    expect(html).toMatch(/id="step-snippet"[^>]*hidden/);
    expect(html).toMatch(/id="step-evento"[^>]*hidden/);
  });

  test('step 2 tem 5 plataformas no Tabs (html/react/next/wordpress/shopify)', async () => {
    const html = await render(Onboarding);
    expect(html).toContain('data-tab-id="html"');
    expect(html).toContain('data-tab-id="react"');
    expect(html).toContain('data-tab-id="next"');
    expect(html).toContain('data-tab-id="wordpress"');
    expect(html).toContain('data-tab-id="shopify"');
  });

  test('step 2 tem botoes copy snippet pra cada plataforma', async () => {
    const html = await render(Onboarding);
    expect(html).toMatch(/data-snippet="snippet-html"[^>]*class="js-copy-snippet/);
    expect(html).toMatch(/data-snippet="snippet-react"/);
  });

  test('step 3 tem polling visual (spinner + counter)', async () => {
    const html = await render(Onboarding);
    expect(html).toContain('id="onb-poll-counter"');
    expect(html).toMatch(/animate-spin/);
  });

  test('step 3 tem estados timeout e sucesso escondidos por SSR', async () => {
    const html = await render(Onboarding);
    expect(html).toMatch(/id="onb-timeout"[^>]*hidden/);
    expect(html).toMatch(/id="onb-sucesso"[^>]*hidden/);
  });

  test('step 3 sucesso tem CTAs pra painel + configuracoes', async () => {
    const html = await render(Onboarding);
    expect(html).toMatch(/href="\/cliente\/painel"[^>]*data-cta="onb-finalizar-painel"/);
    expect(html).toMatch(/href="\/cliente\/configuracoes"[^>]*data-cta="onb-finalizar-config"/);
  });

  test('marcado noindex (area logada)', async () => {
    const html = await render(Onboarding);
    expect(html).toContain('noindex');
  });
});

describe('recursos.astro', () => {
  test('renderiza com h1 + Brasil-first', async () => {
    const html = await render(Recursos);
    expect(html).toContain('Pequeno');
    expect(html).toContain('Brasileiro');
  });

  test('tem 3 grupos com IDs ancorados (coleta/painel/controle)', async () => {
    const html = await render(Recursos);
    expect(html).toMatch(/id="coleta"/);
    expect(html).toMatch(/id="painel"/);
    expect(html).toMatch(/id="controle"/);
  });

  test('FAQ com perguntas tecnicas', async () => {
    const html = await render(Recursos);
    expect(html).toMatch(/<details/);
    expect(html).toContain('Tem SDK pra mobile?');
  });

  test('CTA final pra cadastro + precos', async () => {
    const html = await render(Recursos);
    expect(html).toMatch(/data-cta="recursos-cadastro"/);
    expect(html).toMatch(/data-cta="recursos-precos"/);
  });
});

describe('seguranca.astro', () => {
  test('hero diz Privacidade primeiro', async () => {
    const html = await render(Seguranca);
    expect(html).toContain('Privacidade primeiro');
  });

  test('lista camadas com JWT RS256 + bcrypt + multi-tenant', async () => {
    const html = await render(Seguranca);
    expect(html).toContain('JWT RS256');
    expect(html).toContain('bcrypt');
    expect(html).toContain('Multi-tenant isolado');
  });

  test('seção LGPD lista direitos do titular', async () => {
    const html = await render(Seguranca);
    expect(html).toContain('Direito de exportação');
    expect(html).toContain('Direito de exclusão');
  });

  test('disclosure de vulnerabilidade com email seguranca@', async () => {
    const html = await render(Seguranca);
    expect(html).toContain('seguranca@dsplayground.com.br');
  });

  test('CTA final pra cadastro', async () => {
    const html = await render(Seguranca);
    expect(html).toMatch(/data-cta="seguranca-cadastro"/);
  });
});

describe('sobre.astro', () => {
  test('hero com tom honesto Brasil-first', async () => {
    const html = await render(Sobre);
    expect(html).toContain('pequeno e contente');
  });

  test('seção história + valores + roadmap honesto', async () => {
    const html = await render(Sobre);
    expect(html).toContain('A história curta');
    expect(html).toContain('Princípios que guiam');
    expect(html).toContain('Pra onde vai');
  });

  test('lista princípios com Brasil-first', async () => {
    const html = await render(Sobre);
    expect(html).toContain('Brasil-first');
    expect(html).toContain('Você é o cliente');
  });

  test('CTA pra cadastro + recursos', async () => {
    const html = await render(Sobre);
    expect(html).toMatch(/data-cta="sobre-cadastro"/);
    expect(html).toMatch(/data-cta="sobre-recursos"/);
  });
});

describe('404.astro', () => {
  test('mostra 404 grande + h1 + CTA pra home', async () => {
    const html = await render(Erro404);
    expect(html).toContain('404');
    expect(html).toContain('Essa página não existe');
    expect(html).toMatch(/data-cta="404-home"/);
  });

  test('marcado noindex', async () => {
    const html = await render(Erro404);
    expect(html).toContain('noindex');
  });

  test('lista links de navegacao alternativa', async () => {
    const html = await render(Erro404);
    expect(html).toMatch(/href="\/recursos"/);
    expect(html).toMatch(/href="\/seguranca"/);
    expect(html).toMatch(/href="\/sobre"/);
  });
});

describe('500.astro', () => {
  test('mostra 500 + h1 + botao recarregar', async () => {
    const html = await render(Erro500);
    expect(html).toContain('500');
    expect(html).toContain('Algo travou aqui');
    expect(html).toMatch(/id="recarregar"/);
  });

  test('marcado noindex', async () => {
    const html = await render(Erro500);
    expect(html).toContain('noindex');
  });

  test('disclosure de email contato@ (repo privado, sem GitHub publico)', async () => {
    const html = await render(Erro500);
    expect(html).toContain('mailto:contato@dsplayground.com.br');
  });
});

describe('integracoes.astro', () => {
  test('hero "Cole, instale, pronto"', async () => {
    const html = await render(Integracoes);
    expect(html).toContain('Cole, instale');
  });

  test('Tabs com 6 plataformas (html/react/next/astro/wordpress/shopify)', async () => {
    const html = await render(Integracoes);
    expect(html).toContain('data-tab-id="html"');
    expect(html).toContain('data-tab-id="react"');
    expect(html).toContain('data-tab-id="next"');
    expect(html).toContain('data-tab-id="astro"');
    expect(html).toContain('data-tab-id="wordpress"');
    expect(html).toContain('data-tab-id="shopify"');
  });

  test('placeholder pk_xxx aparece em todos os snippets', async () => {
    const html = await render(Integracoes);
    expect(html).toContain('pk_xxxxxxxxxxxxxxxxxxxx');
  });

  test('seção REST API lista endpoints chave', async () => {
    const html = await render(Integracoes);
    expect(html).toContain('/auth/sdk-token');
    expect(html).toContain('/cliente/auth/configuracoes');
    expect(html).toContain('/cliente/exportar/');
    expect(html).toContain('/health/app');
  });

  test('seção eventos customizados com exemplo enviarEvento', async () => {
    const html = await render(Integracoes);
    expect(html).toContain('enviarEvento');
    expect(html).toContain('venda_concluida');
  });

  test('CTAs pra cadastro + GitHub do SDK', async () => {
    const html = await render(Integracoes);
    expect(html).toMatch(/data-cta="integracoes-cadastro"/);
    expect(html).toMatch(/data-cta="integracoes-github"/);
  });
});

describe('cliente/esqueci-senha.astro', () => {
  test('título "Recuperar senha" e descrição do fluxo de redefinicao', async () => {
    const html = await render(EsqueciSenha);
    expect(html).toContain('Recuperar senha');
    // Anti-enum: copy menciona o token TTL pra confirmar fluxo proper
    expect(html).toContain('escolher uma nova senha');
  });

  test('input email com label associada (a11y)', async () => {
    const html = await render(EsqueciSenha);
    expect(html).toMatch(/<label[^>]*for="email"/);
    expect(html).toMatch(/<input[^>]*id="email"[^>]*type="email"/);
  });

  test('botão de submit tem data-cta="form-esqueci-senha"', async () => {
    const html = await render(EsqueciSenha);
    expect(html).toContain('data-cta="form-esqueci-senha"');
  });

  test('link "Lembrou da senha?" aponta pra /cliente/login', async () => {
    const html = await render(EsqueciSenha);
    expect(html).toMatch(/href="\/cliente\/login"/);
    expect(html).toContain('Lembrou da senha?');
  });

  test('link "Sem conta?" aponta pra /cliente/cadastro', async () => {
    const html = await render(EsqueciSenha);
    expect(html).toMatch(/href="\/cliente\/cadastro"/);
    expect(html).toContain('Sem conta?');
  });

  test('mensagem de sucesso existe + menciona expiração em 15 minutos', async () => {
    const html = await render(EsqueciSenha);
    expect(html).toContain('Link enviado');
    expect(html).toContain('15 minutos');
  });

  test('caixa de erro tem role=alert (a11y)', async () => {
    const html = await render(EsqueciSenha);
    const alertCount = (html.match(/role="alert"/g) || []).length;
    expect(alertCount).toBeGreaterThanOrEqual(2);
  });
});

describe('cliente/login.astro', () => {
  test('título "Entrar" com instrução de email', async () => {
    const html = await render(Login);
    expect(html).toContain('Entrar');
    expect(html).toContain('Use o email da sua conta');
  });

  test('inputs email e senha com labels associadas (a11y)', async () => {
    const html = await render(Login);
    expect(html).toMatch(/<label[^>]*for="email"/);
    expect(html).toMatch(/<input[^>]*id="email"[^>]*type="email"/);
    expect(html).toMatch(/<label[^>]*for="senha"/);
    expect(html).toMatch(/<input[^>]*id="senha"[^>]*type="password"/);
  });

  test('botão submit com data-cta="form-login"', async () => {
    const html = await render(Login);
    expect(html).toContain('data-cta="form-login"');
  });

  test('link "Sem conta?" aponta pra /cliente/cadastro', async () => {
    const html = await render(Login);
    expect(html).toMatch(/href="\/cliente\/cadastro"/);
    expect(html).toContain('Sem conta?');
  });

  test('link "Esqueci minha senha" com data-cta="link-esqueci-senha"', async () => {
    const html = await render(Login);
    expect(html).toMatch(/href="\/cliente\/esqueci-senha"[^>]*data-cta="link-esqueci-senha"/);
    expect(html).toContain('Esqueci minha senha');
  });

  test('FormError oculto com role=alert (a11y)', async () => {
    const html = await render(Login);
    expect(html).toContain('role="alert"');
    expect(html).toContain('hidden');
  });
});

describe('cliente/cadastro.astro', () => {
  test('título "Criar conta" com slogan grátis sem cartão', async () => {
    const html = await render(Cadastro);
    expect(html).toContain('Criar conta');
    expect(html).toContain('grátis');
    expect(html).toContain('Sem cartão de crédito');
  });

  test('4 inputs: nome_site, slug, email, senha com labels (a11y)', async () => {
    const html = await render(Cadastro);
    expect(html).toMatch(/<label[^>]*for="nome_site"/);
    expect(html).toMatch(/<label[^>]*for="slug"/);
    expect(html).toMatch(/<label[^>]*for="email"/);
    expect(html).toMatch(/<label[^>]*for="senha"/);
  });

  test('slug tem hint sobre URL do painel', async () => {
    const html = await render(Cadastro);
    expect(html).toContain('URL do seu painel');
    expect(html).toContain('letras minúsculas');
  });

  test('slug tem pattern de validação e limites 3-32', async () => {
    const html = await render(Cadastro);
    expect(html).toMatch(/minlength="3"/);
    expect(html).toMatch(/maxlength="32"/);
    expect(html).toMatch(/pattern="/);
  });

  test('botão submit com data-cta="form-cadastro"', async () => {
    const html = await render(Cadastro);
    expect(html).toContain('data-cta="form-cadastro"');
  });

  test('link "Já tem conta?" aponta pra /cliente/login', async () => {
    const html = await render(Cadastro);
    expect(html).toMatch(/href="\/cliente\/login"/);
    expect(html).toContain('Já tem conta?');
  });

  test('FormError oculto com role=alert (a11y)', async () => {
    const html = await render(Cadastro);
    expect(html).toContain('role="alert"');
    expect(html).toContain('hidden');
  });
});

describe('cliente/exportar.astro', () => {
  test('título "Arquivo de dados" com breadcrumb Painel', async () => {
    const html = await render(Exportar);
    expect(html).toContain('Arquivo de dados');
    expect(html).toMatch(/href="\/cliente\/painel"/);
    expect(html).toContain('Exportar dados');
  });

  test('descreve formato .lp.gz e influx write', async () => {
    const html = await render(Exportar);
    expect(html).toContain('.lp.gz');
    expect(html).toContain('influx write');
  });

  test('lista de arquivos inicialmente oculta + div estado visível', async () => {
    const html = await render(Exportar);
    expect(html).toMatch(/id="arquivos"[^>]*hidden/);
    expect(html).toContain('id="estado"');
    expect(html).toContain('Carregando');
  });

  test('caixa de erro com role=alert inicialmente oculta', async () => {
    const html = await render(Exportar);
    expect(html).toMatch(/id="erro"[^>]*role="alert"/);
    expect(html).toContain('hidden');
  });

  test('nota de validade dos links de 5 minutos', async () => {
    const html = await render(Exportar);
    expect(html).toContain('5 minutos');
  });

  test('marcado noindex (área logada)', async () => {
    const html = await render(Exportar);
    expect(html).toContain('noindex');
  });
});

describe('changelog.astro', () => {
  test('hero "O que mudou recentemente"', async () => {
    const html = await render(Changelog);
    expect(html).toContain('mudou');
    expect(html).toContain('recentemente');
  });

  test('renderiza ol com aria-label de historico', async () => {
    const html = await render(Changelog);
    expect(html).toMatch(/<ol[^>]*aria-label="Histórico de releases"/);
  });

  test('cada release tem time com datetime ISO', async () => {
    const html = await render(Changelog);
    expect(html).toMatch(/<time[^>]*datetime="2026-05-01"/);
    expect(html).toMatch(/<time[^>]*datetime="2026-04-29"/);
  });

  test('release destaque tem ring brand', async () => {
    const html = await render(Changelog);
    expect(html).toContain('ring-brand-500/30');
  });

  test('badges de tipo (novo/fix/manutencao) renderizam', async () => {
    const html = await render(Changelog);
    expect(html).toContain('novo');
    expect(html).toContain('manutenção');
  });

  test('CTA pra mandar sugestão (mailto, sem GitHub — repo privado)', async () => {
    const html = await render(Changelog);
    expect(html).toMatch(/data-cta="changelog-sugerir"/);
    expect(html).not.toContain('changelog-github');
    expect(html).not.toMatch(/github\.com\/[^/]+\/portifolio\/commits/);
  });

  test('lista features dos PRs recentes (Onboarding, abas, embed)', async () => {
    const html = await render(Changelog);
    expect(html).toContain('Onboarding');
    expect(html).toContain('abas');
    expect(html).toContain('Embed iframe');
  });
});

describe('status.astro', () => {
  test('hero com badge de status overall', async () => {
    const html = await render(Status);
    expect(html).toContain('id="status-overall-label"');
    expect(html).toContain('verificando');
  });

  test('lista dos servicos com pills js-status-pill', async () => {
    const html = await render(Status);
    expect(html).toMatch(/<ul[^>]*aria-label="Status dos serviços"/);
    expect(html).toContain('data-svc-id="api"');
    expect(html).toContain('data-svc-id="web"');
    expect(html).toContain('data-svc-id="grafana"');
    expect(html).toContain('data-svc-id="influxdb"');
  });

  test('API tem healthUrl pra ping', async () => {
    const html = await render(Status);
    expect(html).toMatch(/data-svc-id="api"[^>]*data-svc-health="\/health\/app"/);
  });

  test('servicos atras de auth tem link de detalhe', async () => {
    const html = await render(Status);
    expect(html).toMatch(/data-cta="status-grafana-detalhe"/);
    expect(html).toMatch(/data-cta="status-embed-detalhe"/);
  });

  test('CTA pra reportar incidente vai pra mailto contato@', async () => {
    const html = await render(Status);
    expect(html).toMatch(/data-cta="status-reportar"/);
    expect(html).toContain('mailto:contato@dsplayground.com.br');
  });

  test('elemento de "ultima verificacao" presente pra hidratar', async () => {
    const html = await render(Status);
    expect(html).toContain('id="status-ultima-verificacao"');
  });
});
