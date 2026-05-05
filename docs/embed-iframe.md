# Embed via iFrame — Roadmap e Design Doc

> Status: **Fase 1 LIVE em prod (2026-05-01)** — backend `/embed/*` +
> vhost `embed.dsplayground.com.br` + landing `/embed-test` deployados.
> Validado ponta-a-ponta: widget renderiza Chart.js em ~120ms dentro de
> iframe no apex. Proximos passos = Fase 2 (cliente piloto) quando houver
> demanda real.
> Escopo: permitir que clientes do `dsplayground` embarquem graficos nossos
> em sites/dashboards proprios via `<iframe>`, virando feature de assinatura.

## Gotchas conhecidos da Fase 1 (2026-05-01)

Pegadinhas descobertas durante o dogfood — registrar pra Fase 2 nao repetir:

1. **Sandbox do iframe precisa de `allow-same-origin`.** Sem ele, browser
   trata o documento dentro do iframe como opaque origin (`null`) e
   bloqueia o fetch dos proprios `/assets/*.js` + `.css` por CORS. CSP
   `frame-ancestors` no `embed.X` ja garante isolamento contra parent;
   `allow-same-origin` so libera o widget acessar seus proprios bundles.
2. **Repo do landing e separado** (`danpqdan/comercial`, projeto CF Pages).
   Mudancas em `landing/` aqui no `portifolio` sao espelho — precisa
   replicar pro `comercial` pra chegar em prod. Considerar consolidar
   na Fase 2.
3. **`PUBLIC_SITE_URL` truncado quebra build CF Pages silenciosamente**
   (`astro.config.mjs` valida `site:` como URL). Sintoma: deploys param
   de aparecer em prod sem error visivel — verificar logs do CF Pages
   se `/embed-test` ou similar nao subir.
4. **SDK de analytics nao deve rodar em `/widget/`** — `App.jsx` chamava
   `iniciarAnalytics()` em top-level. Resultado eram 403 `/auth/sdk-token`
   + violacao `connect-src` no widget. Fix: guard `pathname.startsWith('/widget/')`.
5. **Modelo de auth atual e "user dono do site_id"** — admin nao consegue
   embedar graficos de outro site sem ser explicitamente adicionado como
   user via `dashboard_user_admin.py add`. Funciona pra dogfood; pra
   feature comercial (Fase 3) precisa de papel "owner global" ou
   self-service.
6. **Cloudflare Web Analytics injeta beacon** que viola CSP `script-src`
   no `embed.X`. Nao bloqueia widget mas polui console. Solucao:
   adicionar `https://static.cloudflareinsights.com` no `script-src`
   ou desabilitar Web Analytics no projeto Pages. Nao urgente.

## Estado Fase 1 (implementado em dev)

| Peca | Local | Status |
|------|-------|--------|
| `EmbedJwtService` (RS256, aud dedicada) | `backend/auth/embed_jwt_service.py` | ✅ |
| Blueprint `/embed/token` + `/embed/dados` | `backend/embed_routes.py` | ✅ |
| Registro no app.py (init com keys_dir compartilhado) | `backend/app.py` | ✅ |
| Testes unit + integration backend | `backend/test_embed_routes.py` (12 verde) | ✅ |
| Widget React em `/widget/:siteId/:graficoId` | `frontend/src/pages/EmbedWidget.jsx` | ✅ |
| Chart.js + react-chartjs-2 instalados | `frontend/package.json` | ✅ |
| Testes vitest do widget | `frontend/src/testes/EmbedWidget.test.jsx` (6 verde) | ✅ |
| Pagina dogfood `/embed-test` | `landing/src/pages/embed-test.astro` | ✅ |
| vhost nginx `embed.{{ dominio }}` | `ark/ansible/roles/nginx/templates/portifolio.conf.j2` + espelho `ark/nginx/portifolio.conf` | ✅ |

**Pendencias de ativacao — TODAS resolvidas em 2026-05-01:**

- ✅ DNS Cloudflare `embed.dsplayground.com.br` (proxiado)
- ✅ CORS `https://embed.dsplayground.com.br` em `cors_origins` do vault
- ✅ `PUBLIC_PORTIFOLIO_SITE_ID=9f35343c-2480-4e2f-910a-ad325af2eee2` no CF Pages
- ✅ vhost nginx aplicado via `make ansible-apply`
- ✅ Backend + frontend deployados via CD (`deploy.yml`)
- ✅ Espelho da pagina `/embed-test` aplicado no repo `danpqdan/comercial`
- ✅ Smoke ponta-a-ponta validado: widget renderiza Chart.js em ~120ms

