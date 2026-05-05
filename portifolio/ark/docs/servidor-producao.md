# Arquitetura de servidor — producao

## Visao geral

```
                            Internet
                               |
                               v
                        +--------------+
                        | Cloudflare   |  Proxy CDN + Origin Certificate
                        | (laranja)    |  modo Full (strict)
                        +------+-------+
                               |
                               v
                        +--------------+
                        |    Nginx     |  TLS (CF Origin cert), rate limit,
                        |   (host)     |  /admin allowlist, WS upgrade
                        +------+-------+
                    ___________|_______________________________
                   /           |             |                 \
                  v            v             v                  v
             dsplayground. api.dspl...  grafana.dspl...   influx.dspl...
                  |            |             |                  |
                  v            v             v                  v
           +-------------+  +-------+   +---------+        +-----------+
           |  Frontend   |  |Backend|   | Grafana |        | InfluxDB  |
           | nginx:80    |  | :5000 |   |  :3001  |        |  :8086    |
           | (dist Vite) |  +---+---+   +----+----+        +-----+-----+
           +-------------+      |            |                   |
                                |            |                   |
                                v            v                   |
                          +----------+    Prometheus <-----------+
                          | InfluxDB | <------+
                          +----------+        |
                         (portifolio_prod)   CrowdSec agent (le security.log + /var/log/nginx)
```

## Papeis dos componentes

| componente | responsabilidade |
|---|---|
| Nginx | TLS, compressao, upgrade WebSocket, rate limit de borda, bloqueio de paths admin, `auth_request` do dashboard self-service |
| Backend | recebe `analytics_data`, valida, persiste no InfluxDB, serve API de consulta + admin LGPD + auth do dashboard cliente |
| InfluxDB | series temporais de analytics em tres measurements: `page_analytics` (agregados temporais por sessao+pagina, fields `cliques`, `visualizacoes`, `scrolls`, `mouse_moves`, `hovers`, `toques`, `exposicoes`, `permanencia_segundos`, `custom_events`, `user_agent`), `web_vitals` (LCP/CLS/INP/FCP/TTFB, field `valor`, tag `nome` + `rating`), `custom_events` (`enviarEvento`, field `ocorrencias`, tag `nome`, propriedades como tags whitelisted). Tags comuns: `ambiente`, `app_id`, `page_type`, `session_id`, `ip_address`, `device_type`, `pais`, `referrer_dominio`. Backend persiste via `influxdb_service.py:create_*_from_heatmap` chamados em `ingestao/servico_ingestao.py:541-565`. |
| PostgreSQL | auth multi-tenant: `sites`, `site_dominios`, `publishable_keys`, `quotas`, `emissoes_jwt`, `consumo_diario` (SDK ingest); `clientes_users`, `clientes_users_sessoes`, `clientes_magic_links` (dashboard humano — ver `ark/docs/dashboard-cliente.md`) |
| Prometheus | scrape de metricas operacionais do backend e do host |
| Grafana | dashboards de analytics + dashboard self-service do cliente em `/cliente/metricas` (auth.proxy via header `X-WEBAUTH-USER` injetado pelo nginx) |
| CrowdSec | le `security.log` + `/var/log/nginx/`, aplica decisoes em Nginx via bouncer |

## Ordem de deploy via Ansible

1. `base` — pacotes via `dnf`, firewalld, fail2ban, usuario deploy (grupo `wheel`)
2. `docker` — engine + compose do repo oficial CentOS
3. `analytics-stack` — clona repo, sobe backend/InfluxDB/frontend, aplica retencao
4. `nginx` — proxy + certbot (layout `/etc/nginx/conf.d/`)
5. `monitoring` (opt-in) — Prometheus + Grafana
6. `crowdsec` (opt-in) — agente + bouncer Nginx

> OS alvo: **Rocky Linux 9** (RHEL 9). Para Debian/Ubuntu, ver branch `dev`.

`ansible-playbook -i inventory.ini playbook.yml --tags analytics-stack` para re-deploy apenas da app.

## Portas expostas

