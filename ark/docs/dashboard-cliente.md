# Dashboard do Cliente — Design Doc

> Status: **MVP implementado em `dev` (backend + nginx + grafana)** — validacao
> em teste-ambiente-a/b e frontend `/cliente/login` ainda pendentes.
> Autor: Daniel Santos + Claude (sessao 2026-04-24, impl 2026-04-25).
> Escopo: como expor metricas do SDK para clientes do `dsplayground` sem
> que eles precisem aprender Grafana, sem expor dados entre tenants, e
> sem reutilizar credencial publica como credencial de leitura.

## Estado de implementacao (2026-04-29)

**Implementado na branch `dev`:**

| Peca | Local | Status |
|------|-------|--------|
| Schema Postgres + SQLite | `backend/auth/schema_dashboard{_postgres,}.sql` | ✅ |
| Repo (CRUD + indexes) | `backend/auth/clientes_users_repo.py` | ✅ SQLite + Postgres |
| Service (sessao + magic-link + rate-limit) | `backend/auth/sessao_service.py` | ✅ |
| Email sender (stdout + Resend) | `backend/auth/email_sender.py` | ✅ |
| Flask blueprint `/cliente/auth` | `backend/auth/cliente_routes.py` | ✅ |
| Endpoint self-service `/cliente/auth/cadastro` | `backend/auth/cliente_routes.py` + `test_cliente_cadastro.py` | ✅ 2026-04-29 |
| Registro no app.py | `backend/app.py` | ✅ |
| Nginx vhost split (apex landing + portifolio.X) | `ark/ansible/roles/nginx/templates/portifolio.conf.j2` + espelho | ✅ 2026-04-29 |
| Grafana `auth.proxy` + subpath | `ark/monitoring/docker-compose.monitoring.yml` | ✅ |
| Frontend `/cliente/login` (mobile-first, hoje em portifolio.X) | `frontend/src/pages/ClienteLogin.jsx` + `ClienteMetricas.jsx` | ✅ |
| Landing comercial Astro+Tailwind no apex | `landing/` + `Dockerfile` + service no compose | ✅ 2026-04-29 |
| Cliente HTTP tipado (cadastro/login) | `landing/src/lib/api.ts` + `api.test.ts` | ✅ 2026-04-29 |
| Tracking de CTAs e eventos (cadastro/login/erro) | `landing/src/lib/tracking.ts` + `tracking.test.ts` | ✅ 2026-04-29 |
| Ansible: var `node_auth_token` + landing health + canonical `/health/app` | `ark/ansible/...` | ✅ 2026-04-29 |
| Auto-provisionamento pós-cadastro (bucket Influx + org/datasource Grafana + dashboards) | `backend/auth/cliente_routes.py` (`_provisionar_pos_cadastro`) | ✅ 2026-05-05 |
| CLI admin de users | `backend/scripts/dashboard_user_admin.py` | ✅ |
| Dashboard analytics-overview corrigido (4 paineis) | `ark/monitoring/grafana/dashboards/analytics-overview.json` | ✅ |
| Anti-abuse com TTL + skip de IPs privados | `backend/app.py` | ✅ |
| Reaper de sessoes Socket.IO zombies | `backend/app.py` | ✅ |
| Schema `sites.bucket_name` + migracao idempotente | `backend/auth/schema*.sql` + `tenants_repo.py` | ✅ sprint 1 |
| CLI `provisionar_cliente.py` (Postgres + Influx + Grafana) | `backend/scripts/provisionar_cliente.py` | ✅ sprint 1 |
| `SitesCache` (TTL 5min) + roteamento de ingest por bucket | `backend/auth/sites_cache.py` + `ingestao/servico_ingestao.py` | ✅ sprint 1 |
| Validador exige `app_id` e `ambiente` no envelope | `backend/ingestao/validador.py` | ✅ sprint 1 |
| `ip_address` e `metric_id` viraram fields (anti-cardinalidade) | `backend/influxdb_service.py` | ✅ sprint 1 |
| Testes backend (211 verde) + landing (15 verde) | `backend/test_*.py` + `landing/src/lib/*.test.ts` | ✅ 2026-04-29 |

**Hardening Grafana Viewer (sprint 1 extra, 2026-04-27):** `GF_USERS_VIEWERS_CAN_EDIT=false`, `GF_EXPLORE_ENABLED=false`, `GF_SNAPSHOTS_EXTERNAL_ENABLED=false` em `ark/monitoring/docker-compose.monitoring.yml`. Validado: `curl -H 'X-WEBAUTH-USER:<id>' /api/dashboards/home` retorna `canEdit:false canSave:false canAdmin:false`.

**Proposto — sprint 2:**