**Pendencias residuais (nao bloqueantes):**

- 🟡 Cloudflare Web Analytics injeta beacon que viola CSP `script-src` do
  `embed.X`. Solucao opcional: adicionar `https://static.cloudflareinsights.com`
  no `script-src` do vhost ou desabilitar Web Analytics no projeto CF Pages.
  Nao bloqueia widget.
- 🟡 Bundle do `frontend` ainda contem chamada `iniciarAnalytics()` em
  top-level que vaza pra rota `/widget/`, causando 403 em `/auth/sdk-token`
  + violacao `connect-src` (wss). Guard em `frontend/src/App.jsx` foi
  adicionado em PR mas precisa CD redeploy pra hash novo do bundle. Nao
  bloqueia widget — so polui console.

**Smoke test pos-deploy:**

```bash
# 1. Logar em https://dsplayground.com.br/cliente/login
# 2. Em sessao logada:
curl -i -b 'cliente_session=...' https://api.dsplayground.com.br/embed/token \
  -H 'Content-Type: application/json' \
  -d '{"site_id":"<portifolio-site-id>","grafico_id":"eventos_por_minuto"}'
# 3. Pegar token retornado e abrir:
#    https://embed.dsplayground.com.br/widget/<site>/eventos_por_minuto?token=<jwt>
# 4. Browser deve renderizar grafico. Testar embed em
#    https://dsplayground.com.br/embed-test (precisa estar logado).
# 5. Validar bloqueio de embed cross-domain: criar pagina HTML em
#    qualquer outro host com <iframe src=...> do widget — browser deve
#    bloquear via CSP frame-ancestors. Console mostra violation report.
```

## Motivacao

Hoje os graficos vivem so dentro de `app.dsplayground.com.br/cliente/metricas/*`
(Grafana com `auth.proxy`). Cliente que quer mostrar metricas em pagina propria
nao tem caminho — precisa logar no nosso dashboard.

Abrir embed cross-domain agrega valor de assinatura ("seus dados onde voce quiser")
e diferencia o produto sem precisar reimplementar o layer de coleta. Mas hoje o
servidor esta **fechado por default**: `X-Frame-Options: SAMEORIGIN` global em
`ark/nginx/ssl.conf:21` rejeita qualquer embed cross-site, e nao ha
`Content-Security-Policy` em lugar nenhum.

## Decisoes ja tomadas

**1. Widget React proprio em `frontend/`** (nao iframe direto do Grafana).

URL canonica do embed: `https://embed.dsplayground.com.br/widget/<site_id>/<grafico_id>?token=<jwt>`.

Por que widget proprio:
- Isola do Grafana — nao precisa mexer em `auth.proxy`, `GF_SECURITY_ALLOW_EMBEDDING`,
  nem em `cookie_samesite=none`.
- Cookie `cliente_session` (SameSite=Strict) nao entra em jogo — auth e via token
  na URL, nao via sessao de browser.
- Da liberdade de UI: layout enxuto pra embed (sem chrome do Grafana), branding
  configuravel por plano.
- Aprendizado vira contrato pro caso "embed do Grafana cru" como tier premium
  futuro (ver Fase 3d).

**2. Auth: JWT short-lived na URL.**

Token assinado com scope `embed:<site_id>:<grafico_id>`, TTL 5–10 min, emitido
por `api.dsplayground.com.br/embed/token` autenticado pelo cookie `cliente_session`
do dono da conta. Sem cookie no iframe → sem CSRF novo, sem SameSite=None.

Reusa padrao do `sdk_jwt` (chave RSA em `/app/data/keys/`, ja persistida no
volume `portifolio_backend_keys`).

## Fase 1 — Dogfood interno

**Objetivo:** validar fluxo completo (CSP + token + widget) embedando em pagina
de teste do **proprio dominio** antes de abrir pra cliente externo.

### Mudancas de infra

- `ark/nginx/ssl.conf:21`: remover `X-Frame-Options: SAMEORIGIN` global. Mover
  pra cada vhost que precisa, **menos** `embed.X`.