| porta | servico | exposicao |
|---|---|---|
| 22022 | SSH | publica (firewalld + fail2ban) |
| 80 | Nginx | publica (redireciona para 443) |
| 443 | Nginx | publica |
| 5000 | Backend | **loopback** (`127.0.0.1:5000`) — Nginx publica em `api.dsplayground.com.br` |
| 3000 | Frontend (nginx:alpine servindo bundle Vite) | **loopback** (`127.0.0.1:3000→:80`) — Nginx do host publica no apex `dsplayground.com.br` |
| 8086 | InfluxDB | **loopback** (`127.0.0.1:8086`) — rede docker + nginx em `influx.dsplayground.com.br` |
| 3001 | Grafana | loopback (`127.0.0.1:3001`) — atras de nginx em `grafana.dsplayground.com.br` |
| 9090 | Prometheus | **TODO** ainda `0.0.0.0:9090`, deve virar loopback |
| 9100 | node-exporter | **TODO** ainda `0.0.0.0:9100`, deve virar loopback |

## TLS — Cloudflare Origin Certificate

Desde 2026-04-21 o origin nao usa mais Let's Encrypt. O cert agora e um **Cloudflare Origin Certificate** wildcard (`*.dsplayground.com.br` + apex), validade 15 anos, assinado pela CA privada do CF. Arquivos:

| Arquivo | Dono | Modo |
|---|---|---|
| `/etc/ssl/cloudflare-origin/fullchain.pem` | `root:root` | `0644` |
| `/etc/ssl/cloudflare-origin/privkey.pem` | `root:root` | `0600` |

O CF opera em modo **Full (strict)** — o cert do origin e validado na borda da CF antes de fechar o TLS com o browser. Como a CA do CF nao esta no trust store publico, `openssl s_client` direto no origin da `Verify return code: 21` (comportamento esperado); `ssl_stapling` tambem e silenciosamente ignorado no nginx (warning benigno).

DNS dos subdominios (`dsplayground.com.br`, `api.*`, `grafana.*`, `influx.*`) precisa ficar **proxiado (laranja)** na Cloudflare. Se algum registro estiver cinza (DNS only), o CF nao intermedeia, o cert nao vale pra ele e o TLS quebra pra esse hostname.

Renovacao: nao ha — cert dura ate 2041. Quando trocar, atualizar os dois arquivos em `/etc/ssl/cloudflare-origin/` e reload do nginx.

## Roteamento Nginx

Dois arquivos de vhost em `/etc/nginx/conf.d/`:

| Arquivo | Hostnames | Upstream |
|---|---|---|
| `portifolio.conf` | `dsplayground.com.br` | `127.0.0.1:3000` (frontend — nginx no container servindo dist/) |
|  | `dsplayground.com.br/cliente/auth/*` | `127.0.0.1:5000` (backend — login humano do dashboard) |
|  | `dsplayground.com.br/cliente/metricas/*` | `127.0.0.1:3001` (Grafana — atras de `auth_request /__cliente_auth_gate`) |
|  | `api.dsplayground.com.br` | `127.0.0.1:5000` (backend Flask) |
| `portifolio.monitoring.conf` | `grafana.dsplayground.com.br` | `127.0.0.1:3001` (admin direto, fora do auth.proxy) |
|  | `influx.dsplayground.com.br` | `127.0.0.1:8086` |

Socket.IO: path canonico `/socket.io/` em todos os ambientes. O backend hardcode esse path independente de `FLASK_ENV` (ver `backend/app.py` `socketio_config['path']`); o cliente `socket.io-client` tem `path: '/socket.io/'` em `frontend/src/sdk/WebSocketService.tsx`. Requests WS da forma `wss://api.dsplayground.com.br/socket.io/` passam pelo `location /` do vhost da api (upgrade habilitado) e chegam no backend. Em dev local sem nginx, o frontend bate direto em `http://localhost:5000/socket.io/`. `async_mode='eventlet'` em todos os ambientes — sem isso o handshake retorna `upgrades:[]` e o cliente cicla em polling.

### Dashboard self-service do cliente

Fluxo do `/cliente/metricas/*` (detalhes em `ark/docs/dashboard-cliente.md`):

```
Browser -> nginx (location /cliente/metricas/)
        -> auth_request /__cliente_auth_gate
        -> Flask /cliente/auth/gate (valida cookie cliente_session)
        -> 200 + header X-WEBAUTH-USER=<site_id>
        -> proxy_pass para Grafana 127.0.0.1:3001
        -> Grafana auth.proxy confia no header e auto-cria/mapeia user
```

