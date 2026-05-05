# DSPlay Analytics — Backend

![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-3.1-000000?logo=flask&logoColor=white)
![License](https://img.shields.io/badge/license-MIT-6B7280)
![Tests](https://img.shields.io/badge/tests-441%20passing-22C55E)

API central da plataforma DSPlay Analytics. Recebe eventos de browsers via WebSocket (Socket.IO), persiste em InfluxDB por bucket-per-tenant e expõe APIs de consulta, autenticação de clientes, billing e exportação de dados.

---

## Índice

- [Arquitetura](#arquitetura)
- [Stack](#stack)
- [Estrutura de módulos](#estrutura-de-módulos)
- [Autenticação e segurança](#autenticação-e-segurança)
- [API Reference](#api-reference)
- [Modelos de dados](#modelos-de-dados)
- [Configuração](#configuração)
- [Desenvolvimento local](#desenvolvimento-local)
- [Scripts administrativos](#scripts-administrativos)
- [Observabilidade](#observabilidade)
- [Repositórios relacionados](#repositórios-relacionados)

---

## Arquitetura

```
┌─────────────────────────────────────────────────────────────────┐
│  Browser (SDK)                                                  │
│  publishable_key ──► POST /auth/sdk-token                       │
│                           │                                     │
│                      JWT RS256 (TTL 300s)                       │
│                           │                                     │
│  Bearer JWT ──────► WebSocket /socket.io                        │
│                           │                                     │
│                      analytics_data (HeatmapDados)              │
│                           │                                     │
│              ┌────────────▼────────────┐                        │
│              │  validação → derivações │                        │
│              │  cardinalidade check    │                        │
│              └────────────┬────────────┘                        │
│                           │                                     │
│                    InfluxDB (bucket-per-tenant)                  │
│                           │                                     │
│  Dashboard ──► GET /analytics/metricas                          │
│  (cookie)      GET /analytics/web-vitals                        │
│                GET /analytics/custom-events                     │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  Cliente (browser)                                              │
│  POST /cliente/auth/login ──► cookie cliente_session            │
│                                      │                          │
│  nginx auth_request ──► GET /cliente/auth/gate                  │
│       (200 + X-WEBAUTH-USER) ──► Grafana auth.proxy             │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  Archiver (APScheduler)                                         │
│  janelas expiradas ──► gzip ──► Cloudflare R2                   │
│  GET /cliente/exportar/<dia> ──► redirect signed URL (5min)     │
└─────────────────────────────────────────────────────────────────┘
```

---

## Stack

| Tecnologia | Versão | Função |
|---|---|---|
| Flask | 3.1 | Framework web, blueprints, roteamento |
| Flask-SocketIO + Eventlet | 5.6 | WebSocket assíncrono (worker único) |
| Gunicorn + Eventlet | — | Servidor de produção |
| InfluxDB 2.7 | influxdb-client 1.50 | Série temporal de eventos (bucket-per-tenant) |
| PostgreSQL 16 | psycopg 3.3 | Auth multi-tenant em produção |
| SQLite | nativo | Auth multi-tenant em desenvolvimento |
| PyJWT + cryptography | 2.12 / 46 | SDK JWT (RS256) e embed JWT (HS256) |
| Flask-Limiter | 4.1 | Rate limiting por IP e por chave |
| Prometheus Client | 0.25 | Métricas de eventos, WebSocket e HTTP |
| APScheduler | 3.11 | Jobs periódicos do archiver |
| Boto3 | 1.43 | Cloudflare R2 (S3-compatible) |
| Stripe | — | Checkout e webhook de billing |
| Resend | — | E-mail transacional (magic-link, relatório diário) |

---

## Estrutura de módulos

```
backend/
├── app.py                   # Bootstrap Flask: blueprints, Socket.IO, health, middleware
├── config.py                # Configuração por ambiente via .env
├── influxdb_service.py      # Queries Flux, escrita de métricas, validação anti-injeção
├── embed_routes.py          # Blueprint /embed: tokens e dados para iframes
├── metrics.py               # Contadores e histogramas Prometheus
│
├── auth/                    # Autenticação e multi-tenancy
│   ├── jwt_service.py       # Emissão/verificação SDK JWT (RS256, RSA 2048)
│   ├── embed_jwt_service.py # JWT embed para iframes (HS256)
│   ├── tenants_repo.py      # CRUD de sites, publishable keys, quotas (SQLite/Postgres)
│   ├── clientes_users_repo.py # Usuários do dashboard (SQLite/Postgres)
│   ├── sessao_service.py    # Sessões e magic-link (hash SHA256, rate-limit)
│   ├── cliente_routes.py    # Blueprint /cliente/auth
│   ├── middleware.py        # Validação token Socket.IO, normalização de Origin
│   ├── origins_dinamicos.py # CORS dinâmico por site_dominios com TTL em cache
│   ├── grafana_sync.py      # Sincronização de usuários com Grafana
│   ├── email_sender.py      # Envio de magic-link e recuperação de senha
│   ├── sites_cache.py       # Cache em memória de objetos Site
│   ├── schema.sql           # Schema SQLite (dev)
│   └── schema_postgres.sql  # Schema PostgreSQL (prod)
│
├── ingestao/                # Pipeline de processamento de eventos
│   ├── servico_ingestao.py  # Orquestração: validação → derivações → persistência
│   ├── validador.py         # Schema JSON (id_registro, paginas, eventos)
│   ├── derivacoes.py        # Tags server-side: device_type, país, referrer
│   ├── cardinalidade.py     # Tracker de high-cardinality, alertas e limites por plano
│   ├── idempotencia.py      # Deduplição por id_registro
│   └── logs.py              # Logs estruturados da ingestão
│
├── archiver/                # Exportação de dados para Cloudflare R2
│   ├── service.py           # Orquestração: gzip → R2 → cleanup
│   ├── r2_client.py         # Cliente R2 (boto3), geração de signed URLs
│   ├── scheduler.py         # APScheduler: jobs periódicos de exportação
│   ├── routes.py            # Blueprint /cliente/exportar
│   └── main.py              # Entrypoint para container separado
│
├── billing/                 # Faturamento
│   ├── plano_service.py     # Definição dos planos (PLANO_DEFAULTS: free/pro)
│   ├── routes.py            # GET /billing/planos, POST /billing/checkout
│   └── stripe_webhook.py    # Webhook Stripe (payment_intent, subscription)
│
├── integrations/
│   └── grafana_client.py    # Provisioning de datasources, orgs e dashboards no Grafana
│
├── dto/
│   └── Dados.py             # HeatmapDados, PaginaDados, EventoNormalizado
│
└── scripts/                 # CLIs administrativos (ver seção Scripts)
```

---

## Autenticação e segurança

### SDK JWT (RS256)

O SDK do browser troca uma `publishable_key` por um JWT assinado com RSA 2048:

```
POST /auth/sdk-token
  body: { publishable_key, origin, analytics_session_id }
  → valida: site ativo, origin permitido, rate limit de emissão, quota diária
  → retorna: JWT RS256 (audience=JWT_AUDIENCE, TTL=SDK_TOKEN_TTL_SECONDS)
```

O JWT é usado no handshake WebSocket via `Authorization: Bearer <token>`. As chaves RSA ficam em `JWT_KEYS_DIR` (volume persistente em produção).

### Sessão de dashboard (cookie)

Clientes humanos autenticam com email+senha ou magic-link:

```
POST /cliente/auth/login
  → cria Sessao com token_hash SHA256 + fingerprint (IP, User-Agent, Accept-Language)
  → seta cookie cliente_session (HttpOnly, Secure, SameSite=Strict, Domain=COOKIE_DOMAIN)
  → TTL: 1 hora, revogação explícita via /logout
```

### nginx auth_request gate

O nginx do servidor de produção delega autenticação do dashboard ao backend:

```
GET /cliente/auth/gate
  → valida cookie cliente_session
  → 200 + header X-WEBAUTH-USER=<site_id> → Grafana auth.proxy mapeia o usuário
  → 401 → nginx redireciona para /cliente/login
```

### Rate limiting e anti-abuse

- **Flask-Limiter**: limites por endpoint (ex: `/auth/sdk-token` 5/min, `/health` 60/min)
- **Anti-abuse custom**: bloqueia IPs com `ANTIABUSE_REQS_PER_MIN` requisições suspeitas por `ANTIABUSE_BAN_TTL_SECONDS` segundos; eventos registrados em `security.log`
- **Cardinalidade**: eventos com tags de alta cardinalidade são rejeitados quando o tenant atinge o limite do plano (free: 1K tags, pro: 500K)

### CORS

- **Estático**: lista de origens permitidas via `CORS_ORIGINS` (subdomínios da plataforma)
- **Dinâmico**: origens adicionais por tenant via tabela `site_dominios`, com cache TTL configurável por `CORS_DINAMICO_TTL_SEGUNDOS`

---

## API Reference

### Health

| Método | Path | Auth | Descrição |
|---|---|---|---|
| GET | `/health/app` | — | Status da aplicação Flask |
| GET | `/health/socketio` | — | Status do Socket.IO |
| GET | `/health/influxdb` | — | Conectividade com InfluxDB |

### Analytics

| Método | Path | Auth | Descrição |
|---|---|---|---|
| GET | `/analytics/metricas` | Cookie | Métricas agregadas por página |
| GET | `/analytics/web-vitals` | Cookie | CLS, LCP, FID por página |
| GET | `/analytics/custom-events` | Cookie | Eventos customizados do tenant |
| GET | `/analytics/stats/temporal` | Cookie | Estatísticas temporais em tempo real |
| GET | `/analytics/security/status` | Cookie | Status de segurança da conta |

### Autenticação SDK

| Método | Path | Auth | Descrição |
|---|---|---|---|
| POST | `/auth/sdk-token` | — | Emite JWT RS256 para o SDK |

### Autenticação de clientes

| Método | Path | Auth | Descrição |
|---|---|---|---|
| POST | `/cliente/auth/cadastro` | — | Registra novo cliente (email, senha, nome_site, slug) |
| POST | `/cliente/auth/login` | — | Login com email + senha |
| POST | `/cliente/auth/logout` | Cookie | Revoga sessão ativa |
| GET | `/cliente/auth/me` | Cookie | Dados do usuário autenticado |
| GET | `/cliente/auth/gate` | Cookie | Validação para nginx auth_request |
| POST | `/cliente/auth/magic-link/solicitar` | — | Envia magic-link por e-mail |
| GET | `/cliente/auth/magic-link/verificar` | Query `?t=` | Consome magic-link e cria sessão |
| POST | `/cliente/auth/recuperar-senha/solicitar` | — | Envia link de recuperação de senha |
| POST | `/cliente/auth/recuperar-senha/confirmar` | — | Consome token e troca senha |
| GET | `/cliente/auth/configuracoes` | Cookie | User + site + publishable keys + quota + consumo |
| PATCH | `/cliente/auth/senha` | Cookie | Troca senha do usuário logado |
| PATCH | `/cliente/auth/email` | Cookie | Troca e-mail do usuário logado |
| GET | `/cliente/auth/configuracoes/publishable-keys` | Cookie | Lista publishable keys ativas |

### Embed

| Método | Path | Auth | Descrição |
|---|---|---|---|
| POST | `/embed/token` | Cookie | Gera JWT HS256 para iframe embed |
| GET | `/embed/dados/<site_id>/<grafico_id>` | Bearer JWT | Retorna dados do gráfico para iframe |

### Billing

| Método | Path | Auth | Descrição |
|---|---|---|---|
| GET | `/billing/planos` | — | Lista planos disponíveis com quotas |
| POST | `/billing/checkout` | Cookie | Cria sessão Stripe Checkout |

### Exportação

| Método | Path | Auth | Descrição |
|---|---|---|---|
| GET | `/cliente/exportar` | Cookie | Lista dias com dados arquivados |
| GET | `/cliente/exportar/<YYYY-MM-DD>` | Cookie | Redirect para signed URL R2 (TTL 5min) |

### Admin

| Método | Path | Auth | Descrição |
|---|---|---|---|
| POST | `/admin/embed/revogar` | Token admin | Revoga JWT embed por JTI |
| POST | `/admin/embed/housekeeping` | Token admin | Purga JWTs revogados com mais de 48h |
| GET | `/admin/analytics/sessao/<id>` | Token admin | Consulta sessão de analytics |
| DELETE | `/admin/analytics/sessao/<id>` | Token admin | Remove sessão de analytics |

### Socket.IO

| Evento | Direção | Descrição |
|---|---|---|
| `connect` | cliente → servidor | Handshake com `Authorization: Bearer <jwt>` |
| `analytics_data` | cliente → servidor | Envia `HeatmapDados`; retorna `ResumoIngestao` (ack) |
| `disconnect` | servidor | Cleanup da sessão WebSocket |

---

## Modelos de dados

### Tenants

```python
Site(id, slug, nome, ambiente, plano, status, bucket_name)
PublishableKey(key_id, site_id, valor, nome, revogada)
Quota(
    site_id,
    eventos_por_minuto,
    eventos_por_dia,
    emissoes_jwt_por_minuto,
    retencao_dias
)
```

### Usuários do dashboard

```python
ClienteUser(id, site_id, email, senha_hash, papel, ativo, ultimo_login)
Sessao(id, user_id, token_hash, ip, user_agent, expira_em, revogada_em)
MagicLink(id, user_id, token_hash, expira_em, consumido_em, ip_solicitacao, tipo)
```

### Ingestão

```python
HeatmapDados(
    id_registro: str,           # UUID v4 — chave de idempotência
    timestamp_inicial: int,     # ms epoch
    timestamp_final: int,
    paginas: Dict[str, List[PaginaDados]]
)

PaginaDados(
    eventos: List[EventoNormalizado],
    visualizacoes: int,
    segundos: int,
    timestamp_inicial: int,
    timestamp_final: int
)

EventoNormalizado(tipo: str, timestamp: int, dados: Dict[str, Any])
```

### Schemas SQL

Tabelas em `auth/schema.sql` (SQLite) e `auth/schema_postgres.sql` (PostgreSQL):

| Tabela | Descrição |
|---|---|
| `sites` | Tenants da plataforma |
| `site_dominios` | Origens permitidas por tenant (CORS dinâmico) |
| `publishable_keys` | Chaves públicas do SDK por site |
| `quotas` | Limites de eventos e emissões JWT por site |
| `emissoes_jwt` | Auditoria de emissões de SDK token |
| `consumo_diario` | Total de eventos recebidos por site por dia |
| `clientes_users` | Usuários humanos do dashboard |
| `sessoes` | Sessões ativas dos usuários |
| `magic_links` | Tokens de login e recuperação de senha |
| `embed_jwt_revogados` | JTIs de embed revogados |
| `stripe_eventos_processados` | Idempotência de webhooks Stripe |

---

## Configuração

Copie `.env.example` para `.env` e ajuste os valores:

### Aplicação

| Variável | Descrição | Default |
|---|---|---|
| `SECRET_KEY` | Chave de assinatura Flask (obrigatória) | — |
| `FLASK_ENV` | Ambiente (`development` / `production`) | `development` |
| `HOST` | Endereço de bind | `127.0.0.1` |
| `PORT` | Porta | `5000` |

### Banco de dados

| Variável | Descrição | Default |
|---|---|---|
| `TENANTS_DATABASE_URL` | URL do banco de tenants (`postgresql://` ou `sqlite:///`) | `sqlite:///data/tenants.db` |
| `DATABASE_URL` | URL do banco de usuários (mesmo formato) | `sqlite:///data/dashboard.db` |

### JWT e autenticação

| Variável | Descrição | Default |
|---|---|---|
| `JWT_AUDIENCE` | Audience dos SDK JWTs | `api.dsplayground.local` |
| `JWT_KEYS_DIR` | Diretório das chaves RSA | `backend/data/keys` |
| `SDK_AUTH_REQUIRED` | Exige JWT em todo connect WebSocket | `false` |
| `SDK_TOKEN_TTL_SECONDS` | TTL do SDK JWT em segundos | `300` |
| `COOKIE_DOMAIN` | Domain do cookie de sessão | vazio (host-only) |
| `COOKIE_SECURE` | Cookie Secure flag | `true` |

### InfluxDB

| Variável | Descrição | Default |
|---|---|---|
| `INFLUXDB_ENABLED` | Habilita persistência | `false` |
| `INFLUXDB_URL` | Endpoint InfluxDB | `http://localhost:8086` |
| `INFLUXDB_TOKEN` | Token de autenticação | — |
| `INFLUXDB_ORG` | Organização | `zen` |
| `INFLUXDB_BUCKET` | Bucket padrão | `portifolio_dev` |

### CORS

| Variável | Descrição | Default |
|---|---|---|
| `CORS_ORIGINS` | Lista separada por vírgula de origens permitidas | — |
| `CORS_DINAMICO_TTL_SEGUNDOS` | TTL do cache de origens dinâmicas | `60` |

### Billing (Stripe)

| Variável | Descrição | Default |
|---|---|---|
| `STRIPE_API_KEY` | Chave secreta da API Stripe | — |
| `STRIPE_PRICE_IDS` | JSON mapeando plano → price_id Stripe | `{}` |
| `STRIPE_WEBHOOK_SECRET` | Secret de verificação do webhook | — |
| `BILLING_SUCCESS_URL` | URL de retorno após checkout bem-sucedido | — |
| `BILLING_CANCEL_URL` | URL de retorno após cancelamento | — |

### E-mail (Resend)

| Variável | Descrição | Default |
|---|---|---|
| `RESEND_API_KEY` | Chave da API Resend | — |
| `EMAIL_FROM` | Endereço de envio | `no-reply@dsplayground.com.br` |

### Cloudflare R2 (Archiver)

| Variável | Descrição | Default |
|---|---|---|
| `R2_ACCOUNT_ID` | ID da conta Cloudflare | — |
| `R2_ACCESS_KEY_ID` | Access key do token R2 | — |
| `R2_SECRET_ACCESS_KEY` | Secret key do token R2 | — |
| `R2_BUCKET` | Nome do bucket | `dsplayground-analytics-archive` |

### Anti-abuse

| Variável | Descrição | Default |
|---|---|---|
| `ANTIABUSE_REQS_PER_MIN` | Requisições suspeitas por minuto antes do ban | `600` |
| `ANTIABUSE_BAN_TTL_SECONDS` | Duração do ban em segundos | `300` |

---

## Desenvolvimento local

### Pré-requisitos

- Python 3.12+
- InfluxDB 2.7 (opcional — desabilite com `INFLUXDB_ENABLED=false`)
- PostgreSQL 16 (opcional — SQLite é o default em dev)

### Instalação

```bash
cd backend
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# Ajuste SECRET_KEY e as variáveis necessárias
```

### Executar

```bash
python app.py
# ou com Gunicorn (equivalente ao container de prod):
gunicorn --worker-class eventlet -w 1 -b 127.0.0.1:5000 app:app
```

### Testes

```bash
SECRET_KEY=test pytest
```

Para rodar apenas um módulo:

```bash
SECRET_KEY=test pytest test_auth.py -v
```

A suíte não requer InfluxDB nem Postgres — usa mocks e SQLite em memória.

---

## Scripts administrativos

Todos os scripts ficam em `scripts/` e são executados dentro do container ou com o ambiente virtual ativo.

| Script | Uso |
|---|---|
| `tenant_admin.py` | CRUD de sites, publishable keys e quotas |
| `provisionar_cliente.py` | Cria bucket InfluxDB, org Grafana, datasources e dashboards para um novo tenant |
| `dashboard_user_admin.py` | Gestão de usuários do dashboard (criar, listar, redefinir senha) |
| `email_diario.py` | Gera e envia relatório diário de quota por e-mail |
| `email_cron_main.py` | Entrypoint do container `email-cron` (opt-in via compose) |
| `redo_dashboards.py` | Regenera todos os dashboards Grafana a partir dos templates |
| `configurar_retencao.py` | Define política de retenção InfluxDB por bucket |
| `enviar_analytics_sintetico.py` | Injeta dados sintéticos para testes de carga e desenvolvimento |
| `validar_fixture.py` | Valida arquivos de fixture contra o schema de ingestão |

Exemplo de uso:

```bash
# Criar publishable key para um tenant
docker compose exec backend python scripts/tenant_admin.py create-key \
    --slug meu-site \
    --nome "Meu Site — Produção" \
    --ambiente production
```

---

## Observabilidade

### Métricas Prometheus

Expostas em `/metrics` (porta 5000):

| Métrica | Tipo | Labels | Descrição |
|---|---|---|---|
| `portifolio_eventos_recebidos_total` | Counter | `tipo` | Eventos persistidos com sucesso |
| `portifolio_eventos_rejeitados_total` | Counter | `code` | Rejeições por código de erro |
| `portifolio_websocket_conexoes_ativas` | Gauge | — | Conexões WebSocket ativas |
| `portifolio_request_duration_seconds` | Histogram | `path`, `method` | Latência HTTP por endpoint |

Códigos de rejeição (`code`): `SCHEMA_INVALIDO`, `CARDINALIDADE_EXCEDIDA`, `QUOTA_EXCEDIDA`, `IDEMPOTENCIA`, `AUTH_FALHOU`.

### Logs estruturados

Todos os logs seguem o padrão `evento=<nome> chave=valor`:

| Evento | Descrição |
|---|---|
| `conectado` | Novo cliente WebSocket autenticado |
| `recebido` | Payload analytics_data recebido |
| `validado` | Payload aprovado na validação de schema |
| `rejeitado` | Payload rejeitado (inclui `motivo=`) |
| `persistido_influx` | Escrita no InfluxDB concluída |
| `erro_persistencia` | Falha na escrita (inclui `erro=`) |
| `backpressure` | Sinal de backpressure emitido ao SDK |
| `acesso_bloqueado` | Requisição bloqueada pelo anti-abuse |
| `[ADMIN-AUDIT]` | Ações administrativas (revogar, housekeeping) |

O arquivo `security.log` rotaciona em 10 MB × 5 arquivos e é lido pelo CrowdSec para detecção de ataques.

---

## Repositórios relacionados

| Repositório | Descrição |
|---|---|
| [DSPlayAnalytics/SDK](https://github.com/DSPlayAnalytics/SDK) | SDK de analytics para browsers — cliente WebSocket + telemetria |
| [DSPlayAnalytics/landing](https://github.com/DSPlayAnalytics/landing) | Landing e área do cliente — Astro 6 + Tailwind 4 |

---

## Licença

MIT © [DSPlay Analytics](https://dsplayground.com.br)