- vhosts `api.X`, `app.X`, `grafana.X`, `influx.X`: adicionar
  `add_header Content-Security-Policy "frame-ancestors 'none'" always;` (substitui
  o XFO antigo, e mais expressivo).
- vhost novo `embed.dsplayground.com.br` (Cloudflare DNS proxiado, mesmo Origin Cert):
  - `add_header Content-Security-Policy "frame-ancestors 'self' https://*.dsplayground.com.br" always;`
  - `proxy_pass` pro container `portifolio-frontend` (porta 3000), serve a build
    Vite com rotas `/widget/*`.
- vhost `portifolio.X` (showcase): cria pagina `/embed-test` com 2-3 iframes
  apontando pra `embed.X/widget/...` — primeiro consumidor real.

### Mudancas de backend

- Endpoint `POST /embed/token` em `api.X`:
  - Requer cookie `cliente_session` valido.
  - Body: `{ "site_id": "<uuid>", "grafico_id": "<slug>", "ttl_segundos": 600 }`.
  - Valida que o `cliente_session.user.org_id` e dono do `site_id`
    (mesmo check do dashboard hoje).
  - Retorna `{ "token": "<jwt>", "expira_em": <unix_ts> }`.
  - Rate-limit dedicado: 30/min por `cliente_session.user_id`.
- Endpoint `GET /embed/dados/<site_id>/<grafico_id>` em `api.X`:
  - Auth: `Authorization: Bearer <jwt>` (token de embed, nao `sdk_jwt`).
  - Valida assinatura, scope, expiracao, e que `site_id`/`grafico_id` casa com o claim.
  - Retorna JSON com series temporais (proxy pro Influx, mesma logica do
    `/cliente/metricas` mas sem Grafana no meio).
  - CORS: aceita Origin `https://embed.dsplayground.com.br` (estatico nessa fase).

### Mudancas de frontend

- Rota `/widget/:site_id/:grafico_id` em `frontend/src/`:
  - Le `?token=` da query.
  - Fetch em `api.X/embed/dados/...` com `Authorization: Bearer`.
  - Renderiza grafico (reusa lib que ja usamos no `ClienteMetricas.jsx` se possivel,
    senao Recharts/Chart.js — escolher na implementacao).
  - Trata erro de token expirado: dispara `postMessage({ tipo: 'embed.token_expirado' })`
    pro parent, parent renova via `/embed/token` e atualiza `src` do iframe.

### Pagina de teste em `portifolio.X/embed-test`

```html
<iframe src="https://embed.dsplayground.com.br/widget/<site_id_real>/eventos_por_minuto?token=<token_emitido_via_curl>"
        width="600" height="300" sandbox="allow-scripts allow-same-origin"></iframe>
```

### Criterios de saida da Fase 1

- [ ] iframe renderiza grafico em `portifolio.X/embed-test` em sessao logada.
- [ ] iframe **falha** ao tentar embedar fora de `*.dsplayground.com.br` (testar
      em CodePen/JSFiddle — browser tem que bloquear via CSP).
- [ ] Token expirado dispara fluxo de renovacao via `postMessage` sem reload
      manual.
- [ ] `embed.X` nao expoe `/widget` sem token (deve retornar 401 server-side ou
      pagina de erro client-side).
- [ ] Lighthouse score do widget > 90 (performance + best-practices).

## Fase 2 — Cliente piloto

**Objetivo:** liberar embed pra 1–2 clientes reais validarem fluxo end-to-end.
Continuamos no widget proprio (mesmo da Fase 1) — muda so a politica de
`frame-ancestors` (estatica → dinamica).

### Mudancas

- **`frame-ancestors` dinamico**: mover header do nginx pro Flask. Novo hook
  `@app.after_request` (ao lado de `cors_dinamico_resposta` em
  `backend/app.py:408`) consulta `OriginsDinamicos` (ja existe, ver
  `backend/auth/origins_dinamicos.py`) e adiciona
  `Content-Security-Policy: frame-ancestors <lista>` na response do `/widget/*`.
  - Lista vem de `sites.dominios_permitidos` no Postgres — mesma fonte do CORS
    dinamico. So um lugar pra editar quando cliente adiciona novo dominio.
- **Throttle**: rate-limit no `/embed/token` agora considera `site_id` tambem
  (nao so `user_id`) — evita cliente abusar.