- **Quota enforcement**: backend rejeita evento com `analytics_error code=QUOTA_EXCEDIDA` quando `consumo_diario.eventos > quotas.eventos_por_dia`. Hoje so incrementa, nao rejeita.
- **Cardinalidade enforcement**: contador `(bucket, tag) -> set(values)` em memoria + Postgres; rejeita ponto + log `[SECURITY] cardinalidade_excedida` quando passa do limite do plano.
- Email diario com counts agregados de rejeicoes (1x/dia, nao 1x/evento).
- Email alert pro cliente em 80% e 95% da cardinalidade do plano.
- Tags derivadas server-side: `device_type` (do User-Agent), `pais` (GeoIP do IP), `referrer_dominio` (do header Referer).
- **Org-per-cliente fim-a-fim no Grafana**: o `provisionar_cliente.py` ja cria a org, mas usuarios do `auth.proxy` continuam caindo na "Main Org". Falta logica no `/gate` (ou script de membership) que adiciona o user a org certa idempotente via Grafana API.
- 4 dashboards out-of-the-box provisionados na org do cliente: Web Vitals, Engajamento, Funil, Event Explorer.
- Container `analytics-archiver`: cron diario que exporta `[now-retencao-1d, now-retencao]` em line protocol comprimido pra `/var/backups/analytics/<slug>/YYYY-MM-DD.lp.gz`.
- Endpoint `GET /cliente/exportar?inicio=...&fim=...` com signed URL (nginx X-Accel-Redirect).
- Validacao end-to-end em `ark/teste-ambiente-a` (Docker) e `teste-ambiente-b` (Vagrant).

**Pendente — proximas sprints (v2/v3):**

- 2FA TOTP, white-label CSS, integracoes server-to-server REST.
- `RESEND_API_KEY` em prod via Ansible Vault (dev cai pro stdout sender).
- Migracao de backup local para S3 (Backblaze/Wasabi/R2) quando volume passar de ~50 GB ou primeiro cliente pago entrar.
- Custom dashboards salvos pelo cliente (camada 3 da §2).
- Em escala >500 clientes, migrar `auth.proxy` -> `auth.jwt` com claims customizados.

**Nota de schema:** `REFERENCES clientes(id)` no desenho inicial virou `REFERENCES sites(id)` na implementacao (alinhado com a tabela multi-tenant existente, `sites`, que ja e o conceito de "cliente"). Campo em `clientes_users` e `site_id`.

---

## 1. Problema

O SDK ja coleta eventos arbitrarios por cliente em InfluxDB (medidas
padrao — Web Vitals, page view, scroll, hover, exposicao, toque,
clique, mouse move, page exit — alem de `evento_custom` livre). Falta
**entregar essas metricas pro proprio cliente** com:

- UX limpa (referencia: New Relic — telas pre-prontas por intencao).
- Isolamento entre tenants (cliente A nao ve dado de cliente B).
- Suporte a **eventos arbitrarios** (cliente pode definir qualquer
  `evento` via SDK — nao da pra ter so N dashboards fixos).
- Sem reutilizar token do SDK (publico, embedded em browser) como
  credencial de leitura.

## 2. Arquitetura — 2 camadas

### Camada 1 — Dashboards prontos (out-of-the-box)

Para o que **todo cliente** gera, JSON versionado em
`ark/monitoring/dashboards/`:

- **Web Vitals** — LCP, FID, CLS, INP por pagina e dispositivo.
- **Page Views & Sessoes** — volume, paginas mais vistas, retencao.
- **Engajamento** — clique, scroll, hover, exposicao.
- **Saidas** — page exit, tempo de sessao, bounce.

Hand-tuned, polidos. `cliente_id` injetado via header de auth (ver §3).

### Camada 2 — Event Explorer (1 dashboard generico)

Um dashboard com variaveis dinamicas:

- `$evento` — populado via Flux `schema.measurements()` (ou tag
  values), filtrado por `cliente_id`.
- `$breakdown` — lista as tags do evento selecionado.

Cliente escolhe `evento=botao_clicado` + `breakdown=pagina` e ve
timeseries + top values + amostras recentes — **sem mexer em Flux**.
Equivalente ao "Data Explorer" do New Relic.

### Camada 3 — Custom dashboards (v2)

Cliente salva combinacoes uteis do Explorer como dashboard proprio.
Fora do MVP.

## 3. Auth — Por que NAO usar o token SDK

**Falha critica:** o token do SDK e publico. Esta no JS bundle do
site do cliente. Qualquer end-user inspeciona e pega. Se ele
desbloqueasse leitura de dashboards, o end-user da loja-do-cliente
veria as metricas da loja-do-cliente.

Padrao da industria (NR, Datadog, Segment): **separar credenciais**.

| Credencial         | Onde vive            | Permissao             |
|--------------------|----------------------|-----------------------|
| Ingest token (SDK) | JS do site do cliente | `scope: ["ingest"]`  |
| Dashboard session  | Cookie HttpOnly       | `scope: ["dashboard"]`|

## 4. Fluxo de trafego

```
Cliente → Cloudflare → Nginx host → /cliente/metricas/*
                            ↓
              Flask /cliente/auth/gate
              (valida cookie de sessao → Postgres)
                            ↓ (200 + X-WEBAUTH-USER: <cliente_id>)
              proxy_pass → Grafana (127.0.0.1:3001)
                            ↓
              Grafana auth.proxy confia no header
                            ↓
              InfluxDB datasource filtra por v.cliente_id
                            ↓
              Dashboard renderizado
```