Login humano em `/cliente/login` (frontend React) emite cookie `cliente_session` (HttpOnly, Secure, SameSite=Strict, 7d). Suporta senha (POST `/cliente/auth/login`) e magic-link (`/magic-link/solicitar` + `/magic-link/verificar`). Logout em `POST /cliente/auth/logout`.

Frontend em producao e um bundle estatico (`vite build`) servido por `nginx:alpine` dentro do container `portifolio-frontend` — nao ha dev server exposto. SPA fallback em `docker-nginx.conf` serve `index.html` para qualquer rota nao-estatica. URLs da API sao embutidas no bundle em build time via build args `VITE_API_URL` e `VITE_WEBSOCKET_URL`, vindos do `.env` do compose (gerado pelo Ansible) — alterar esses valores exige rebuild da imagem.

Configuracao do backend: variaveis de runtime moram em `backend/.env` (renderizado por `ark/ansible/roles/analytics-stack/templates/backend.env.j2`). O `docker-compose.yml` consome via `env_file:`, nao ha `environment:` inline. Nunca reintroduzir `FLASK_ENV` ou bucket no bloco `environment:` do compose — regressao direta do incidente dev-em-prod de 2026-04-21.

## Volume `portifolio_backend_keys` (chaves RSA do SDK JWT)

O backend roda como **UID 10001** (ver Dockerfile) e escreve/le `/app/data/keys/sdk_jwt_{private,public}.pem`. Docker cria volumes novos com `root:root`, entao o backend recebe `PermissionError` na primeira geracao das chaves. A role `analytics-stack` garante o chown correto **antes** do `docker compose up` rodando `docker run --rm -v portifolio_backend_keys:/mnt alpine chown -R 10001:10001 /mnt`. Task idempotente — se o volume for recriado (ex.: `down -v`), proximo `ansible-apply` restaura.

## CI / CD

Tres workflows em `.github/workflows/`:

| Workflow | Trigger | Responsabilidade |
|---|---|---|
| `ci.yml` | PR, push em `main` | `docker-compose config`, ansible syntax, frontend lint+test+build, frontend docker build multi-stage, backend lint+test |
| `prod-regression.yml` | push em paths sensiveis + cron diario 03:17 UTC | smoke via curl: debugger Werkzeug, `/console`, rota sem prefixo `/api`, bundle estatico do frontend servido |
| `deploy.yml` | `workflow_run` de CI concluido com sucesso em `main` (tambem `workflow_dispatch`) | CD: self-hosted runner na VPS roda `git reset --hard origin/main`, `docker compose up -d --build --force-recreate --no-deps backend frontend`, health check |

**Limites do CD automatico:** re-builda apenas `backend` e `frontend` (onde o codigo de app muda). InfluxDB/Postgres nao sao tocados. Mudancas em roles Ansible, nginx do host, monitoring ou crowdsec continuam exigindo `make -f ark/Makefile ansible-apply` manual — SSH na VPS e aplicar. Rationale: mudancas de infra em geral precisam de `sudo`/`become`, envolvem o host fora do docker, e raramente sao frequentes o bastante pra justificar o risco de automacao.

### Self-hosted runner (porque SSH externo nao passa)

O provedor (HostGator) bloqueia ingress em portas non-standard (`22022`) para IPs fora do datacenter, entao um runner `ubuntu-latest` da AWS nunca chega no `sshd`. Solucao: rodar o runner do GitHub Actions dentro da propria VPS, puxando jobs via HTTPS outbound (`443`, que passa).

**Localizacao:** `/opt/actions-runner/` — owner `deploy:deploy`.

**Servico:** `actions.runner.danpqdan-portifolio.vps-production.service` (systemd), roda como user `deploy` (membro de `docker` e `analytics`, entao pode rebuildar containers e ler `/opt/portifolio`).

**Label:** `production-vps`. O workflow declara `runs-on: [self-hosted, production-vps]` — sem label, qualquer job `self-hosted` do repo pegaria este runner.

