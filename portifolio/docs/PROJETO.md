# PROJETO — DS Playground Analytics

> Estado canônico consolidado em **2026-04-29**. Substitui os 16 docs anteriores em
> `/docs` (histórico em git). Detalhes operacionais profundos vivem em
> `CLAUDE.md`, `ark/docs/dashboard-cliente.md` e `ark/docs/servidor-producao.md` —
> este arquivo é o ponto de entrada e o resumo do estado atual.

## Sumário

0. [Como ler este documento](#0-como-ler-este-documento)
1. [Estado atual — TL;DR](#1-estado-atual--tldr)
2. [Arquitetura](#2-arquitetura)
3. [SDK de analytics (`@danpqdan/dsplayground-analytics-sdk`)](#3-sdk-de-analytics)
4. [Backend — ingestão e persistência](#4-backend--ingestão-e-persistência)
5. [Backend — API de consulta + admin LGPD](#5-backend--api-de-consulta--admin-lgpd)
6. [Multi-tenant e dashboard do cliente](#6-multi-tenant-e-dashboard-do-cliente)
7. [Landing comercial e self-service signup](#7-landing-comercial-e-self-service-signup)
8. [Operação e deploy](#8-operação-e-deploy)
9. [Capacidade e escalabilidade](#9-capacidade-e-escalabilidade)
10. [Pendências priorizadas](#10-pendências-priorizadas)
11. [Onde está cada coisa (mapa)](#11-onde-está-cada-coisa)
12. [Apêndice — bug fixes históricos](#12-apêndice--bug-fixes-históricos)

---

## 0. Como ler este documento

**Status legend** usado em tabelas:
- ✅ — implementado e em produção (branch `dev` ou `main`)
- 🚧 — em andamento ou parcialmente implementado
- 🟡 — pendente, planejado, prioridade média
- 🔴 — pendente bloqueando algo
- 📐 — referência viva (não tem ciclo de vida — atualizar conforme schema/contrato muda)

**Fontes de verdade** (em ordem de precedência quando há conflito):
1. **Código** em `backend/`, `frontend/`, `landing/`, `ark/`
2. **`CLAUDE.md`** (raiz) — comandos operacionais e regras pra agentes
3. **`ark/docs/dashboard-cliente.md`** — design do produto comercial multi-tenant
4. **`ark/docs/servidor-producao.md`** — VPS, hardening, deploy
5. **Este arquivo (`docs/PROJETO.md`)** — síntese e ponteiros

Se contradisser código, atualize código + este doc no mesmo commit.

---

## 1. Estado atual — TL;DR

**Produto:** plataforma SaaS de analytics first-party (Web Vitals + eventos custom + dashboard pronto), com bucket dedicado por cliente. Branding: "DS Playground Analytics".

**Stack rodando em produção** (branch `dev`, 8 containers):

| Camada | Tecnologia | Onde está |
|---|---|---|
| Landing comercial (apex) | Astro 4 + Tailwind 3 (estático) | `landing/` |
| Portfolio pessoal (subdomínio) | React 19 + Vite | `frontend/` |
| Backend ingestão + REST | Flask + Socket.IO + gunicorn(eventlet) | `backend/` |
| TS DB | InfluxDB 2.7 (bucket-per-cliente) | `portifolio_influxdb` |
| Auth multi-tenant | Postgres 16 | `portifolio_postgres` |
| Métricas (operação) | Prometheus + node-exporter | `ark/monitoring/` |
| Dashboards do cliente | Grafana 11 (auth.proxy) | `portifolio_grafana` |
| Anti-abuse | CrowdSec + nginx bouncer | `ark/crowdsec/` |
| SDK público | npm `@danpqdan/dsplayground-analytics-sdk@^0.3.1` | repo separado, GitHub Packages |

**O que funciona end-to-end:**
- Coleta SDK → WebSocket → backend → Influx (bucket-per-cliente, validado, com quotas/cardinalidade)
- API REST de consulta (`/analytics/metricas`, `/web-vitals`, `/custom-events`)
- Self-service signup pela landing (`POST /cliente/auth/cadastro`)
- Login + cookie HttpOnly → `/cliente/metricas` (Grafana via auth_request)
- LGPD admin (GET/DELETE por sessão, audit log)
- Deploy via Ansible + GitHub Actions self-hosted runner (CD em `main`)
- 211 testes backend verde + 15 testes landing verde

**Pendências relevantes:** ver §10. Em uma frase: trigger de provisionamento Influx/Grafana pós-cadastro, Onda 2/3 do contrato SDK↔Backend (backpressure dinâmico), Prometheus `/metrics` no backend, multi-cliente CORS dinâmico.

---

## 2. Arquitetura

```
                        Internet (Cloudflare proxy, Full strict, Origin Cert 2041)
                                          │
                          ┌───────────────┴────────────────┐
                          ▼                                ▼
                  Cloudflare Pages                   Nginx host (80/443)
                  (repo `comercial`)            ┌─────────┼─────────┐
                  dsplayground.com.br (apex)    ▼         ▼         ▼
                  • landing comercial Astro    app.X  portifolio.X api.X
                                                │         │         │
                                                ▼         ▼         ▼
                                   /cliente/metricas → React 3D    backend Flask
                                   auth_request →     (portfolio    + Socket.IO
                                   Grafana (3001)     pessoal)
                                          │
                                          ▼
                                  portifolio-grafana
                                  (auth.proxy via X-WEBAUTH-USER)
                                          │
                                          ▼
                                  influxdb (bucket-per-cliente)
                                  + postgres (auth multi-tenant)

   Cookie cliente_session: HttpOnly + Secure + SameSite=Strict + Domain=dsplayground.com.br
   (var COOKIE_DOMAIN no Ansible) — viaja entre apex (landing), app.X (dashboard) e api.X.
```

**Princípios de segurança:**
- Backend, Influx, Postgres, Grafana, Prometheus bindam em `127.0.0.1:*` — só nginx alcança.
- TLS via Cloudflare Origin Cert (válido até 2041, modo Full strict).
- Cookies de sessão: HttpOnly + Secure + SameSite=Strict + sha256-hash server-side (plaintext nunca persiste).
- Tokens SDK: JWT 5min TTL, escopo `ingest`, derivado de `publishable_key` (que é pública por design).

**Detalhes profundos:** `ark/docs/servidor-producao.md` (fonte canônica), `CLAUDE.md` (comandos operacionais), `ark/docs/dashboard-cliente.md` (auth multi-tenant).

---

## 3. SDK de analytics

**Pacote:** `@danpqdan/dsplayground-analytics-sdk@^0.3.1` (privado em GitHub Packages, repo separado).

### 3.1 Inicialização

```ts
import { iniciarAnalytics, enviarEvento } from '@danpqdan/dsplayground-analytics-sdk';

iniciarAnalytics({
  websocketUrl: 'https://api.dsplayground.com.br',
  appId: 'minha-loja',
  ambiente: 'production',
  publishableKey: 'pk_production_...',  // gerado via tenant_admin.py
  intervaloEnvioMs: 5000,
  debug: false,
});

enviarEvento('checkout_iniciado', { valor: 49.90, produtos: 2 });
```

`appId` e `ambiente` viram tags no envelope; `publishableKey` é trocada por JWT via `/auth/sdk-token` (5min TTL, rate-limit 5/min). Sem `publishableKey` o SDK opera no bucket default (só dev).

### 3.2 Catálogo de eventos (📐 contrato vivo)

Tipos coletados automaticamente:

| Evento | Quando | Tags whitelist |
|---|---|---|
| `page_view` | Mudança de URL | `page_type`, `device_type`, `pais`, `referrer_dominio` |
| `page_exit` | beforeunload | mesmas |
| `click` / `touch` | Interação | `elemento_id` (cascata: `data-analytics-id` > `id` > `aria-label` > classe > tag) |
| `scroll_depth` | 25/50/75/100% | `pct` como tag, `pixels` como field |
| `mouse_move` | Amostrado (5pts/s default) | x/y como fields |
| `hover` | Cursor parado >500ms | `elemento_id` |
| `element_exposure` | IntersectionObserver | `elemento_id`, `pct_visivel` |
| `web_vital` | LCP/INP/CLS/FCP/TTFB | `nome`, `rating` (good/needs-improvement/poor) |
| `custom` | `enviarEvento(nome, props)` | `nome` |

**Nunca coletados sem opt-in explícito:** `innerText`, valores de inputs, querystring completa, fingerprints de browser.

### 3.2.1 Modelo de página ativa (gotcha histórico)

`enviarEvento()` e os callbacks de Web Vitals empilham eventos via `HeatmapUtils.empilharEventoNoAtivo`, que precisa de **uma instância de `HeatmapUtils` em estado `iniciar()`** registrada como buffer global. Sem isso, o evento seria perdido — bug que afetou produção até **v0.3.1**.

A partir de v0.3.1 o SDK enfileira em `eventosPendentes` (cap 100) eventos disparados antes do primeiro `iniciar()`, drenando-os pra página ativa quando ela mounta. Preserva o early signal (LCP candidato inicial, `app_carregado` no module-load) sem mudança no consumer. **Contrato:** `enviarEvento(...)` retorna `true` quando enfileira sem página ativa (em vez de `false` como em ≤0.3.0).

**Padrão recomendado para consumer novo** (Astro/Vite/HTML estático): instanciar `HeatmapUtils` logo após `iniciarAnalytics`:

```ts
import { iniciarAnalytics, enviarEvento, HeatmapUtils, WebSocketService } from '@danpqdan/dsplayground-analytics-sdk';

iniciarAnalytics({...});
const heatmap = new HeatmapUtils(document.body, null, location.pathname);
heatmap.configurarColecaoTempoReal((d) => WebSocketService.sendAnalyticsDataImmediate(d, false), 5000);
heatmap.iniciarColecaoTempoReal();
heatmap.iniciar();
WebSocketService.connect();
```

Ver `frontend/src/classe/ClasseHome.jsx` (per-rota) e `landing/src/layouts/Base.astro` (global em layout) como referências canônicas.

### 3.3 Fila offline + entrega

- **IndexedDB** com fallback localStorage; FIFO; limite configurável.
- Reenvio após reconexão Socket.IO (handshake reidentifica `appId` + JWT).
- ACK estruturado do backend: `{ status, received, schema_version }` ou `{ status: 'error', code, fields }`.

### 3.4 Estado de implementação

| Item | Status | Onde |
|---|---|---|
| `iniciarAnalytics()` + envelope | ✅ | SDK repo, `frontend/src/sdk/iniciarAnalytics.ts` (legado) |
| Coleta temporal (5s tick) | ✅ | `HeatmapUtils.tsx` |
| Normalização de elementos | ✅ | `frontend/src/sdk/normalizadores/` |
| Fila offline IndexedDB | ✅ | `frontend/src/sdk/filaAnalytics.ts` |
| Validação de payload + ACK estruturado | ✅ | `backend/ingestao/validador.py` |
| **Onda 1**: idempotência + ACK confirmado + retry exponencial | 🚧 parcial | fila tem retry simples; falta exponential backoff + dead-letter |
| **Onda 2**: validação de timestamp + skew correction + overflow priority | 🟡 | planejado em `plano-garantias-sdk-backend.md` (incorporado abaixo) |
| **Onda 3**: backpressure dinâmico (`ok`/`slow`/`stop`) + schema version negotiation | 🟡 | depende de Onda 1+2 |

### 3.5 Onda 2 e 3 — contrato de confiabilidade SDK↔Backend (planejamento)

**Onda 1 — entrega confiável** (em progresso):
- Cache LRU de `(site_id, id_registro)` no backend → idempotência.
- ACK confirmed com retry exponencial (1s → 2s → 4s → 8s, max 4 tentativas, timeout 10s).
- Resync pós-reconnect rastreando `last_received_id_registro`.
- Novo formato de ACK com `resumo` e `retriable: bool`.

**Onda 2 — dados limpos:**
- Rejeitar `timestamp_inicial` fora da janela `[server_time - 24h, server_time + 5min]`.
- Correção de skew via `server_time` no handshake (cliente ajusta delta).
- Fila overflow → emite evento interno `analytics:queue_overflow` + descarta em ordem de prioridade: `mouse_move` → `hover` → `scroll` → `click` → `page_view` (page_view nunca descartado).
- Itens que esgotaram tentativas vão pra `dead_letter` (localStorage, máximo 100, com TTL 24h).

**Onda 3 — coordenação dinâmica:**
- ACK carrega `backpressure_hint`: `ok` (segue), `slow` (dobra `intervaloEnvioMs`), `stop` (pausa por 30s).
- Schema version negotiation no `connect`: cliente envia `schema_version`, backend responde com `min`/`max` aceito; mismatch → erro estruturado pro cliente atualizar.

**Testes de aceite por onda:** especificados em §10 (pendências); fixtures em `backend/fixtures/`.

---

## 4. Backend — ingestão e persistência

### 4.1 Schema InfluxDB (📐)

**3 measurements** (1 bucket por cliente, nome `cliente_<slug>`):

| Measurement | Fields | Tags whitelist | Tags PROIBIDAS |
|---|---|---|---|
| `page_analytics` | cliques, hovers, mouse_moves, toques, scrolls, exposicoes, custom_events, permanencia_segundos, visualizacoes, user_agent, ip_address | `app_id`, `ambiente`, `page_type`, `device_type`, `pais`, `referrer_dominio` | `user_id`, `session_id` (em produto comercial), `email`, `request_id`, `url_completa` |
| `web_vitals` | valor (numérico), user_agent | `app_id`, `ambiente`, `page_type`, `nome` (LCP/CLS/INP/FCP/TTFB), `rating`, `device_type` | mesmas |
| `custom_events` | ocorrencias (count), `<props_primitivas>` como fields | `app_id`, `ambiente`, `page_type`, `nome` | mesmas |

**Semântica de delta:** cada emissão é janela; agregação na query usa `sum()` para contadores. `mean()` em contador NÃO faz sentido (somaria valores absolutos errados).

**Retenção:** definida por plano (free 7d, pequeno 30d, médio 90d, grande 365d) via `influx bucket update --retention=...`. Aplicação via `backend/scripts/configurar_retencao.py`.

**Cardinalidade:** `user_id` ou `session_id` como tag detona o bucket. Validador rejeita server-side; quotas em Postgres limitam séries únicas por cliente.

### 4.2 Tag enforcement (validador)

Implementação: `backend/ingestao/validador.py`. Regras:

- **Obrigatórias** (rejeita se faltar): `app_id`, `ambiente`, `page_type`.
- **Whitelist tags**: `device_type`, `pais` (GeoIP — TODO), `referrer_dominio`, `nome` (custom_events/web_vitals), `rating` (web_vitals).
- **Cardinalidade limit por bucket**: contador `(bucket, tag) → set(values)` em memória + Postgres; ultrapassa limite do plano → rejeita + log `[SECURITY] cardinalidade_excedida`.
- **Eventos rejeitados ainda contam pra quota** (anti-abuso: senão atacante manda 1B eventos inválidos sem custo).

### 4.3 Roteamento de ingest por bucket

```python
# backend/auth/sites_cache.py + backend/ingestao/servico_ingestao.py
bucket = sites_cache.obter_bucket(site_id)  # TTL 5min, cache-aside Postgres
if bucket is None:
    # site sem bucket -> log evento=site_sem_bucket + cai no bucket default
    pass
influxdb_service.write_temporal_metrics_async(metric, bucket=bucket)
```

`SitesCache.obter_bucket()` consulta Postgres `sites.bucket_name`; cache TTL 5min. Após criar cliente novo, chamar `invalidar(site_id)` libera entrada antes do TTL.

### 4.4 Quotas (planejado, parcial)

| Plano | Eventos/mês | Retenção | Sessões/dia | Cardinalidade max | Backup |
|---|---|---|---|---|---|
| free | 10k | 7d | 50 | 1k tag values | ❌ |
| pequeno | 100k | 30d | 500 | 5k | semanal, 1m |
| médio | 1M | 90d | 5k | 50k | diário, 6m |
| grande | 10M | 365d | ilimitado | 500k | diário + arquivo 12m |

Hoje: contagem em `consumo_diario` ✅; **enforcement (rejeitar evento quando passar)** 🟡 ainda não implementado — ver §10.

---

## 5. Backend — API de consulta + admin LGPD

### 5.1 Endpoints públicos (sem auth, rate-limit 30 req/min/IP)

| Endpoint | Resposta |
|---|---|
| `GET /analytics/metricas?app_id=&ambiente=&page_type=&inicio=&fim=&limit=` | Soma de contadores de `page_analytics` |
| `GET /analytics/web-vitals?...` | Pontos de LCP/CLS/INP/FCP/TTFB |
| `GET /analytics/custom-events?...&nome=` | Soma de ocorrências de evento custom |
| `GET /health/app` | App vivo |
| `GET /health/socketio` | Socket.IO ativo |
| `GET /health/influxdb` | InfluxDB acessível |

Códigos: 200 sucesso · 429 rate-limit · 503 InfluxDB indisponível · 403 IP em blocklist.

### 5.2 Endpoints admin LGPD (auth: header `X-Admin-Token: <ADMIN_API_TOKEN>`)

| Endpoint | Ação |
|---|---|
| `GET /admin/analytics/sessao/<session_id>` | Retorna todos os 3 measurements pra aquela sessão |
| `DELETE /admin/analytics/sessao/<session_id>` | Apaga via Influx Delete API |

Cada chamada gera `[ADMIN-AUDIT] acao=... resultado=...` em `security.log` (CrowdSec parseia).

### 5.3 Auth pro dashboard humano (`/cliente/auth/*`)

Detalhes em `ark/docs/dashboard-cliente.md` §6. Sumário:

| Endpoint | Payload | Resposta |
|---|---|---|
| `POST /cliente/auth/cadastro` | `{email,senha,nome_site,slug}` | 201 + cookie OR 400/409 |
| `POST /cliente/auth/login` | `{email,senha}` | 200 + cookie OR 401 |
| `POST /cliente/auth/logout` | — | 200, limpa cookie |
| `GET /cliente/auth/me` | — | `{user_id, site_id, papel}` ou 401 |
| `GET /cliente/auth/gate` | — | 200 + `X-WEBAUTH-USER` ou 401 (nginx auth_request) |
| `POST /cliente/auth/magic-link/solicitar` | `{email}` | sempre 200 (anti-enumeração) |
| `GET /cliente/auth/magic-link/verificar?t=...` | — | 302 → `/cliente/metricas` + Set-Cookie |

Cookie: `cliente_session`, HttpOnly+Secure+SameSite=Strict, sha256-hash server-side, TTL 7d rolando.

### 5.4 Auth multi-cliente do SDK (planejado, parcial)

**4 tipos de credencial:**

| Credencial | Onde vive | Permissão |
|---|---|---|
| `publishable_key` | JS do cliente, embutido no bundle | `scope: ["sdk-token-issue"]` |
| `sdk_jwt` | Cookie/memória SDK, 5min TTL, RS256 | `scope: ["ingest"]` + `site_id` claim |
| `access_token` (REST) | Authorization header, 1h TTL | `scope: ["read:analytics"]` + `site_id` |
| `cliente_session` | Cookie HttpOnly | `scope: ["dashboard"]` + `user_id` |

**Implementado** ✅: `publishable_key`, `sdk_jwt`, `cliente_session`.
**Pendente** 🟡: `access_token` REST (hoje endpoints `/analytics/*` são públicos sem `site_id`).

---

## 6. Multi-tenant e dashboard do cliente

**Fonte canônica completa:** `ark/docs/dashboard-cliente.md` (sec 1-23, ~34 KB de design + runbooks).

Resumo dos pontos principais:

### 6.1 Schema multi-tenant

```
sites (id, slug, nome, ambiente, plano, status, bucket_name)
  ↓ FK
clientes_users (id, site_id, email, senha_hash, papel)
clientes_users_sessoes (id, user_id, token_hash, expira_em)
clientes_magic_links (id, user_id, token_hash, expira_em)
publishable_keys (key_id, site_id, valor, ambiente)
quotas (site_id, eventos_por_minuto, eventos_por_dia, retencao_dias)
consumo_diario (site_id, dia, eventos)
emissoes_jwt (site_id, publishable_id, jti, origin, ip)
```

### 6.2 Fluxo de provisionamento

**Self-service via landing** (default): `POST /cliente/auth/cadastro` → cria `sites` + `clientes_users(papel=admin)` + cookie de sessão. **Gap:** ainda não cria bucket Influx, org Grafana, datasource. Reconciliação manual via `scripts/provisionar_cliente.py`. Trigger automático na §10.

**Admin/CLI** (fallback): `python scripts/provisionar_cliente.py --slug X --nome "Y" --plano free` cria todos os artefatos (Postgres + Influx + Grafana org + datasource + dashboards templates).

### 6.3 Dashboard do cliente (Grafana via auth.proxy)

```
Browser → /cliente/metricas/...
  ↓ nginx auth_request /__cliente_auth_gate
  ↓ Flask /cliente/auth/gate (valida cookie cliente_session)
  ↓ 200 + header X-WEBAUTH-USER=<site_id>
  ↓ nginx propaga
  ↓ Grafana auth.proxy confia → cria/mapeia user
  ↓ datasource Influx filtra por bucket cliente_<slug>
```

**Hardening Viewer** (já aplicado): `GF_USERS_VIEWERS_CAN_EDIT=false`, `GF_EXPLORE_ENABLED=false`, `GF_SNAPSHOTS_EXTERNAL_ENABLED=false`.

### 6.4 Dashboards disponíveis

- **Camada 1** (out-of-the-box): Web Vitals, Engajamento, Funil, Event Explorer (4 templates em `ark/monitoring/dashboards/`).
- **Camada 2** (Event Explorer genérico): variáveis dinâmicas `$evento` + `$breakdown` populadas via Flux `schema.measurements()`.
- **Camada 3** (custom dashboards salvos pelo cliente): v2, fora do MVP.

### 6.5 Recovery procedures

Runbook completo em `ark/docs/dashboard-cliente.md` §22:
- A. VPS comprometida — restaurar backup completo dos 3 volumes.
- B. `grafana_data` perdido — re-provisionar tokens + datasources.
- C. `postgres_data` perdido — restore do `pg_dump` diário.
- D. `influxdb_data` perdido — catástrofe; restore do snapshot Influx + revogar tokens órfãos.
- E. Token de cliente comprometido — `tenant_admin.py rotate-token --site <slug>`.

---

## 7. Landing comercial e self-service signup

**Fonte canônica:** `ark/docs/dashboard-cliente.md` §23.

**Stack:** Astro 4 + Tailwind 3 + vitest + happy-dom em `landing/`. Build estático, servido por nginx:alpine no container `portifolio-landing` (loopback `127.0.0.1:3002`).

### 7.1 Páginas

- `/` — hero + features + 3 passos + CTA
- `/precos` — 3 planos (Free / Pro / Business)
- `/cliente/login` — form de login
- `/cliente/cadastro` — form de cadastro
- `/sitemap.xml`, `/robots.txt`, `/_health`

### 7.2 Eventos de dogfood (a landing usa o próprio SDK)

| Evento | Quando | Payload |
|---|---|---|
| `page_view` | Toda navegação | `{path, referrer}` |
| `cta_clicado` | Click em `[data-cta]` | `{cta, path}` |
| `cadastro_concluido` | 201 do `/cadastro` | `{site_id, plano}` |
| `login_concluido` | 200 do `/login` | `{site_id, papel}` |
| `formulario_erro` | 4xx/5xx | `{formulario, code, status}` |

Implementação: `landing/src/lib/tracking.ts` (testado, 9 testes happy-dom). Layout faz `attachCtaTracking(document, sdk.enviarEvento)` após init do SDK.

### 7.3 Brand voice (📐)

A landing usa linguagem **humana, sem jargão técnico**. Detalhes em memória `feedback_extreme_programming.md` + brand brief gerado em 2026-04-29 (substituições de jargão, voz/tom, audiência: dono de e-commerce / agência / marketing / freelancer dev).

---

## 8. Operação e deploy

### 8.1 Stack Docker (8 containers, 3 compose files)

| Container | Imagem | Porta loopback | Compose |
|---|---|---|---|
| `portifolio-frontend` | nginx:alpine + dist Vite | 3000 | `docker-compose.yml` |
| `portifolio-landing` | nginx:alpine + dist Astro | 3002 | `docker-compose.yml` |
| `portifolio-backend` | Flask + gunicorn(eventlet) | 5000 | `docker-compose.yml` |
| `portifolio-influxdb` | influxdb:2.7 | 8086 | `docker-compose.yml` |
| `portifolio-postgres` | postgres:16-alpine | só rede docker | `docker-compose.yml` |
| `portifolio-grafana` | grafana:11.2.0 | 3001 | `ark/monitoring/docker-compose.monitoring.yml` |
| `portifolio-prometheus` | prom/prometheus:v2.54.1 | 9090 (loopback) | `ark/monitoring/...` |
| `portifolio-node-exporter` | prom/node-exporter:v1.8.2 | 9100 (loopback) | `ark/monitoring/...` |
| `portifolio-crowdsec` | crowdsecurity/crowdsec:v1.6.3 | 6060, 8080 | `ark/crowdsec/docker-compose.crowdsec.yml` |

**Volumes persistentes:** `portifolio_influxdb_data`, `portifolio_postgres_data`, `portifolio_backend_keys` (chaves RSA do JWT), `monitoring_grafana-data`, `monitoring_prometheus-data`, `crowdsec_*`. **Nunca rodar `docker compose down -v`**.

### 8.2 Provisionamento via Ansible

```bash
make -f ark/Makefile ansible-check    # dry-run
make -f ark/Makefile ansible-apply    # aplicar
```

Roles em `ark/ansible/roles/`: `base`, `docker`, `analytics-stack`, `nginx`, `monitoring`, `crowdsec`.

**Vars críticas em `group_vars/all.yml`** (criptografado via ansible-vault, senha em `/opt/portifolio/.vault-password` mode 0600):

- `influxdb_token`, `influxdb_init_password`, `flask_secret_key`, `admin_api_token`, `postgres_password`
- `grafana_admin_password`
- `node_auth_token` — PAT GitHub com `read:packages` (build do landing + frontend)
- `landing_publishable_key` — dogfood (vazio = bucket default)
- `cors_origins` — lista de dominios permitidos (estática hoje, dinâmica no futuro — ver §10)

### 8.3 CI/CD

**3 workflows em `.github/workflows/`:**

| Workflow | Trigger | Responsabilidade |
|---|---|---|
| `ci.yml` | PR, push em `main` | Validate: docker-compose config, ansible syntax, frontend lint+test+build, backend lint+test |
| `prod-regression.yml` | push em paths sensíveis + cron diário 03:17 UTC | Smoke via curl: sem debugger Werkzeug, sem `/console`, sem rota sem prefix, bundle estático servido |
| `deploy.yml` | `workflow_run` CI OK em `main` | CD: runner self-hosted na VPS faz `git reset --hard origin/main` + `docker compose up -d --build --force-recreate --no-deps backend frontend landing` + health |

**Limites do CD automático:** apenas `backend`, `frontend`, `landing` rebuildam. Mudanças em InfluxDB, Postgres, roles Ansible, nginx do host, monitoring ou crowdsec exigem `ansible-apply` manual.

### 8.4 Observabilidade

- **Logs estruturados** no backend: `evento=<nome> chave=valor`. Eventos-chave: `conectado`, `recebido`, `validado`, `rejeitado`, `persistido_*`, `erro_persistencia`, `backpressure`, `acesso_bloqueado`, `[ADMIN-AUDIT]`, `auth_cliente_*`.
- **`backend/security.log`** rotaciona em 10 MB × 5 arquivos; CrowdSec lê.
- **Grafana**: `https://grafana.dsplayground.com.br` (admin direto, autenticação local).
- **Prometheus**: scrape do node-exporter ativo; **scrape do backend pendente** (item D.2 do plano-backend, hoje não há `/metrics`).
- **Health checks** dos containers via `docker inspect <name> --format '{{.State.Health.Status}}'`.

### 8.5 Backup InfluxDB

```bash
docker exec portifolio-influxdb influx backup /var/lib/influxdb2/backups
# pg_dump diário cron pra Postgres
```

**Free tier não tem backup** — quando dado expira em 7d, sumiu. Documentado explicitamente no signup. Migração pra S3 (Backblaze B2 / R2) quando volume passar de ~50 GB ou primeiro cliente pago entrar.

---

## 9. Capacidade e escalabilidade

**VPS atual:** 1 vCPU AMD EPYC, 1.7 GiB RAM, 50 GiB disco (HostGator Rocky 9.7).

**Modelo de volumetria por sessão ativa:**
- ~12 ticks de 5s em sessão de 1min = 12 emissões
- ~2 KB de payload por tick após normalização
- ~50 pontos InfluxDB por sessão (3 measurements × média de eventos)

**Teto prático seguro:** ~1.200 sessões concorrentes ativas antes de degradação de latência. Gargalo dominante é **CPU** (Flask + eventlet single-thread), não RAM.

**Roadmap de otimização (em ordem):**
1. Correções imediatas: orjson em vez de json (3-5x), evitar pickle em cache, lazy import de bibliotecas pesadas.
2. Trocar gunicorn(eventlet) → gunicorn(gevent) ou uvicorn workers — melhor concorrência IO.
3. Migrar pra FastAPI + asyncio (mais reescrita, ganho 5-10x em IO-bound).
4. Horizontal: nginx round-robin entre 2-3 VMs Flask + sticky session via `appId` hash.
5. Go/Rust **só se métricas justificarem** — não otimização especulativa.

**Topologia multi-VPS:** plano executivo de migração (monorepo + 1 VPS → multi-repo + LB + multi-API + VPS data + CDN) em **`ark/docs/migracao-multi-vps.md`**. 6 fases incrementais, ~12 semanas, custo alvo R$ 134-428/mês conforme provedor.

**Read-path do cliente:** Grafana embedded com auth.proxy é a escolha atual (até ~500 clientes). Em escala maior, considerar dashboard React custom + `auth.jwt` com claims customizados.

---

## 10. Pendências priorizadas

> Inventário operacional de contas/tokens/recovery em **`ark/docs/contas-e-acessos.md`**.
> Esta seção é só a fila acionável.

### 10.1 P0 fechados em 2026-04-30

- ✅ **Auth nos `/analytics/* REST**` (commit `d07c841`) — cookie obrigatório + bucket forçado por site_id; 9 testes em `test_analytics_auth.py`
- ✅ **Trigger automático de provisionamento pós-cadastro** (commit `e9beb96`) — thread daemon best-effort chama `scripts.provisionar_cliente`; 5 testes
- ✅ **Quota enforcement** — já estava implementado (sprint anterior); 6 testes verde validados em 2026-04-30
- ✅ **Hostname do dashboard cliente em `app.dsplayground.com.br`** (commits `abee7da`, `69e6fd6`, `7c980a0`, deploy 2026-04-30) — cookie `cliente_session` viaja entre apex/app/api via `COOKIE_DOMAIN=dsplayground.com.br`; vhost nginx `app.X` ativo; landing redireciona pós-cadastro pra `app.X/cliente/metricas`; Grafana `GF_ROOT_URL` migrado.
- ✅ **Apex em CF Pages** — landing comercial servida via Cloudflare Pages do repo `comercial`; nginx host removeu vhost apex (dead code). `PUBLIC_DASHBOARD_URL` configurado no painel CF Pages (2026-04-30).
- ✅ **Hardening de conta** — PAT amplo revogado, PAT enxuto criado (`read:packages`), 2FA habilitado em GitHub e CF.
- ✅ **Smoke test e2e** — `ark/scripts/smoke-test-arquitetura.sh` valida 20 pontos com clean-room (cria conta descartável + DELETE cascade no fim). 20/20 PASS validado em 2026-04-30. Bugs corrigidos via processo: PR #11 (`limiter.exempt(/gate)` — auth_request batia 429) + PR #12 (`proxy_pass` sem trailing `/` — Grafana sub_path causava loop 301).

### 10.2 Fila atual

| Prio | Item | Bloqueia | Onde | Estimativa |
|---|---|---|---|---|
| ✅ ~~**P2**~~ | ~~CrowdSec nginx-bouncer task ansible~~ — task atual em `ark/ansible/roles/crowdsec/tasks/main.yml` ja esta limpa (sem `ignore_errors`, sem nginx-bouncer); firewall-bouncer-nftables instalado pelo script oficial `install.crowdsec.net` | — | — | — |
| 🟢 **P3** | **Decidir destino do `landing/` no monorepo** — hoje é espelho da canônica em CF Pages (`comercial`). Manter como fallback até Phase 4 da migração ou remover já | `deploy.yml` rebuilda landing redundante | `landing/` + `docker-compose.yml` + `deploy.yml` | 1h se decidir remover |
| 🟡 **P1** | **Email transacional (Resend)** — sem isso magic-link em prod cai no stdout do container = "esqueci senha" totalmente quebrado | Recover password de cliente real | `group_vars/all.yml` + `email_sender.py` (já tem stub) | 0.5d |
| 🟡 **P1** | **Email do produto `contato@dsplayground.com.br`** — landing referencia (plano Business). Cloudflare Email Routing → forward Gmail (free) é o caminho mais rápido | UX de contato comercial | painel CF | 1-2h |
| ✅ ~~**P1**~~ | ~~**Dashboard de Settings do cliente**~~ — **feito 2026-05-02**, `comercial/src/pages/cliente/configuracoes.astro` com publishable_key + botão copiar, troca email/senha, plano + consumo | — | — | — |
| ✅ ~~**P1**~~ | ~~**Recover password UX**~~ — **feito 2026-05-02**, `comercial/src/pages/cliente/esqueci-senha.astro` live em CF Pages | — | — | — |
| 🟡 **P1** | **Conta empresa/CNPJ** (PJ MEI/ME/SLU + contador) | Emitir NF pro primeiro cliente pago | externo | varia |
| ✅ ~~**P1**~~ | ~~Cardinalidade enforcement runtime + alert em 80%/95%~~ — **feito 2026-05-02**, `backend/ingestao/cardinalidade.py` com alertas em 80% e 95% | — | — | — |
| ✅ ~~**P1**~~ | ~~Container `analytics-archiver`~~ — **feito 2026-05-01**, sidecar com APScheduler cron 03:00 UTC, exporta line protocol gzip pra Cloudflare R2 (`backend/archiver/`) | — | — | — |
| ✅ ~~**P1**~~ | ~~Endpoint `GET /cliente/exportar`~~ — **feito 2026-05-01**, listagem JSON + download via 302 signed URL R2 (TTL 5min), auth via cookie cliente_session, anti-IDOR via slug derivado do site_id | — | — | — |
| ✅ ~~**P1**~~ | ~~Email diário com counts agregados de rejeições~~ — **feito 2026-05-02**, `backend/scripts/email_diario.py` + container email-cron opt-in (PRs #57/#58); ativar requer `RESEND_API_KEY` no vault | — | — | — |
| 🟡 **P1** | Backup offline de credenciais (1Password ou age key + pen drive): vault Ansible, recovery codes, age key dos backups | Recovery em catástrofe | externo + processo | 1-2h |
| 🚧 **P2** | **Upgrade de plano** — `POST /billing/checkout` implementado (cria sessao Stripe Checkout via urllib, 7 testes); webhook + plano_service ja prontos. Falta: `STRIPE_API_KEY` + `STRIPE_PRICE_IDS` + `STRIPE_WEBHOOK_SECRET` no vault Ansible para ativar em prod | Cliente Pro/Business sem caminho de pagamento | `backend/billing/routes.py`, `backend/billing/stripe_webhook.py` | vault + deploy |
| ✅ ~~**P2**~~ | ~~Onda 1 do contrato SDK↔Backend: retry exponencial + dead-letter~~ — **feito 2026-05-06**, `sdk/src/filaAnalytics.ts` (`BACKOFF_RETRY_MS`, `proximaTentativaApos`, `incrementarTentativa`); `WebSocketService` acumula dead-letter via `getDeadLetter()`/`limparDeadLetter()`; 138/138 testes verdes | — | — | — |
| ✅ ~~**P2**~~ | ~~Onda 2: validação timestamp + skew correction + overflow priority~~ — **feito 2026-05-06**: backend `_validar_timestamps` + 4 testes novos; SDK `derivarPrioridade` refinado (mouse_move/hover→baixa, scroll/touch→normal, click/page_view/…→alta); `DeadLetterStore` localStorage TTL 24h max 100; 154/154 SDK + 450/450 backend verdes | — | — | — |
| ✅ ~~**P2**~~ | ~~Onda 3: backpressure dinâmico + schema version negotiation~~ — **feito 2026-05-06**: backend `handle_connect` valida `schema_version` do auth Socket.IO, emite `schema_error` + disconnect se incompatível, inclui `server_schema_version`/`min_client_schema` no `connection_response`; SDK envia `schema_version` no auth, lida com `schema_error` e `connection_response`, dispara `onSchemaIncompativel`; 4 testes novos (slow/stop/schema_error/connection_response); 158/158 SDK + 450/450 backend | — | — | — |
| ✅ ~~**P2**~~ | ~~CORS dinâmico via `sites.dominios_permitidos`~~ — **feito 2026-05-02**, `backend/ingestao/origins_dinamicos.py` consulta `site_dominios` em runtime | — | — | — |
| ✅ ~~**P2**~~ | ~~Tags derivadas server-side: `device_type`, `pais` (GeoIP), `referrer_dominio`~~ — **feito 2026-05-02**, `backend/ingestao/derivacoes.py` | — | — | — |
| ✅ ~~**P2**~~ | ~~Org-per-cliente fim-a-fim no Grafana: `/gate` força membership idempotente~~ — **implementado**, `backend/auth/grafana_sync.py` com `GrafanaSyncService` (TTL cache 1h, idempotente via add_org_user + set_user_current_org); ativado quando `GRAFANA_URL` + creds presentes | — | — | — |
| 🟢 **P3** | Backend `/metrics` Prometheus-client | Dashboards de operação | `backend/app.py` + scrape config | 1d |
| ✅ ~~**P3**~~ | ~~DNS Cloudflare: `portifolio.dsplayground.com.br`~~ — **ativo**, registro A proxiado confirmado no painel CF | — | — | — |
| 🟢 **P3** | Validação E2E nos 5 cenários de recovery em `ark/teste-ambiente-{a,b}` | SLO interno antes de virar chave comercial | `ark/teste-ambiente-*/` | 1-2d cada |
| 🟢 **P3** | 2FA TOTP no dashboard do cliente | v2 — não MVP | `sessao_service.py` + `clientes_users.totp_secret` | 3-5d |
| ✅ ~~**P3**~~ | ~~Migração backup → S3-compatible~~ — **feito 2026-05-01 direto**, R2 desde dia 1 (free tier 10 GB cobre ~55 clientes plano medio). Pulou fase intermediaria de backup local. | — | — | — |

---

## 11. Onde está cada coisa

### Código

| Componente | Caminho |
|---|---|
| SDK (legado, frontend) | `frontend/src/sdk/` |
| SDK (público, npm) | repo separado `dsplayground-analytics-sdk` |
| Backend ingestão | `backend/ingestao/` (servico_ingestao, validador, normalizador) |
| Backend auth | `backend/auth/` (cliente_routes, sessao_service, tenants_repo, clientes_users_repo, jwt_service, sites_cache, grafana_sync) |
| Backend persistência | `backend/influxdb_service.py` |
| Backend health/admin | `backend/app.py` (api_bp + endpoints LGPD) |
| Schemas SQL | `backend/auth/schema*.sql` (Postgres + SQLite) |
| Scripts admin | `backend/scripts/` (`provisionar_cliente.py`, `tenant_admin.py`, `dashboard_user_admin.py`, `configurar_retencao.py`) |
| Fixtures de teste | `backend/fixtures/analytics_payload_sintetico.json` |
| Testes backend (211) | `backend/test_*.py` |
| Frontend portfolio | `frontend/src/` (React 19 + Vite, classes Home/About/Projects) |
| Landing | `landing/src/` (Astro pages, components, lib/api.ts, lib/tracking.ts) |
| Testes landing (15) | `landing/src/lib/*.test.ts` |
| Templates Grafana | `ark/monitoring/dashboards/` |
| Provisionamento Grafana | `ark/monitoring/grafana/provisioning/` |
| Templates nginx | `ark/ansible/roles/nginx/templates/` (espelho `ark/nginx/`) |
| Templates Ansible | `ark/ansible/roles/*/templates/` |
| CrowdSec configs | `ark/crowdsec/` |

### Documentação

| Doc | Escopo |
|---|---|
| `CLAUDE.md` (raiz) | Comandos operacionais + regras pra agentes + estado da VPS |
| `AGENTS.md` (raiz) | Padrões de código + fluxo de PR |
| `README.md` (raiz) | Apresentação pública |
| `ark/docs/dashboard-cliente.md` | Design completo do produto multi-tenant + recovery runbook (sec 1-23) |
| `ark/docs/servidor-producao.md` | Arquitetura VPS, TLS, CrowdSec, hardening |
| `ark/docs/api-prefix-redundancia.md` | Histórico do refactor canonical (sem `/api/`) |
| `ark/docs/migracao-multi-vps.md` | Plano executivo de migração multi-repo + multi-VPS + CDN + LB |
| `ark/docs/contas-e-acessos.md` | Inventário de contas/tokens + recovery + checklist hardening |
| `ark/README.md`, `ark/nginx/README.md`, `ark/ansible/README.md`, `ark/crowdsec/README.md` | Operação por área |
| **`docs/PROJETO.md`** (este arquivo) | Estado canônico consolidado |

---

## 12. Apêndice — bug fixes históricos

Bugs já resolvidos, listados por completude. Comportamento atual está no código; só consultar aqui se for revisitar a decisão.

| Bug | Causa raiz | Solução |
|---|---|---|
| **Coleta temporal duplicada** (abr/2026) | `useHeatmap` hook + classes do `SlidesCarousel` instanciavam coleta em paralelo | Removido o hook das páginas; classes controlam coleta sozinhas; `window.__ACTIVE_PAGE_CONTROLLER__` garante 1 página ativa |
| **Duplicação por timing 5s/15s** | Coleta temporal (5s) + envio periódico legado (15s) eventualmente coincidiam | Removido o envio periódico; só coleta temporal envia |
| **Acúmulo infinito em `HeatmapRegistryGlobal`** | `addPaginaDados()` no array a cada `getDados()` (5s) | Novo método `setPaginaDados()` substitui em vez de acumular |
| **Migração InfluxDB 1.8 → 2.7** | Mudança de modelo de auth (org/bucket/token) | Atualizado `backend/config.py`, `.env.example`, queries Flux, health endpoint validado |

Tipo "deteção automática temporal/regular" no backend (em `README_TEMPORAL.md`) foi protótipo arquiteturalmente substituído pelo controle no SDK frontend.

---

## Manutenção

Ao alterar arquitetura, schema de dados, contrato de eventos, fluxo de deploy ou pendências:

1. Atualize o **código** primeiro.
2. Atualize **este doc** (`docs/PROJETO.md`).
3. Se o detalhe é profundo (recovery, design multi-tenant), atualize a fonte canônica em `ark/docs/` e mantenha o ponteiro daqui.
4. Atualize **`CLAUDE.md`** se afeta comandos operacionais.
5. Commit único com mudança de código + doc.