Guard rails:

- Grafana segue bindando em `127.0.0.1:3001`. Sem ingress externo.
- `firewalld` bloqueia 3001 mesmo se loopback exposto por engano.
- Audit do Flask em `security.log` (CrowdSec ja le).

## 5. Schema Postgres

```sql
-- usuarios humanos do cliente que acessam dashboard
CREATE TABLE clientes_users (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  cliente_id   UUID NOT NULL REFERENCES clientes(id) ON DELETE CASCADE,
  email        CITEXT UNIQUE NOT NULL,
  senha_hash   TEXT,                                  -- null se magic-link only
  papel        TEXT NOT NULL DEFAULT 'viewer',        -- admin | viewer
  ativo        BOOLEAN NOT NULL DEFAULT true,
  ultimo_login TIMESTAMPTZ,
  criado_em    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_clientes_users_cliente ON clientes_users(cliente_id);

-- sessoes ativas (cookie sha256-hash)
CREATE TABLE clientes_users_sessoes (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     UUID NOT NULL REFERENCES clientes_users(id) ON DELETE CASCADE,
  token_hash  TEXT UNIQUE NOT NULL,                   -- sha256 do cookie, nunca plaintext
  ip          INET,
  user_agent  TEXT,
  expira_em   TIMESTAMPTZ NOT NULL,
  revogada_em TIMESTAMPTZ,
  criada_em   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_sessoes_token ON clientes_users_sessoes(token_hash)
  WHERE revogada_em IS NULL;
CREATE INDEX idx_sessoes_user  ON clientes_users_sessoes(user_id);

-- magic links (login passwordless)
CREATE TABLE clientes_magic_links (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id         UUID NOT NULL REFERENCES clientes_users(id) ON DELETE CASCADE,
  token_hash      TEXT UNIQUE NOT NULL,               -- sha256 do token enviado por email
  expira_em       TIMESTAMPTZ NOT NULL,               -- 15 min
  consumido_em    TIMESTAMPTZ,
  ip_solicitacao  INET,
  criada_em       TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

## 6. Endpoints (Flask blueprint `/cliente/auth`)

| Metodo | Rota                          | Payload                                  | Resposta                                            |
|--------|-------------------------------|------------------------------------------|-----------------------------------------------------|
| POST   | `/cadastro`                   | `{email,senha,nome_site,slug}`           | 201 + cookie OR 400/409                             |
| POST   | `/magic-link/solicitar`       | `{email}`                                | sempre `200 {ok:true}` (nao vaza emails existentes) |
| GET    | `/magic-link/verificar?t=...` | —                                        | 302 → `/cliente/metricas` + Set-Cookie              |
| POST   | `/login`                      | `{email,senha}`                          | 200 + cookie OR 401                                 |
| POST   | `/logout`                     | —                                        | revoga sessao, limpa cookie                         |
| GET    | `/me`                         | —                                        | `{user_id, cliente_id, papel}` ou 401               |
| GET    | `/gate`                       | —                                        | 200 + `X-WEBAUTH-USER: <cliente_id>` ou 401         |

`/gate` e o endpoint do `auth_request` do nginx.

## 7. Cookie de sessao

- Nome: `cliente_session`
- Valor: `base64url(random_bytes(32))` (256-bit, gerado com
  `secrets.token_urlsafe`).
- Server guarda apenas `sha256(token)` na tabela `sessoes`.
- Flags: `HttpOnly; Secure; SameSite=Strict; Path=/`.
- `Max-Age`: 7 dias rolando (renovado a cada `/gate` ok).
- `Domain`: `dsplayground.com.br`.

## 8. Fluxo magic-link

1. Cliente abre `/cliente/login`, digita email, submete.
2. POST `/magic-link/solicitar` → rate-limit (3/email/15min,
   10/IP/15min) → gera token 32B → salva
   `sha256(token) + expira_em (now+15min)` → envia email com link
   `https://dsplayground.com.br/cliente/auth/verificar?t=<token>`.
3. Cliente clica → GET `/verificar?t=...` → valida (existe, nao
   expirou, nao foi consumido) → marca `consumido_em = now()` →
   cria sessao → Set-Cookie → 302 → `/cliente/metricas`.
4. Cada request a `/cliente/metricas/*` passa por
   `auth_request /cliente/auth/gate` → valida cookie → injeta
   header `X-WEBAUTH-USER: <cliente_id>`.

## 9. Rate-limit & lockout

- 5 logins falhos por (email + IP) em 15min → 30min lockout.
- 3 magic-links solicitados por email em 15min.
- 10 magic-links solicitados por IP em 15min.
- Tudo logado em `security.log` → CrowdSec parseia → bane IP abusivo.

## 10. Audit events (`security.log`)

Formato `evento=<x> cliente_id=<id> user_id=<id> ip=<ip> ua=<ua>`:

- `auth_login_ok` / `auth_login_fail`
- `auth_magic_solicitado` / `auth_magic_consumido` / `auth_magic_expirado`
- `auth_session_criada` / `auth_session_revogada` / `auth_session_expirada`
- `auth_gate_ok` / `auth_gate_negado`

## 11. Provisionamento de novo cliente

Dois caminhos coexistem (ambos suportados):

**Self-service (recomendado, default em prod desde 2026-04-29)** — cliente cadastra-se pela landing comercial em `dsplayground.com.br/cliente/cadastro`. Endpoint `POST /cliente/auth/cadastro` cria `sites` + `clientes_users` (admin) e devolve cookie de sessao no mesmo response. Fluxo detalhado em §23.

**Admin/CLI (fallback, onboarding manual)**:
1. Cliente SDK e criado (fluxo existente — Postgres `clientes`).
2. Trigger cria 1 `clientes_users` com `papel='admin'` e email do
   contato.
3. Backend dispara magic-link "bem-vindo, clique pra acessar seu
   dashboard". Sem fricção de senha inicial.
4. Admin pode adicionar mais users via `/cliente/users`
   (futuro v2).

## 12. E-mail — lacuna do stack

Stack atual nao tem SMTP/MTA. Opcoes:

| Provider  | Free tier        | Notas                        |
|-----------|------------------|------------------------------|
| Resend    | 100/dia, 3k/mes  | API moderna, recomendado MVP |
| SES       | $0.10/1k         | Mais barato em escala        |
| Postmark  | 100/mes          | Entregabilidade premium      |

Adicionar `RESEND_API_KEY` em `backend/.env` via Ansible Vault.

## 13. Multi-tenant data scoping no Grafana

### Grafana side

- `grafana.ini`:
  ```
  [auth.proxy]
  enabled         = true
  header_name     = X-WEBAUTH-USER
  header_property = username
  auto_sign_up    = true
  sync_ttl        = 60
  ```
- Cada `cliente_id` vira user Grafana com role `Viewer`.

### Datasource InfluxDB

- Header `X-Cliente-ID` propagado para o datasource (Grafana suporta
  via "Custom HTTP Headers" no datasource).
- Variavel Grafana `cliente_id` do tipo `Constant`, populada por
  `${__user.login}`.

### Flux nas queries

Toda query comeca com:

```flux
from(bucket: "metricas")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r.cliente_id == "${cliente_id}")
```

Para reforcar (caso usuario duplique dashboard e remova o filter):
**datasource secundario com query header forwarding** que injeta o
filtro server-side antes de bater no Influx.

## 14. Risco residual

- Senha de dashboard reusada e vazada → atacante entra. Mitigacao:
  2FA TOTP no v2 + alerta de novo IP/UA via CrowdSec.
- Magic-link interceptado em e-mail comprometido → atacante entra.
  Mitigacao: link expira 15min + 1 uso unico + audit alerta.
- `cliente_id` 1:1 com user Grafana **explode em escala alta**
  (>500 clientes). Trocar para `auth.jwt` com claims customizados —
  mais complexo, vale so pra esse volume.
- Cardinalidade alta em InfluxDB se cliente colocar `user_id` como
  tag → cluster derrete. **Documentar no SDK**: tags = categorias
  finitas, fields = valores. Quota de series unicas por cliente em
  Postgres + reject no ingest.

## 15. Roadmap

- **MVP (~3-4 dias):** schema + endpoints `/login`, `/logout`,
  `/me`, `/gate` + magic-link + Resend + nginx `auth_request` +
  `auth.proxy` no Grafana + 1 dashboard provisionado (Web Vitals)
  como prova de conceito.
- **v1 (~1-2 sprints):** 4 dashboards out-of-the-box + Event
  Explorer + onboarding magic-link automatico no provisionamento.
- **v2:** 2FA TOTP, custom dashboards salvos pelo cliente, papel
  admin gerenciando users, dashboards programaticos via API.
- **v3 (se >500 clientes):** migrar pra `auth.jwt`, considerar UI
  React custom no portfolio para 2-3 telas mais usadas (resto
  continua Grafana embedded).

## 16. Decisoes em aberto

- Comecar pela **tabela + `/me` + `/gate`** (testavel com cookie
  manual em Postman, ~1 dia) ou **fluxo completo magic-link**
  (~3-4 dias)?
- Resend ou SES?
- Embedar Grafana via iframe em `/cliente/metricas` ou redirecionar
  pro subdominio `grafana.dsplayground.com.br` autenticado?

## 17. Referencias

- Padrao "ingest key vs read key": New Relic, Datadog, Segment.
- Grafana auth.proxy:
  https://grafana.com/docs/grafana/latest/setup-grafana/configure-security/configure-authentication/auth-proxy/
- nginx `auth_request`:
  http://nginx.org/en/docs/http/ngx_http_auth_request_module.html
- OWASP session management cheat sheet (cookie flags, lifetime).

---

## 18. Planos e tiers (PostHog-style)