- **Audit log**: cada emissao de token vira linha em
  `backend/security.log` com `evento=embed_token_emitido site_id=<x> dominio=<y>`.
  CrowdSec ja le esse arquivo — facil escrever cenario de abuse pattern depois.
- **Onboarding manual**: admin ainda edita `dominios_permitidos` direto via SQL
  ou CLI `provisionar_cliente.py`. Self-service fica pra Fase 3.

### Criterios de saida da Fase 2

- [ ] 2 clientes piloto rodando embed estavel por **2 semanas**.
- [ ] Zero incidente de bypass (browser consegue embedar de dominio nao listado).
- [ ] Latencia p95 do `/embed/dados` < 500ms.
- [ ] Metricas no Prometheus: `embed_tokens_emitidos_total{site_id}`,
      `embed_dados_requisicoes_total{site_id,status}`.

## Fase 3 — GA + monetizacao

**Pre-requisito:** Fase 2 validada. Sem isso, UI da Fase 3 reflete
especulacao em vez de necessidade real.

### 3a. Self-service de dominios e embeds

UI nova em `app.dsplayground.com.br/cliente/configuracao/embeds`:

- CRUD de `dominios_permitidos` (hoje so editavel via admin/SQL).
- Lista de graficos disponiveis pra embed (alimentada pelo schema do dashboard
  do cliente).
- Gerador de snippet: clica num grafico + escolhe dominio → copia HTML
  `<iframe src=...>` pronto. Token e emitido server-side ao montar a pagina
  do cliente (snippet inclui pequeno script que chama `/embed/token` antes
  de injetar o iframe).
- Lista/revogacao de tokens ativos (hoje TTL curto ja resolve, mas revogacao
  explicita ajuda quando cliente perde controle de um dominio).

### 3b. Billing e quotas formais

Adicionar em `quotas` (mesmo schema de `quotas.eventos_por_dia`):

| Coluna | Significado |
|---|---|
| `embed_dominios_max` | Quantos dominios distintos podem estar em `dominios_permitidos` |
| `embed_views_mes` | Quantos page-loads de iframe sao permitidos por mes |
| `embed_graficos_max` | Quantos graficos distintos podem ser embedados |

Enforcement:
- `/embed/token` nega emissao com `code=QUOTA_EXCEDIDA` quando passa de
  `embed_views_mes`.
- UI da Fase 3a bloqueia adicao de dominio acima de `embed_dominios_max`.
- Tier sem embed = `embed_dominios_max=0` → endpoint sempre nega.

Metrica de uso vira gancho pra upgrade prompt (email/in-app quando bate 80%).

### 3c. Observabilidade e abuse-prevention

- Metricas Prometheus por `site_id`:
  - `embed_tokens_emitidos_total`
  - `embed_widget_loads_total` (postMessage do widget pro backend, opt-in)
  - `embed_erros_total{tipo=token_expirado|token_invalido|origem_negada}`
  - `embed_render_latencia_seconds` (medido no widget, enviado via beacon)
- Audit log de mudancas em `dominios_permitidos`:
  tabela `auditoria_dominios_permitidos (site_id, dominio, acao, ator_user_id, timestamp)`.
  Compliance + forense quando cliente reclama de remocao indevida.
- Rate-limit dedicado em `/embed/token` por `site_id` (nao so IP) — protecao
  contra cliente comprometido emitindo tokens em massa.
- Alarme automatico se `embed_erros_total{tipo=origem_negada} > 100/min` por
  `site_id` (sintoma de dominio nao autorizado tentando embedar — pode ser
  ataque ou config errada do cliente).

### 3d. (Opcional) tier premium: Grafana embed cru

Depois que widget proprio rodou bem, oferecer "embed do painel completo do
Grafana" como tier mais caro:

- `auth.proxy` do Grafana ja existe, mas confia em header `X-WEBAUTH-USER`
  setado pelo nginx apos validar cookie. Pra embed cross-site, trocar pra
  validar JWT (mesmo do widget) e setar `X-WEBAUTH-USER` a partir do claim.
- Ligar `GF_SECURITY_ALLOW_EMBEDDING=true` e `GF_SECURITY_COOKIE_SAMESITE=none`
  no `ark/monitoring/docker-compose.monitoring.yml`.
- vhost `app.X` ganha excecao no `frame-ancestors` pra dominios premium.
- Justifica preco mais alto: cliente ganha o painel completo do Grafana
  (interatividade, drill-down, time-range picker) sem reimplementar nada
  do nosso lado.