**Risco conhecido:** self-hosted runners em repos publicos sao perigosos (PRs de forks rodam com acesso ao host). Se o repo virar publico no futuro, desinstalar o runner imediatamente ou mudar para modelo com approval manual por PR.

**Operacao:**

```bash
# status
sudo systemctl status actions.runner.danpqdan-portifolio.vps-production

# logs ao vivo
sudo journalctl -u actions.runner.danpqdan-portifolio.vps-production -f

# parar temporariamente (deploys em fila ficam waiting)
sudo systemctl stop actions.runner.danpqdan-portifolio.vps-production

# re-registrar (ex: token expirou, renomear):
cd /opt/actions-runner
sudo ./svc.sh stop && sudo ./svc.sh uninstall
sudo -u deploy ./config.sh remove --token <NOVO_REMOVAL_TOKEN>
# depois rodar ./config.sh + ./svc.sh install deploy + ./svc.sh start novamente
```

### Rollback manual

O CD nao tem rollback automatico. Em caso de deploy ruim, logado na VPS como `deploy`:

```bash
cd /opt/portifolio
git reset --hard <sha-anterior>
docker compose up -d --build --force-recreate --no-deps backend frontend
```

## Segredos

- `INFLUXDB_TOKEN`, `SECRET_KEY`, `ADMIN_API_TOKEN`, credenciais Postgres — no `group_vars/all.yml` criptografado com Ansible Vault.
- Nunca versionar `all.yml` em claro — `.example.yml` e o unico que entra no git.

### Rotacao de `postgres_password`

`POSTGRES_PASSWORD` em `docker-compose.yml` so e honrada no **initdb** do
container Postgres (criacao do volume `portifolio_postgres_data`). Em
volume ja existente (re-deploy normal), o role `portifolio` mantem a senha
antiga — **rotacionar `postgres_password` no vault e rodar `ansible-apply`
NAO rotaciona a senha real do banco**. Resultado historico: backend
crash-loop com `FATAL: password authentication failed`, nginx 502 publico
(incidente 2026-05-01).

A role `analytics-stack` cobre isso desde 2026-05-01 com 2 tasks pos-`compose up`:

1. **Aguardar Postgres pronto pra aceitar comandos administrativos** — `pg_isready` com retry 10x3s.
2. **Rotacionar senha do role Postgres pra refletir vault atual (idempotente)** —
   `ALTER USER "{{ postgres_user }}" WITH PASSWORD '{{ postgres_password }}';`
   via `community.docker.docker_container_exec` com SQL no `stdin` (senha
   nao aparece em `ps`), `no_log: true`, conectando via socket Unix dentro do
   container (pg_hba default usa `trust` em conexoes locais).

Procedimento operacional pra rotacionar:

```bash
cd /opt/portifolio/ark/ansible
ansible-vault edit group_vars/all.yml
# trocar postgres_password por nova
make -f ../Makefile ansible-apply
# A role:
#   1. regenera backend/.env e compose .env com a nova senha
#   2. compose up (sobe stack)
#   3. ALTER USER no cluster pra alinhar com .env
#   4. health backend OK
```

Restricao: `postgres_password` **nao pode conter aspa simples** — escape
SQL nao e feito no template. Geracao recomendada e `secrets.token_urlsafe(32)`
(safe por construcao).

### Rotacao de `grafana_admin_password`

`GF_SECURITY_ADMIN_PASSWORD` no compose so e' aplicada no setup inicial do
Grafana — quando o volume `monitoring_grafana-data` e' criado pela primeira
vez. Em volume ja existente (re-deploy normal), o user `admin` mantem a senha
antiga. Quando o vault rotaciona `grafana_admin_password`, o backend regera
`backend/.env` com a senha NOVA e fica em descompasso com o Grafana, que
responde 401 `password-auth.failed` em todas as chamadas administrativas
(GrafanaSyncService no `/gate`, scripts `provisionar_cliente.py` e
`redo_dashboards.py`).

Mesmo padrao do bug Postgres acima — `analytics-stack` resolve com `ALTER USER`,
`monitoring` resolve com `grafana-cli admin reset-admin-password`.

A role `monitoring` cobre isso com 2 tasks pos-`compose up`:

1. **Aguardar Grafana pronto pra aceitar admin commands** — `wget /api/health` retry 15x4s.
2. **Rotacionar senha do admin Grafana pra refletir vault atual (idempotente)** —
   `grafana-cli admin reset-admin-password <senha>` dentro do container.
   Senha passa via env var (`docker exec -e GF_PW=...`); `no_log: true`
   esconde do log Ansible. `changed_when: false` porque CLI sempre executa
   mas e' idempotente.

Procedimento operacional pra rotacionar:

```bash
cd /opt/portifolio/ark/ansible
ansible-vault edit group_vars/all.yml
# trocar grafana_admin_password
make -f ../Makefile ansible-apply
# A role monitoring:
#   1. regenera ark/monitoring/.env e backend/.env
#   2. compose up -d (sobe stack)
#   3. grafana-cli reset-admin-password no cluster
#   4. backend GrafanaSyncService volta a autenticar
```

Recovery manual quando o ansible nao roda (debug):

```bash
PW=$(docker compose exec backend printenv GRAFANA_ADMIN_PASSWORD)
docker exec portifolio-grafana grafana-cli admin reset-admin-password "$PW"
```

## Owner:group — mapa operacional

Grupo compartilhado **`analytics` GID 10001** e a ponte entre host e containers para bind-mounts funcionarem sem UID mismatch. Criado pela role `base` no host e pelos Dockerfiles do backend/frontend.

| Local | User | Grupo primario | Grupos extras |
|---|---|---|---|
| Host — operacao | `deploy` | `deploy` | `wheel`, `docker`, **`analytics`** |
| Container `backend` | `app` (UID 10001) | `analytics` (GID 10001) | — |
| Container `frontend` | `nginx` (UID 101, image nginx:alpine) | `nginx` | — |
| Container `influxdb` | `influxdb` (UID 1000, image) | `influxdb` | — |
| Container `prometheus` / `node-exporter` | `nobody` | `nogroup` | — |
| Container `grafana` | `grafana` (UID 472) | `grafana` | — |
| Container `crowdsec` | `root` | `root` | (precisa ler logs de varios paths) |
| Host — nginx master | `root` | `root` | — |
| Host — nginx workers | `nginx` | `nginx` | — |

| Arquivo/diretorio | Dono | Modo | Obs |
|---|---|---|---|
| `/opt/portifolio/` | `deploy:analytics` | `0750` | outros nao listam |
| `/opt/portifolio/backend/` | `deploy:analytics` | `2770` | SGID: novos arquivos herdam grupo `analytics` |
| `/opt/portifolio/backend/.env` | `deploy:analytics` | `0640` | grupo le, outros nada |
| `/opt/portifolio/backend/security.log` | `deploy:analytics` | `0660` | grupo pode escrever — container backend (GID 10001) append ok |
| `/opt/portifolio/ark/monitoring/.env` | `deploy:analytics` | `0640` | Grafana + InfluxDB token |
| `/etc/nginx/snippets/ssl.conf` | `root:root` | `0644` | |
| `/etc/nginx/conf.d/portifolio.conf` | `root:root` | `0644` | layout Rocky/RHEL |
| `/etc/letsencrypt/live/<dominio>/privkey.pem` | `root:root` | `0600` | certbot controla |
| `/var/run/docker.sock` | `root:docker` | `0660` | `deploy` entra pelo grupo `docker` |
| `/var/log/nginx/portifolio.*.log` | `nginx:nginx` | default | |

Regra geral: **user dedicado** por superficie (app/node/deploy/nginx/root), **grupo `analytics`** como denominador comum onde processos precisam compartilhar arquivos atraves de bind-mount.

## Observabilidade em producao

Logs: estruturados no formato `evento=<nome> chave=valor`. Estagios principais:

- `conectado` / `desconectado` — ciclo de socket
- `recebido` / `validado` / `rejeitado` — pipeline de ingestao
- `persistido_temporal` / `persistido_webvital` / `persistido_customevent`
- `erro_persistencia` — falha de InfluxDB (nao derruba ingestao)
- `backpressure` — fila do executor > 50 itens
- `acesso_bloqueado` — middleware de seguranca bloqueou IP
- `[REAPER]` — background task limpou sessoes Socket.IO zombies (idle > `SESSION_IDLE_TIMEOUT`)
- `auth_cliente_login_ok` / `auth_cliente_login_fail` — login do dashboard (senha)
- `auth_cliente_magic_solicitado` / `auth_cliente_magic_consumido` / `auth_cliente_magic_invalido` — fluxo magic-link
- `auth_cliente_gate_ok` / `auth_cliente_gate_negado` — `auth_request` do nginx pro Grafana
- `[ADMIN-AUDIT]` — qualquer chamada aos endpoints `/admin/*`