Decidido em 2026-04-26 apos benchmark com PostHog, Mixpanel, Amplitude, Plausible, Datadog RUM. Escolha: cobranca por **eventos/mes** + **retencao** + **cardinalidade**, com free generoso em volume mas curto em retencao. Coluna "backup" descrita em sec. 21.

| Plano | Eventos/mes | Retencao | Sessoes/dia | Cardinalidade max | Sites por user | Backup |
|---|---|---|---|---|---|---|
| **free** | 10k | 7 dias | 50 | 1k tag values | 1 | ❌ trial puro |
| **pequeno** | 100k | 30 dias | 500 | 5k tag values | 3 | semanal, retencao 1m |
| **medio** | 1M | 90 dias | 5k | 50k tag values | 10 | diario, retencao 6m |
| **grande** | 10M | 365 dias | ilimitado | 500k tag values | ilimitado | diario + arquivo 12m |

**Enforce server-side**: backend valida cada evento contra a quota do plano (`sites.plano` -> `quotas.eventos_por_dia`). Se passou: `analytics_error code=QUOTA_EXCEDIDA` + email diario com counts agregados de rejeicoes (1x/dia, nao 1x/evento).

**Trial**: `free` cobre exatamente o ciclo "instalei o SDK -> deixo rodar 1 dia -> analiso o dashboard". Apos os 7d, dado some — ate o cliente fazer upgrade.

**Upgrade**: Usuario cria `clientes_users` no plano free, dados ficam ligados ao mesmo `site_id`. Quando faz upgrade, o `sites.plano` muda; bucket existente ganha nova retencao (Influx aceita `update bucket --retention=...` em runtime, mas dados ja-expirados nao voltam).

**Cardinalidade alta = morte do InfluxDB OSS**: cliente que mete `user_id` como tag detona o bucket. Por isso a sec. 19 define whitelist + rejeicao server-side.

## 19. Bucket-per-cliente

Decisao: 1 bucket InfluxDB por `site_id`, nome `cliente_<slug>`. Trade-offs documentados:

| Opcao | Pro | Contra |
|---|---|---|
| **Bucket-per-cliente (escolhido)** | Hard isolation, easy revoke (drop bucket), retention per plan | Overhead operacional cresce linear, tokens proliferam |
| Single bucket + tag site_id | Operacao simples | Filtro depende de disciplina, vaza com bug |
| Bucket-per-plano + tag | Hibrido | Mistura free + pago no mesmo bucket complica |

**Esquema do bucket:**

| Measurement | Fields | Tags whitelist | Tags proibidas |
|---|---|---|---|
| `page_analytics` | cliques, hovers, mouse_moves, toques, scrolls, exposicoes, custom_events, permanencia_segundos, visualizacoes, user_agent | `app_id`, `ambiente`, `page_type`, `device_type`, `pais`, `referrer_dominio` | `user_id`, `session_id`*, `email`, `request_id`, `url_completa` |
| `web_vitals` | valor (numerico), user_agent | `app_id`, `ambiente`, `page_type`, `nome` (LCP/CLS/INP), `rating`, `device_type` | mesmas |
| `custom_events` | ocorrencias (count), <props_primitivas como fields> | `app_id`, `ambiente`, `page_type`, `nome` (do evento) | mesmas |

\* `session_id` e tag em `page_analytics` hoje porque a query de "sessoes ativas" precisa dele. Em produto comercial, considerar mover pra field — sessoes geram cardinalidade ilimitada.

**Routing do ingest (implementado em sprint 1):**

```python
# backend/auth/sites_cache.py + backend/ingestao/servico_ingestao.py
bucket = sites_cache.obter_bucket(site_id)  # TTL 5min, cache-aside Postgres
if bucket is None:
    # site sem bucket cadastrado -> log evento=site_sem_bucket + cai no bucket default
    pass
influxdb_service.write_temporal_metrics_async(metric, bucket=bucket)
```

O `SitesCache` recebe o `TenantsRepo` e expoe `obter_bucket(site_id)` + `invalidar(site_id)`. Apos provisionar um cliente novo, chamar `invalidar` libera a entrada antes do TTL expirar (relevante para hot-deploys).

## 20. Tag enforcement

Backend rejeita pontos no momento do ingest (NAO no momento da query — query lenta vs ingest rapido). Regras:

**Tags obrigatorias** (rejeita ponto se faltar):
- `app_id` (vem do payload, ja validado contra `sites.app_id`)
- `ambiente` (vem do payload)
- `page_type` (vem do payload — eventos sem pagina sao invalidos por design)

**Tags whitelist** (so essas sao aceitas como tag; resto vira field):
- `device_type` (derivado do `user_agent` server-side)
- `pais` (derivado do IP via GeoIP, opcional — ainda sem implementacao)
- `referrer_dominio` (derivado do `Referer` header — so o dominio, nao path)
- `nome` (so em `custom_events` e `web_vitals`)
- `rating` (so em `web_vitals`: good/needs-improvement/poor)