Decisao de fazer ou nao a 3d depende da demanda dos clientes piloto. Sem pedido
explicito, ficar so com widget proprio ja entrega 80% do valor.

## Contratos tecnicos

### Shape do JWT de embed

```json
{
  "iss": "dsplayground.com.br",
  "sub": "embed:<site_id>:<grafico_id>",
  "aud": "embed.dsplayground.com.br",
  "exp": 1735689600,
  "iat": 1735689000,
  "site_id": "uuid",
  "grafico_id": "eventos_por_minuto",
  "user_id": "uuid_do_dono",
  "scope": "embed:read"
}
```

Assinado com a mesma chave RSA do `sdk_jwt` (volume `portifolio_backend_keys`).
Algoritmo: `RS256`. Claim `aud` separado garante que token de embed nao serve
pra autenticar SDK (e vice-versa).

### Headers HTTP

Em `embed.dsplayground.com.br/widget/*`:

| Header | Valor |
|---|---|
| `Content-Security-Policy` | `frame-ancestors <dominios dinamicos>; default-src 'self'; script-src 'self' 'unsafe-inline'; ...` |
| `X-Frame-Options` | **nao enviar** (CSP `frame-ancestors` substitui; XFO atrapalha porque so aceita unica origem) |
| `Referrer-Policy` | `strict-origin-when-cross-origin` |
| `X-Content-Type-Options` | `nosniff` |

Em `api.dsplayground.com.br/embed/dados/*`:

| Header | Valor |
|---|---|
| `Access-Control-Allow-Origin` | `https://embed.dsplayground.com.br` (estatico) |
| `Access-Control-Allow-Credentials` | `false` (token vai em Authorization, nao cookie) |
| `Cache-Control` | `private, max-age=30` (cliente pode cachear no browser) |

### postMessage entre widget e parent

Eventos do widget → parent:

```ts
{ tipo: 'embed.pronto', site_id, grafico_id, render_ms }
{ tipo: 'embed.erro', codigo: 'token_expirado'|'sem_dados'|'erro_servidor' }
{ tipo: 'embed.token_expirado' }  // parent deve renovar via /embed/token
```

Parent → widget:

```ts
{ tipo: 'embed.token_renovado', token: '<novo_jwt>' }
{ tipo: 'embed.tema', cores: {...} }  // futuro: customizacao por plano
```

`origin` do `postMessage` deve ser sempre validado em ambos os lados.

## Riscos e decisoes em aberto

- **Library de chart**: Recharts (ja no projeto?) vs. ECharts (mais features) vs.
  Chart.js (mais leve). Decidir na primeira PR da Fase 1 — afeta bundle size do
  widget e diferencia tier premium.
- **Tema do widget**: configuravel por cliente (via plano)? Pra MVP da Fase 1,
  fixar tema dark + branding `dsplayground` so.
- **Cardinalidade de tokens**: TTL 10min + 1 token por (site_id, grafico_id, user_id)
  → cache em Redis ou so reemitir? Sem Redis no stack, reemitir e mais simples
  pra Fase 1; revisitar se gerar custo notavel.
- **Sandbox do iframe**: cliente esquece `sandbox=` no HTML → widget tem acesso
  ao window do parent. Mitigar com `Cross-Origin-Resource-Policy: same-site`
  no widget, e documentar boas-praticas no snippet gerado pela Fase 3a.
- **Dominio do embed**: `embed.dsplayground.com.br` (subdomain dedicado, isolamento
  de cookies por origin) vs. path em `app.X` (menos DNS, mas compartilha cookies).
  Subdomain ganha — mantem `cliente_session` longe do widget.

## Referencias

- CORS dinamico (mesmo padrao que sera usado pra `frame-ancestors` na Fase 2):
  `backend/auth/origins_dinamicos.py` + hook em `backend/app.py:408`.
- Fonte da arquitetura geral: `ark/docs/servidor-producao.md`.
- Auth do dashboard (modelo de cookie/sessao que **nao** sera usado no embed):
  `ark/docs/dashboard-cliente.md`.
- Headers de seguranca atuais: `ark/nginx/ssl.conf`.
- Schema multi-tenant + `dominios_permitidos`:
  `backend/auth/schema_dashboard_postgres.sql`.
