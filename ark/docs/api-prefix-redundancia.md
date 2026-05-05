# API prefix redundante + bug latente do SDK

> Status: **executado** — SDK v0.3.0 (Socket.IO sem `/api/`) + remocao de
> `url_prefix` dos blueprints + nginx strippa `/api/` no apex. Em prod desde
> 2026-04-30. Doc preservada como historico arquitetural.
> Identificado em 2026-04-29 durante revisao de exemplo do SDK.

## Resumo do problema

Hoje o backend Flask responde por **dois caminhos equivalentes**, ambos com path `/api/...`:

```
api.dsplayground.com.br/api/auth/sdk-token       (subdomain  + path /api)
dsplayground.com.br/api/auth/sdk-token           (apex       + path /api)
```

O `api.` do subdominio + `/api/` do path **dizem a mesma coisa duas vezes**. Pior: o exemplo de uso do SDK no README esta documentando uma chamada que **nao funciona em producao**.

## Bug latente do SDK

`websocketUrl: 'https://api.dsplayground.com.br'` no exemplo do README do `@danpqdan/dsplayground-analytics-sdk@0.2.0`. Combinado com:

```ts
// SDK src/authClient.ts:69
const url = `${this.config.backendBaseUrl.replace(/\/$/, '')}/auth/sdk-token`;
```

a chamada vira `https://api.dsplayground.com.br/auth/sdk-token`. Mas o backend em prod registra (em `backend/app.py:331`):

```python
app.register_blueprint(auth_bp, url_prefix=('/api/auth' if env == 'production' else '/auth'))
```

Em prod o endpoint real e `/api/auth/sdk-token`. **404 em prod**, funciona em dev (sem prefix).

Mesmo problema no Socket.IO:

```ts
// SDK src/WebSocketService.tsx:208
path: '/api/socket.io/'
```

Aqui o SDK explicitamente coloca `/api/`. Combinado com `api.X` o caminho fica redundante. Funciona, mas e visualmente confuso.

## Configuracao atual (referencia)

**nginx `portifolio.conf`** ([ver](../nginx/portifolio.conf)):
- vhost `api.dsplayground.com.br`: `location / { proxy_pass http://portifolio_backend; }` — preserva path
- vhost `dsplayground.com.br`: `location /api/cliente/auth/ { proxy_pass http://portifolio_backend; }` — preserva path

**backend `app.py`**:
- `auth_bp`: `url_prefix='/api/auth'` em prod, `/auth` em dev
- `cliente_auth_bp`: `url_prefix='/api/cliente/auth'` (constante na blueprint)
- `socketio_config['path'] = '/api/socket.io'` em todos os ambientes

**SDK `authClient.ts` / `WebSocketService.tsx`**:
- `auth/sdk-token` (sem `/api/`)
- Socket.IO path `/api/socket.io/` (com `/api/`) — inconsistente

## 3 opcoes de fix

### A) Backend canonico sem `/api/`, nginx do apex strippa o prefixo

Backend escuta caminhos limpos. nginx faz traducao por vhost.

| Camada | Mudanca |
|---|---|
| `backend/app.py` | `auth_bp` registrado com `url_prefix='/auth'` em **todos** ambientes. `cliente_auth_bp` muda blueprint definition para `url_prefix='/cliente/auth'`. `socketio_config['path'] = '/socket.io'`. |
| `ark/nginx/portifolio.conf` (apex) | `location /api/ { rewrite ^/api/(.*)$ /$1 break; proxy_pass http://portifolio_backend; proxy_http_version 1.1; ... }` |
| SDK `WebSocketService.tsx:208` | `/api/socket.io/` -> `/socket.io/`. Bump v0.3.0. |
| Portfolio | bump dep para `^0.3.0`. |
| Backend tests | scan de `/api/` hardcoded em `test_*.py` e ajustar. |

**Pro**: URL canonica limpa, SDK consistente, novos clientes vanilla nao tropecam no `/api/api/`.
**Contra**: cirurgia em 5 lugares (backend + 2 vhosts + SDK + portfolio + tests).

### B) Drop do subdominio `api.dsplayground.com.br`

Manter so o apex `dsplayground.com.br/api/...`. DNS do `api.` faz 301 redirect.

| Camada | Mudanca |
|---|---|
| Cloudflare DNS | record `api.X` 301 -> `dsplayground.com.br/api/...` |
| `ark/nginx/portifolio.conf` | remove vhost `api.dsplayground.com.br` (server_name compartilhado precisa separar) |
| SDK README | exemplo passa a usar `https://dsplayground.com.br` em vez de `https://api.X` |

**Pro**: cirurgia menor, sem mudanca de codigo.
**Contra**: redirect adiciona um hop em cada Socket.IO connect (latencia inicial). Perde subdominio dedicado — alguns clientes preferem `api.X` por isolamento de cookies de auth do dashboard humano.

### C) Backend sem prefix em prod, nginx do apex adiciona o prefixo

Inverso da A: backend sempre limpo, nginx apex injeta `/api/`.