**Cardinalidade limit por bucket** (configuravel por plano):
- Backend mantem contador `(bucket, tag) -> set(values)` em memoria + Postgres
- Se `len(set) > limite_plano`: rejeita evento + log `[SECURITY] cardinalidade_excedida bucket=X tag=Y`
- Email alert pro cliente em 80% e 95% da cardinalidade

**Eventos rejeitados** continuam contabilizados pra quota (se nao, abriria buraco — atacante manda 1B eventos invalidos sem custo).

## 21. Backup pre-wipe

InfluxDB OSS nao exporta automaticamente dados que vao expirar. Sidecar dedicado.

**Container `analytics-archiver`** (em `backend/archiver/`, compose service `archiver`):

```yaml
archiver:
  build:
    context: ./backend
    dockerfile: archiver/Dockerfile
  env_file: ./backend/.env  # reusa INFLUXDB_*, R2_*, TENANTS_DATABASE_URL
  depends_on: [influxdb, postgres]
```

Codigo: `backend/archiver/`
- `service.py` — `ArchiverService.export_window(slug, start, end)` retorna gzip de line protocol.
- `r2_client.py` — `R2Client.upload(slug, dia, body)` + `signed_url_para_download(key, ttl)`.
- `scheduler.py` — `executar_rodada_diaria(sites, archiver, r2, agora_utc)` itera e arquiva.
- `sites_source.py` — combina `TenantsRepo.listar_sites` + `obter_quota` em `SiteArquivavel`.
- `routes.py` — blueprint `/cliente/exportar` (listar + download via 302 signed URL).
- `main.py` — entrypoint APScheduler com cron diario.

**Algoritmo (implementado em `scheduler.py`):**

```
para cada site com status='ativo' e plano != 'free':
  retencao = quotas.retencao_dias  (default 30)
  dia_a_exportar = now_utc.date() - retencao
  start = midnight(dia_a_exportar) UTC
  end   = start + 1 dia
  payload = ArchiverService.export_window(slug, start, end)
  if payload nao-vazio:
    R2Client.upload(slug, dia_a_exportar, payload)
    -> r2://dsplayground-analytics-archive/<slug>/YYYY/MM/DD.lp.gz
```

Falhas em um site nao param os outros (try/except + contador `ResumoRodada.falhas`).
Payload vazio (bucket sem dados na janela) pula upload pra nao poluir R2.

**Storage R2 (Cloudflare):**
- Bucket unico `dsplayground-analytics-archive` (jurisdiction EU, free tier 10 GB).
- Key prefix por slug: `<slug>/<YYYY>/<MM>/<DD>.lp.gz` — list anti-IDOR via `Prefix=<slug>/`.
- Free tier cobre ~55 clientes plano medio (180 MB/cliente steady-state) ou 3 plano grande.
- Acima: $0.015/GB/mes — 100 GB = $1.35/mes.

**Endpoint pro cliente baixar (`backend/archiver/routes.py`):**

```
GET /cliente/exportar           — JSON com lista de dias arquivados do slug do user
GET /cliente/exportar/<YYYY-MM-DD> — 302 + signed URL R2 (TTL 5min)
```

Auth via cookie `cliente_session` (mesmo do `/cliente/auth/me`). Anti-IDOR: key R2
sempre derivada do `user.site_id -> tenants_repo.obter_site(...).slug`, nunca do path.

**Free tier nao tem backup** — quando dado expira em 7d, sumiu mesmo. Documentar **explicitamente** no signup.

## 22. Recovery procedure (runbook)

**Cenarios e procedimentos:**

### A. VPS comprometida — restaurar do backup completo

```bash
# Pre-requisitos: backup atualizado dos 3 volumes Docker (postgres_data,
# influxdb_data, grafana_data) + clone fresco do repo na nova VPS.

# 1. Restaurar volumes (projeto compose usa prefixo dsplay_)
docker volume create dsplay_postgres_data
docker run --rm -v dsplay_postgres_data:/dst -v /backup:/src alpine \
  sh -c 'cd /dst && tar xzf /src/postgres_data.tar.gz'
# repetir para influxdb_data, grafana_data

# 2. Subir stack
cd /opt/dsplay && docker compose up -d
make -f ark/Makefile monitoring-up

# 3. Validar: cada bucket Influx tem dados, Grafana tem datasources
# com tokens validos, sites tem bucket_name preenchido em Postgres.
```

### B. `grafana_data` perdido isoladamente

Cenario onde so o volume do Grafana corrompeu. Tokens InfluxDB que estavam la **nao estao em mais nenhum lugar** (decisao da sec. 14: nao persistir em Postgres por simplicidade).

```bash
# 1. Pra cada site provisionado, revogar tokens antigos do Influx:
#    (lista todos os tokens com "InfluxDB" no description e revoga)
docker exec dsplay-influxdb influx auth list \
  --json | jq -r '.[] | select(.description | contains("cliente_")) | .id' \
  | xargs -I{} docker exec dsplay-influxdb influx auth delete --id {}

# 2. Re-provisionar tudo (script idempotente):
backend/scripts/provisionar_cliente.py --recovery --all
# pra cada site:
#   - cria novo read-token escopado ao bucket existente
#   - recria org no Grafana
#   - recria datasource com novo token
#   - importa dashboards templates
```