`security.log` tem rotacao automatica (10 MB x 5 arquivos). Monte em volume dedicado em producao.

Metricas: endpoint `/metrics` no backend e follow-up (`docs/plano-backend.md` D.2). Quando existir, o Prometheus ja esta configurado para fazer scrape em `backend:5000/metrics`.

## Variaveis de ambiente (resumo)

Tudo vem do `backend/.env` (ou `ark/monitoring/.env` para Grafana). Renderizado pelo Ansible em prod.

**Backend (`backend/.env`):**

| Variavel | Default | Descricao |
|---|---|---|
| `SECRET_KEY` | (obrigatorio) | secret do Flask |
| `INFLUXDB_ENABLED` | false | habilita persistencia em Influx |
| `INFLUXDB_URL/TOKEN/ORG/BUCKET` | — | conexao InfluxDB; exigidos se enabled |
| `TENANTS_DATABASE_URL` | sqlite:///./data/tenants.db | postgres em prod, sqlite em dev |
| `JWT_KEYS_DIR` | ./data/keys | chaves RSA do sdk_jwt |
| `SDK_TOKEN_TTL_SECONDS` | 300 | TTL do token publico do SDK |
| `SDK_AUTH_REQUIRED` | true (em prod via Ansible; dev `.env.example` mantem false) | exige sdk_jwt em todos os Socket.IO connects — sem isso o handshake retorna `code=TOKEN_MISSING` e desconecta |
| `SESSION_REQUEST_LIMIT` | 10000 | maximo de batches por sessao Socket.IO; 0 desabilita |
| `SESSION_IDLE_TIMEOUT` | 180 | segundos sem atividade ate sessao virar zombie (reaper limpa) |
| `SESSION_REAPER_INTERVAL` | 30 | frequencia do reaper de zombies |
| `ANTIABUSE_REQS_PER_MIN` | 600 | janela 60s de tolerancia por IP no anti-abuse |
| `ANTIABUSE_BAN_TTL_SECONDS` | 300 | duracao do ban quando estoura threshold (em prod era permanente, agora TTL) |
| `ANTIABUSE_SKIP_PRIVATE` | true | pula bloqueio para IPs privados (loopback, docker bridge, redes internas) |
| `RESEND_API_KEY` | — | (opcional) envia magic-link via Resend; sem isso, fallback stdout |
| `EMAIL_FROM` | no-reply@dsplayground.com.br | remetente do magic-link |
| `DASHBOARD_BASE_URL` | https://dsplayground.com.br | base da URL do magic-link |
| `DASHBOARD_REDIRECT` | /cliente/metricas | destino apos consumir magic-link |
| `COOKIE_SECURE` | true | flag Secure no cookie de sessao do cliente; false em dev http |

**Monitoring (`ark/monitoring/.env`):**

| Variavel | Descricao |
|---|---|
| `GF_ADMIN_USER`, `GF_ADMIN_PASSWORD` | bootstrap do admin Grafana |
| `GF_ROOT_URL` | base do Grafana — em prod `https://dsplayground.com.br/cliente/metricas/` |
| `INFLUXDB_TOKEN`, `INFLUXDB_ORG`, `INFLUXDB_BUCKET` | passados ao container Grafana, interpolados no datasource provisionado |

**`auth.proxy` e configurado direto no `docker-compose.monitoring.yml`** via `GF_AUTH_PROXY_*` e `GF_USERS_AUTO_ASSIGN_ORG_ROLE=Viewer` — ver o arquivo pra valores.

## Backup e restore

Ver secao "Backup e Restore do InfluxDB" em `docs/backend/DEPLOY-GUIDE.md`.

Para PostgreSQL: `pg_dump` diario via cron sidecar, retencao 30 dias. A definir quando o schema estabilizar.
