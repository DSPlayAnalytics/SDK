# DSPlay Analytics — Landing

![Astro](https://img.shields.io/badge/Astro-6-BC52EE?logo=astro&logoColor=white)
![Tailwind CSS](https://img.shields.io/badge/Tailwind-4-38BDF8?logo=tailwindcss&logoColor=white)
![Cloudflare Pages](https://img.shields.io/badge/Deploy-Cloudflare%20Pages-F38020?logo=cloudflare&logoColor=white)
![Tests](https://img.shields.io/badge/tests-245%20passing-22C55E)
![License](https://img.shields.io/badge/license-MIT-6B7280)

Landing comercial e portal do cliente do [DSPlay Analytics](https://dsplayground.com.br).

---

## Índice

- [Visão geral](#visão-geral)
- [Arquitetura](#arquitetura)
- [Stack](#stack)
- [Estrutura de diretórios](#estrutura-de-diretórios)
- [Páginas](#páginas)
- [Design system](#design-system)
- [Lib](#lib)
- [Testes](#testes)
- [Variáveis de ambiente](#variáveis-de-ambiente)
- [Desenvolvimento local](#desenvolvimento-local)
- [Build e deploy](#build-e-deploy)
- [Repositórios relacionados](#repositórios-relacionados)

---

## Visão geral

Aplicação Astro 6 totalmente estática servida no edge via **Cloudflare Pages**. Cobre duas superfícies distintas:

- **Marketing** — home, preços, recursos, integrações, segurança, changelog e status. Páginas públicas sem autenticação.
- **Portal do cliente** — cadastro, login, onboarding, painel de métricas (Grafana embedado), configurações e exportação de dados arquivados. Autenticação via cookie `cliente_session` gerenciado pelo backend.

A própria landing instrumenta telemetria de funil via **[@DSPlayAnalytics/SDK](https://github.com/DSPlayAnalytics/SDK)** (dogfood), emitindo eventos como `cta_clicado`, `onboarding_step_concluido` e `primeiro_evento`.

---

## Arquitetura

```
Browser
  │
  ├─ Páginas estáticas (HTML/CSS/JS)
  │    └─ Cloudflare Pages CDN (dsplayground.com.br)
  │         └─ Build: astro build → dist/
  │
  ├─ Auth / API calls (fetch + credentials: include)
  │    └─ api.dsplayground.com.br  (DSPlayAnalytics/backend)
  │         ├─ POST /cliente/auth/login         → Set-Cookie: cliente_session
  │         ├─ POST /cliente/auth/cadastro
  │         ├─ GET  /cliente/auth/configuracoes
  │         └─ GET  /cliente/exportar/<dia>     → redirect signed URL R2
  │
  ├─ Dashboard autenticado (iframe)
  │    └─ app.dsplayground.com.br (Grafana)
  │         └─ nginx auth_request → Flask /cliente/auth/gate
  │              → X-WEBAUTH-USER header → Grafana auth.proxy
  │
  └─ Telemetria (WebSocket via SDK)
       └─ api.dsplayground.com.br/socket.io
            └─ eventos: cta_clicado, page_view, onboarding_step_concluido
```

---

## Stack

| Tecnologia | Versão | Função |
|---|---|---|
| [Astro](https://astro.build) | 6 | Framework — output estático, file-based routing |
| [Tailwind CSS](https://tailwindcss.com) | 4 | Estilização — tokens semânticos via `@theme {}` |
| TypeScript | 5 | Tipagem estática |
| [Vitest](https://vitest.dev) | 3 | Test runner |
| [Happy DOM](https://github.com/capricorn86/happy-dom) | 20 | DOM mock para testes |
| [@DSPlayAnalytics/SDK](https://github.com/DSPlayAnalytics/SDK) | 0.4.0 | Telemetria de eventos (dogfood) |
| [Wrangler](https://developers.cloudflare.com/workers/wrangler/) | 4 | Deploy Cloudflare Pages |

---

## Estrutura de diretórios

```
src/
├── pages/                        # Rotas (file-based routing Astro)
│   ├── index.astro               # Home
│   ├── precos.astro
│   ├── recursos.astro
│   ├── integracoes.astro
│   ├── seguranca.astro
│   ├── sobre.astro
│   ├── changelog.astro
│   ├── status.astro
│   ├── 404.astro
│   ├── 500.astro
│   └── cliente/                  # Portal autenticado
│       ├── login.astro
│       ├── cadastro.astro
│       ├── esqueci-senha.astro
│       ├── redefinir-senha.astro
│       ├── onboarding.astro
│       ├── painel.astro
│       ├── configuracoes.astro
│       └── exportar.astro
│
├── components/
│   ├── Nav.astro                 # Navbar — troca itens logado/deslogado
│   ├── Footer.astro
│   ├── SeoHead.astro             # <head>: title, OG, canonical
│   └── ui/                       # Biblioteca de componentes (ver Design system)
│
├── layouts/
│   └── Base.astro                # Layout principal — carrega Tailwind, SDK,
│                                 # Nav, Footer, ToastContainer
│
├── lib/                          # Lógica reutilizável (ver Lib)
│   ├── api.ts                    # Cliente HTTP com Result<T,E>
│   ├── nav-auth.ts               # Detecção de sessão no Nav
│   ├── redirect.ts               # Validação segura de ?next=
│   ├── toast.ts                  # Notificações imperativas
│   ├── tracking.ts               # Telemetria de cliques [data-cta]
│   └── config.ts                 # Constantes de ambiente
│
├── styles/
│   └── global.css                # @import "tailwindcss" + @theme {} tokens
│
├── config.ts                     # Re-export das constantes públicas
└── env.d.ts                      # Tipos para import.meta.env
```

---

## Páginas

### Públicas

| Rota | Descrição |
|---|---|
| `/` | Home — proposta de valor, comparativo, FAQ, CTA |
| `/precos` | Planos free / pro com tabela comparativa |
| `/recursos` | Funcionalidades detalhadas da plataforma |
| `/integracoes` | Guias de instalação: WordPress, React, HTML puro |
| `/seguranca` | LGPD, privacidade, compliance |
| `/sobre` | Sobre o projeto |
| `/changelog` | Histórico de versões |
| `/status` | Status dos serviços em tempo real |

### Portal do cliente

| Rota | Descrição | Auth |
|---|---|---|
| `/cliente/cadastro` | Criação de conta (email, senha, nome do site, slug) | Público |
| `/cliente/login` | Login com email + senha | Público |
| `/cliente/esqueci-senha` | Solicita link de redefinição de senha por email | Público |
| `/cliente/redefinir-senha` | Cria nova senha via token (`?t=`) — nunca loga diretamente | Público (token) |
| `/cliente/onboarding` | Wizard pós-cadastro em 3 passos | Cookie |
| `/cliente/painel` | Dashboard com Grafana embedado + live counter (30s) | Cookie |
| `/cliente/configuracoes` | 7 abas: publishable keys, quota, plano, email, senha, billing, exportar | Cookie |
| `/cliente/exportar` | Lista e download de arquivos arquivados (R2 signed URLs) | Cookie |

---

## Design system

Componentes em `src/components/ui/`. Todos são componentes `.astro` com zero JavaScript por padrão — interatividade adicionada via `<script>` inline quando necessário.

| Componente | Props principais | Uso |
|---|---|---|
| `Button` | `variant` (primary/secondary/ghost), `size` (sm/md), `href`, `disabled`, `fullWidth`, `data-cta` | CTAs, ações de formulário |
| `Card` | `class` | Container com padding e borda |
| `Input` | `label`, `type`, `id`, `required`, `autocomplete` | Campos de formulário |
| `FormError` | `id` | Exibe mensagem de erro (toggled via `classList`) |
| `Section` | `narrow` (boolean) | Wrapper full-width ou `max-w` centralizado |
| `Badge` | `color`, `size` | Label inline com cor semântica |
| `Breadcrumbs` | `items: {label, href}[]` | Navegação estruturada |
| `Tabs` | `tabs: {id, label}[]` | Tab group com `overflow-x-auto` em mobile |
| `Stepper` | `steps: {number, title}[]`, `current` | Progresso de wizard |
| `ChartCard` | slot | Container para embeds Grafana |
| `MetricCard` | `value`, `label`, `trend` | KPI com indicador de tendência |
| `EmptyState` | `icon`, `title`, `description` | Placeholder quando sem dados |
| `ToastContainer` | — | Region `aria-live` para `showToast()` |

### Tokens de cor

Definidos em `src/styles/global.css` via `@theme {}` do Tailwind 4:

```css
@theme {
  --color-brand-*:   /* cor primária da marca */
  --color-success-*: /* verde — confirmações */
  --color-warning-*: /* amarelo — alertas */
  --color-danger-*:  /* vermelho — erros */
  --color-info-*:    /* azul — informações neutras */
}
```

---

## Lib

### `api.ts` — Cliente HTTP

Todas as funções retornam um **discriminated union** `Result<TOk, TErr>`:

```typescript
type Result<T, E> =
  | { ok: true } & T           // dados tipados diretamente no objeto
  | { ok: false; code: E; message: string; status: number }
```

O tipo força narrowing explícito no caller — `if (r.ok)` antes de acessar dados.

```typescript
// Opções injetáveis (fetchImpl permite testes sem mock global)
interface ApiOptions {
  apiUrl: string;
  fetchImpl?: typeof fetch;
}

// Funções disponíveis
cadastrar(payload, opts)              → Result<CadastroOk, CadastroErrorCode>
login(payload, opts)                  → Result<LoginOk, LoginErrorCode>
solicitarMagicLink(payload, opts)     → Result<MagicLinkOk, MagicLinkErrorCode>
solicitarRecuperarSenha(payload, opts)→ Result<MagicLinkOk, RecuperarSenhaErrorCode>
confirmarRecuperarSenha(payload, opts)→ Result<ConfirmarRecuperarSenhaOk, ConfirmarRecuperarSenhaErrorCode>
alterarSenha(payload, opts)           → Result<AlterarOk, AlterarSenhaErrorCode>
alterarEmail(payload, opts)           → Result<AlterarOk, AlterarEmailErrorCode>
obterConfiguracoes(opts)              → Result<ConfiguracoesOk, ConfiguracoesErrorCode>
listarExports(opts)                   → Result<ListarExportsOk, ListarExportsErrorCode>
urlDownloadExport(apiUrl, dia)        → string  // redirect para signed URL R2
urlDashboard(dashboardUrl, query?)    → string
```

Todas as chamadas usam `credentials: 'include'` para propagar o cookie de sessão.

---

### `nav-auth.ts` — Estado de sessão

Detecta se o usuário está logado e alterna os itens do `Nav` sem flash de layout:

```typescript
criarFetcherMe(apiUrl, fetchImpl?)    → FetcherMe
aplicarEstadoLogado(fetcher, doc?)    → Promise<{ logado: boolean }>
```

Faz `GET /cliente/auth/me` com `credentials: 'include'`. Em caso de 200, ativa `#nav-logado` e oculta `#nav-deslogado` via `classList`. O `fetchImpl` injetável permite testes com mock sem alterar o global `fetch`.

---

### `redirect.ts` — Segurança pós-login

Valida o parâmetro `?next=` antes de redirecionar após login:

```typescript
resolverDestinoPosLogin(query: URLSearchParams, fallback: string) → string
```

**Bloqueado:** `http://`, `https://`, `//`, `@`, backslash e qualquer path fora de `/cliente/*` ou `/`.
**Fallback:** `DASHBOARD_URL` quando `?next=` está ausente ou inválido.

Impede open-redirect em qualquer fluxo de autenticação.

---

### `toast.ts` — Notificações

API imperativa para exibir notificações flutuantes:

```typescript
showToast(message: string, options?: { variant?: ToastVariant; durationMs?: number })
  → HTMLElement | null

type ToastVariant = 'success' | 'error' | 'info' | 'warning'
```

Auto-dismiss em 4 segundos por padrão. Requer `<ToastContainer />` presente no DOM (incluído em `Base.astro`).

---

### `tracking.ts` — Telemetria de CTA

Monitora cliques em elementos com `[data-cta]` e emite eventos para o SDK:

```typescript
attachCtaTracking(root: Document | Element, emit: EventEmitter) → () => void
```

Desacoplado do SDK — recebe `emit` como parâmetro, tornando-o testável sem instanciar o SDK. Emite `cta_clicado` com `{ cta: string, path: string }`.

---

### `config.ts` — Constantes de ambiente

```typescript
export const SITE_NAME    = 'DS Playground Analytics'
export const SITE_URL     = import.meta.env.PUBLIC_SITE_URL
export const API_URL      = import.meta.env.PUBLIC_API_URL
export const DASHBOARD_URL = import.meta.env.PUBLIC_DASHBOARD_URL
export const PUBLISHABLE_KEY = import.meta.env.PUBLIC_PUBLISHABLE_KEY
export const DEBUG        = import.meta.env.PUBLIC_DEBUG === 'true'
```

---

## Testes

```bash
npm test          # vitest run (uma vez)
npm run test:watch # vitest --watch
```

| Suite | Cobertura |
|---|---|
| `src/lib/api.test.ts` | `cadastrar`, `login`, `alterarEmail`, `alterarSenha`, `listarExports` — mock fetch injetável |
| `src/lib/nav-auth.test.ts` | `aplicarEstadoLogado`, swaps DOM `#nav-logado`/`#nav-deslogado`, mock fetcher |
| `src/lib/redirect.test.ts` | `resolverDestinoPosLogin` — open-redirect blocking, paths permitidos |
| `src/lib/toast.test.ts` | `showToast` — variantes, auto-dismiss, controle de timer |
| `src/lib/tracking.test.ts` | `ctaFromTarget`, `attachCtaTracking` — mock emit, bubbling |
| `src/components/ui/ui.test.ts` | Componentes UI — renderização e props |
| `src/tests/pages.test.ts` | Sanidade de páginas |

Environment: `happy-dom 20` (inclui fix de CVE crítico da versão anterior).

---

## Variáveis de ambiente

Todas as variáveis são **públicas** — embutidas no bundle JavaScript em tempo de build. Não armazene segredos aqui.

| Variável | Obrigatório | Default | Descrição |
|---|---|---|---|
| `PUBLIC_SITE_URL` | Sim | `https://dsplayground.com.br` | URL canônica — canonical, OG tags, sitemap |
| `PUBLIC_API_URL` | Sim | `https://api.dsplayground.com.br` | Endpoint do backend de auth e ingestão |
| `PUBLIC_DASHBOARD_URL` | Sim | `https://app.dsplayground.com.br/cliente/metricas` | URL base do dashboard autenticado |
| `PUBLIC_PUBLISHABLE_KEY` | Não | `""` | Publishable key da landing para dogfood SDK |
| `PUBLIC_DEBUG` | Não | `false` | Ativa logs do SDK no console |

Copie `.env.example` para `.env` e ajuste para o ambiente local.

---

## Desenvolvimento local

### Pré-requisitos

- Node.js 20+
- Token GitHub com `read:packages` para instalar o SDK do GitHub Packages
- Backend rodando localmente ([DSPlayAnalytics/backend] `privado`

### Instalação

```bash
# Autenticar no GitHub Packages
export NODE_AUTH_TOKEN=$(gh auth token)

npm install

cp .env.example .env
# Edite .env: PUBLIC_API_URL=http://localhost:5000
```

### Comandos

```bash
npm run dev      # Servidor de desenvolvimento — http://localhost:4321
npm run build    # Build estático → dist/
npm run preview  # Preview do build gerado localmente
npm run check    # astro check + tsc --noEmit
npm test         # Vitest — execução única
```

---

## Build e deploy

### Dockerfile (multi-stage)

```dockerfile
# Stage 1 — build
FROM node:25-bookworm-slim AS build
ARG PUBLIC_SITE_URL PUBLIC_API_URL PUBLIC_DASHBOARD_URL PUBLIC_PUBLISHABLE_KEY PUBLIC_DEBUG
RUN npm ci && npm run build

# Stage 2 — runtime
FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
```

As variáveis `PUBLIC_*` são passadas como `ARG` e embutidas no bundle durante o `npm run build` do Stage 1. Não persistem na imagem final.

### Cloudflare Pages

| Configuração | Valor |
|---|---|
| Build command | `npm run build` |
| Build output | `dist/` |
| Node version | 20+ |
| `NODE_AUTH_TOKEN` | PAT GitHub com `read:packages` (necessário para instalar o SDK) |
| `PUBLIC_*` | Configurar no dashboard de variáveis de ambiente do CF Pages |

O deploy é automático a cada push em `main`.

---

## Repositórios relacionados

| Repositório | Descrição |
|---|---|
| [DSPlayAnalytics/SDK](https://github.com/DSPlayAnalytics/SDK) | SDK de analytics para browsers — instrumentação de eventos |

---

## Licença

MIT © [DSPlay Analytics](https://dsplayground.com.br)