### C. `postgres_data` perdido

Os tokens do Grafana continuam validos (datasources tem token plaintext em secureJsonData encriptado). Mas perdeu `clientes_users`, `sites`, etc.

```bash
# 1. Restaurar do pg_dump diario (ver setup de backup do Postgres)
# 2. Conferir consistencia: cada bucket no Influx deve ter site
#    correspondente em Postgres com bucket_name == nome do bucket.
# 3. Magic-links pendentes podem ter sido perdidos — clientes precisam
#    solicitar novos via /cliente/login.
```

### D. `influxdb_data` perdido

**Catastrofe maxima**: dados de todos os clientes vao embora.

```bash
# 1. Restaurar do snapshot mais recente (estrategia depende do setup
#    de backup do Influx — pg_dump-style: influx backup ... ).
# 2. Tokens vinculados a buckets que sumiram precisam ser revogados.
#    Recomendacao: revogar todos e recriar via provisionar_cliente.py.
# 3. Notificar clientes do gap de dados (timestamps faltantes).
```

### E. Token de cliente comprometido (ex: vazamento)

```bash
# 1. Revogar token no Influx
docker exec dsplay-influxdb influx auth delete --id <token_id>
# 2. Gerar novo + atualizar datasource Grafana via API
backend/scripts/provisionar_cliente.py --rotate-token --site <slug>
# 3. Auditoria: pesquisar `evento=` em security.log buscando uso suspeito.
```

**Importante**: testar os 5 cenarios em ambiente B (Vagrant) antes de virar a chave comercial. Documentar tempos medios em SLO interno.

---

## 23. Landing comercial + self-service signup (2026-04-29)

Decisao tomada em 2026-04-29: separar **portfolio pessoal** do **produto comercial** em hostnames distintos, e abrir self-service signup via landing.

### 23.1 Split de dominios

| Hostname | Conteudo | Container | Porta loopback |
|---|---|---|---|
| `dsplayground.com.br` (apex) | Landing comercial (Astro estatico) — produto, preços, cadastro, login | `dsplay-landing` (nginx:alpine + dist/) | 3002 |
| `portifolio.dsplayground.com.br` | Portfolio pessoal do Daniel (React 3D — Home/Projects/About) | `dsplay-frontend` (nginx:alpine + Vite bundle) | 3000 |
| `api.dsplayground.com.br` | Backend Flask + Socket.IO (paths canonicos sem `/api/`) | `dsplay-backend` | 5000 |

Apex tambem rota `/cliente/metricas/*` (auth_request -> Grafana via X-WEBAUTH-USER) e `/api/*` (rewrite strippa o prefix antes do proxy_pass pro backend). Vhosts em `ark/ansible/roles/nginx/templates/portifolio.conf.j2` com espelho em `ark/nginx/portifolio.conf`.

### 23.2 Stack do landing

- **Astro 4 + Tailwind 3** em `landing/`. Build estatico — todo o SEO (meta tags, OG, Twitter card, JSON-LD `SoftwareApplication`, `sitemap.xml`, `robots.txt`) vai pro HTML; nada e SPA-rendered.
- **vitest + happy-dom** pra unit tests do cliente HTTP (`lib/api.ts`) e do tracking de CTAs (`lib/tracking.ts`).
- Dockerfile espelha o do frontend: stage de build (node:22) + stage de runtime (nginx:alpine servindo `dist/`).
- Build args: `PUBLIC_SITE_URL`, `PUBLIC_API_URL`, `PUBLIC_PUBLISHABLE_KEY`, `PUBLIC_DEBUG`.

### 23.3 Endpoint de cadastro

`POST /cliente/auth/cadastro` (em `backend/auth/cliente_routes.py:cadastro()`):

**Payload**: `{email, senha, nome_site, slug}`. Validacoes:
- `email` regex `^[^@\s]+@[^@\s]+\.[^@\s]+$`
- `senha` >= 8 chars
- `slug` regex `^[a-z0-9](?:[a-z0-9\-]{1,30}[a-z0-9])$` (3-32, comeca/termina alfanumerico)
- `nome_site` qualquer texto nao-vazio

**Acoes**:
1. Checa duplicatas (email em `clientes_users`, slug em `sites`) → 409 com `code` tipado.
2. `tenants_repo.criar_site(slug=..., nome_site, ambiente, dominios=[], plano='free', bucket_name='cliente_<slug>')`.
3. `sessao_service.criar_user(site.id, email, papel='admin', senha=...)` (gera senha_hash via werkzeug).
4. `sessao_service.criar_sessao(user.id)` — cookie HttpOnly+Secure+SameSite=Strict.
5. Retorna 201 com `{status, user, site}` e Set-Cookie.