| Camada | Mudanca |
|---|---|
| `backend/app.py` | mesmo de A: blueprints sem `/api/`. |
| `ark/nginx/portifolio.conf` (apex) | `location /api/auth/ { proxy_pass http://portifolio_backend/auth/; }` (slash final no proxy_pass strippa). Repetir para `/api/cliente/auth/`, `/api/socket.io/`, etc. — explicito por endpoint. |
| SDK | sem mudanca (mantem `/api/socket.io/`). |

**Pro**: SDK e clientes nao precisam mudar.
**Contra**: cada novo endpoint requer config no nginx. Locations multiplos vs 1 catch-all do A.

## Recomendacao

**Opcao A.** Backend canonico limpo + nginx faz a traducao no apex. Resolve a redundancia visual, fecha o bug latente do SDK (`/auth/sdk-token` passa a funcionar nos 2 dominios), deixa o SDK mais consistente (Socket.IO path em `/socket.io/` casa com REST).

Trade-off aceitavel: mexe no SDK (bump v0.3.0) e portfolio (bump dep). Como ambos estao sob nosso controle, e cirurgia auditavel.

## Plano de execucao (Opcao A)

Ordem importa por causa do contrato SDK<->backend:

1. **Branch** `feature/api-prefix-canonico` em ambos repos.
2. **Backend** (`portifolio`):
   - `app.py:331`: `url_prefix='/auth'` constante
   - `auth/cliente_routes.py`: blueprint `url_prefix='/cliente/auth'` (perde o `/api/`)
   - `app.py:125`: `socketio_config['path'] = '/socket.io'`
   - Tests `test_*.py` e `test_dashboard_auth.py`: scan `/api/` em URLs e atualizar
3. **Nginx** (`ark/nginx/portifolio.conf`):
   - apex: novo `location /api/ { rewrite ^/api/(.*)$ /$1 break; proxy_pass http://portifolio_backend; ... }` antes dos locations especificos atuais
   - `__cliente_auth_gate`: `proxy_pass http://portifolio_backend/cliente/auth/gate;`
   - api.X vhost: nada muda (proxy_pass direto continua valido)
4. **Validacao backend**:
   - `ark/teste-ambiente-a` agora em Rocky 9 — rodar playbook
   - Local: `docker compose up -d --build backend` + curl `/auth/sdk-token` e `/api/auth/sdk-token`
5. **SDK** (`dsplayground-analytics-sdk`):
   - `WebSocketService.tsx:208`: `/api/socket.io/` -> `/socket.io/`
   - Bump `package.json` 0.2.0 -> 0.3.0
   - CHANGELOG: BREAKING CHANGE — backend deve ter feature/api-prefix-canonico mergeado
   - Tag `v0.3.0`, push, workflow publica
6. **Portfolio** (`portifolio`):
   - `frontend/package.json`: dep `^0.2.0` -> `^0.3.0`
   - Validar build local + Docker
7. **Merge ordem**:
   - `feature/api-prefix-canonico` no portifolio (com nginx + backend) -> dev
   - SDK v0.3.0 ja publicado
   - portfolio bumpa dep e merge dev -> main
   - CD automatic deploya backend + nginx
   - Rollback plan: revert do backend nginx config se algo quebrar (npm install ja resolveu SDK 0.3 mas backend pode reverter pra 0.2)

## Validacao end-to-end pos-deploy

```bash
# 1. /auth/sdk-token deve funcionar nos 2 caminhos
curl -i -X POST https://api.dsplayground.com.br/auth/sdk-token \
    -H "Origin: https://acme.test" -d '{"publishable_key":"pk_..."}'

curl -i -X POST https://dsplayground.com.br/api/auth/sdk-token \
    -H "Origin: https://acme.test" -d '{"publishable_key":"pk_..."}'

# 2. Socket.IO em ambos os paths
wscat -c wss://api.dsplayground.com.br/socket.io/?EIO=4&transport=websocket
wscat -c wss://dsplayground.com.br/api/socket.io/?EIO=4&transport=websocket

# 3. SDK v0.3.0 + portfolio bumpado: abrir browser, ver logs do backend
```

## Itens descartados

- **Manter status quo**: nao resolve o bug do SDK e a redundancia visual continua confundindo clientes novos.
- **Backend hardcoded `/api/` mesmo no api.X**: opcao mais conservadora mas amplifica a redundancia (forca o cliente a sempre escrever `https://api.X/api/...`). Reprovado por estetica e consistencia.

## Referencias

- `backend/app.py:34` — `api_bp = Blueprint('api', __name__, url_prefix='/api')` (parece morto, vale checar)
- `backend/app.py:331` — registro condicional do `auth_bp`
- `backend/app.py:125` — Socket.IO path
- SDK `src/WebSocketService.tsx:208` — Socket.IO path no client
- SDK `src/authClient.ts:69` — montagem de URL pra `/sdk-token`
- `ark/nginx/portifolio.conf:36` — server_name compartilhado entre apex e api.X
- `ark/nginx/portifolio.conf:127` — vhost api.X com `proxy_pass` direto