**Codes de erro**: `PAYLOAD_INCOMPLETO`, `EMAIL_INVALIDO`, `SENHA_CURTA`, `SLUG_INVALIDO`, `EMAIL_JA_CADASTRADO`, `SLUG_JA_CADASTRADO`, `CADASTRO_NAO_CONFIGURADO` (503 — repos nao injetados no boot).

**Auditoria**: log `evento=auth_cliente_cadastro_ok site_id=... slug=... user_id=... ip=...` em `security.log` (CrowdSec parseia).

**Testes**: `backend/test_cliente_cadastro.py` cobre happy path, bucket `cliente_<slug>`, papel admin, dup email/slug, validacao de payload completa (8 testes).

### 23.4 Provisionamento pos-cadastro (implementado em 2026-05-05)

O handler de `/cadastro` chama `_provisionar_pos_cadastro()` ao final, que spawna uma
`threading.Thread(daemon=True)` com `_executar_provisionamento()`. Esta funcao constroi
um `argparse.Namespace` artificial e chama `provisionar()` de `scripts/provisionar_cliente.py`,
criando em sequencia:

1. Bucket InfluxDB `cliente_<slug>` com retencao do plano.
2. Token InfluxDB escopado ao bucket (read-only para Grafana).
3. Org Grafana `cliente_<slug>`.
4. Datasource Influx na org com o token gerado.
5. Dashboards out-of-the-box (templates de `ark/monitoring/dashboards/`).
6. Publishable key default no Postgres.

**Estrategia best-effort**: cadastro retorna 201 mesmo se provisionamento falhar.
Falhas sao logadas em `security.log` com `evento=provisionamento_falhou` (CrowdSec parseia).
Admin reconcilia com:
```bash
docker compose exec backend python scripts/provisionar_cliente.py \
    --slug <slug> --nome "<Nome>" --plano free
```

**Testes**: `CadastroTriggerProvisionamentoTests` em `test_cliente_cadastro.py` cobre:
- Dispatch correto de kwargs (slug, nome, plano, ambiente, site_id).
- Cadastro retorna 201 mesmo com provisionamento lancando excecao.
- Payload invalido NAO dispara provisionamento.

### 23.5 Eventos do landing (dogfood)

A propria landing usa o SDK pra medir conversao. Eventos emitidos:

| Evento | Quando | Payload |
|---|---|---|
| `page_view` | Toda navegacao (auto, no Layout) | `{path, referrer}` |
| `cta_clicado` | Click em qualquer `[data-cta]` | `{cta, path}` |
| `cadastro_concluido` | 201 do `/cadastro` | `{site_id, plano}` |
| `login_concluido` | 200 do `/login` | `{site_id, papel}` |
| `formulario_erro` | 4xx/5xx de cadastro ou login | `{formulario, code, status}` |

Implementacao em `landing/src/lib/tracking.ts` (testado em `tracking.test.ts`, 9 testes happy-dom). O Layout wireia `attachCtaTracking(document, sdk.enviarEvento)` apos init do SDK.

**Dogfood publishable key**: emite-se uma key dedicada pra `dsplayground-landing` via `tenant_admin.py create-key` e cola-se em `landing_publishable_key` no Vault. Eventos da landing entao caem num bucket separado (`cliente_dsplayground-landing`), permitindo medir conversao sem misturar com clientes reais. Ver `landing/.env.example`.

### 23.6 Operacao via Ansible

Variaveis novas em `group_vars/all.yml` (espelhadas em `all.example.yml`):

- `node_auth_token` — PAT GitHub com `read:packages`. Obrigatorio (assertado em `playbook.yml` pre_tasks). Usado como BuildKit secret pelos Dockerfiles do `frontend` e `landing` para baixar `@danpqdan/dsplayground-analytics-sdk` do GitHub Packages registry privado. Persistido em `${repo_dir}/.env` (mode 0640, dono `deploy:analytics`) e propagado pelo compose via `secrets.NODE_AUTH_TOKEN.environment`.
- `landing_site_url`, `landing_api_url`, `landing_debug` — build args do Astro.
- `landing_publishable_key` — opcional, vazio por default (eventos caem no bucket default em dev).

Health checks adicionados:
- `analytics-stack` role: `uri: http://127.0.0.1:3002/_health` apos `docker compose up`.
- `playbook.yml` post_tasks: backend agora bate em `/health/app` (canonico) ao inves do antigo `/api/health/app`, e valida o landing em `/_health`.

### 23.7 Pendencias

- Migrar `app_id` do payload pra ser derivado de `site.id` server-side (hoje cliente envia, mas pode mentir — backend ja valida contra `sites.id`, mas remover do payload elimina o passo).
- E-mail de boas-vindas pos-cadastro (estrutura ja existe via Resend em §12 — falta template e trigger).
- Dogfood: gerar a publishable key da landing apos primeiro deploy completo.
- DNS Cloudflare: criar registro `portifolio.dsplayground.com.br` apontando pro mesmo IP da apex (proxiado, laranja). Hoje so a apex resolve.
