# CLAUDE.md — VPS de producao (dsplayground.com.br)

Este arquivo guia o Claude Code ao operar esta VPS. O foco e gerencia de servidor: inspecionar containers, ler logs, aplicar mudancas via Ansible/Compose e nao pisar em producao.

## Identidade do host

- **Host**: `vps-15240803.vpsbr-15240803.vpshostgator.com.br` (HostGator)
- **OS**: Rocky Linux 9.7 (kernel `5.14.0-611.47.1.el9_7`)
- **Dominios publicos**: `dsplayground.com.br` (apex → frontend), `api.dsplayground.com.br` (backend), `grafana.dsplayground.com.br`, `influx.dsplayground.com.br`
- **Cloudflare**: modo **Full (strict)**, DNS proxiado (laranja) para todos os subdominios
- **SSH**: porta `22022` (firewalld + fail2ban). Ingress externo em portas non-standard e bloqueado pelo provedor — por isso o CI/CD usa **self-hosted runner** na propria VPS.
- **Ambiente**: `production` (ver `/opt/portifolio/ark/ansible/inventory.ini`)

## Repositorio

- Raiz: `/opt/portifolio` — dono `deploy:analytics`, modo `0750`
- Infra/operacao: `/opt/portifolio/ark/` (Nginx, Ansible, CrowdSec, monitoramento)
- App: `backend/` (Flask + Socket.IO + InfluxDB + Postgres), `frontend/` (React + Vite, build estatico servido por nginx:alpine)
- **Repos externos relacionados** (este monorepo NAO contem o codigo deles, mas depende):
  - **`landing/` aqui e ESPELHO MANUAL** do repo `danpqdan/comercial` (CF Pages builda do `comercial`, nao deste repo). Mudancas em `landing/` SEM replicar no `comercial` ficam invisiveis em prod do apex `dsplayground.com.br`.
  - **SDK de analytics** vive no repo separado `danpqdan/dsplayground-analytics-sdk` (publico, GitHub Packages). Frontend consome como dep npm `@danpqdan/dsplayground-analytics-sdk`. **Nao tem pasta `sdk/` aqui** — pra mexer no SDK, ir no repo dele.
  - Detalhes operacionais: `ark/docs/embed-iframe.md` -> "Gotchas conhecidos da Fase 1" #2.
- Leitura obrigatoria antes de mexer em app: `/opt/portifolio/AGENTS.md` e `/opt/portifolio/README.md`
- Leitura obrigatoria antes de mexer em infra: `/opt/portifolio/ark/README.md` e `/opt/portifolio/ark/docs/servidor-producao.md` (**este e a fonte canonica da arquitetura atual** — CLAUDE.md e resumo)

## Stack em execucao (docker ps)

Oito containers em tres compose files distintos:

| Container | Imagem | Porta host | Compose file |
|---|---|---|---|
| `portifolio-frontend` | `portifolio-frontend` (nginx:alpine + bundle Vite) | `127.0.0.1:3000→:80` | `/opt/portifolio/docker-compose.yml` |
| `portifolio-backend` | `portifolio-backend` (Flask + Socket.IO) | `127.0.0.1:5000→:5000` | `/opt/portifolio/docker-compose.yml` |
| `portifolio-influxdb` | `influxdb:2.7` | `127.0.0.1:8086→:8086` | `/opt/portifolio/docker-compose.yml` |
| `portifolio-postgres` | `postgres:16-alpine` | so na rede docker (sem publish) | `/opt/portifolio/docker-compose.yml` |
| `portifolio-prometheus` | `prom/prometheus:v2.54.1` | `0.0.0.0:9090` *(TODO → loopback)* | `ark/monitoring/docker-compose.monitoring.yml` |
| `portifolio-grafana` | `grafana/grafana:11.2.0` | `127.0.0.1:3001→:3000` | `ark/monitoring/docker-compose.monitoring.yml` |
| `portifolio-node-exporter` | `prom/node-exporter:v1.8.2` | `0.0.0.0:9100` *(TODO → loopback)* | `ark/monitoring/docker-compose.monitoring.yml` |
| `portifolio-crowdsec` | `crowdsecurity/crowdsec:v1.6.3` | `127.0.0.1:6060`, `127.0.0.1:8080` | `ark/crowdsec/docker-compose.crowdsec.yml` |

Redes docker:
- `portifolio_default` (bridge) — rede da app (backend, postgres, influxdb, frontend); monitoring e crowdsec entram nela via `external: true`
- `monitoring_portifolio-monitoring` (bridge) — isola Prometheus/Grafana/node-exporter

Volumes persistentes (nao apagar sem checar):
- `portifolio_influxdb_data`, `portifolio_influxdb_config` — series temporais
- `portifolio_postgres_data` — auth multi-tenant (clientes, tokens, refresh, quotas, audit)
- `portifolio_backend_keys` — chaves RSA do `sdk_jwt` (`/app/data/keys/sdk_jwt_{private,public}.pem`). Criado com `root:root`, `analytics-stack` chown 10001:10001 antes do `up`.
- `monitoring_prometheus-data`, `monitoring_grafana-data` — metricas e dashboards
- `crowdsec_crowdsec-db`, `crowdsec_crowdsec-config` — decisoes e config do agente

## Arquitetura de trafego

```
Internet → Cloudflare (laranja, Full strict, Origin Cert wildcard ate 2041)
              ├→ dsplayground.com.br (apex)  → CF Pages (repo `comercial`)
              │   • landing comercial Astro estatica — fora do nginx host
              │
              └→ Nginx host (80/443, TLS CF Origin Cert)
                    ├─ app.dsplayground.com.br      → 127.0.0.1:3001 (Grafana c/ auth.proxy)
                    │    └─ /cliente/metricas/*  → auth_request /__cliente_auth_gate
                    │       (Flask valida cookie → X-WEBAUTH-USER → Grafana)
                    ├─ portifolio.dsplayground.com.br → 127.0.0.1:3000 (portfolio React 3D)
                    │    └─ /api/*  → 127.0.0.1:5000 (nginx strippa /api/, paths canonicos)
                    ├─ api.dsplayground.com.br      → 127.0.0.1:5000 (backend Flask, paths canonicos sem /api/)
                    │                                  WS em /socket.io/, REST em /auth/sdk-token, /cliente/auth/*
                    ├─ grafana.dsplayground.com.br  → 127.0.0.1:3001 (Grafana — admin direto)
                    └─ influx.dsplayground.com.br   → 127.0.0.1:8086 (InfluxDB)

Backend → influxdb:8086, postgres:5432 (rede portifolio_default)
CrowdSec le /var/log/nginx + backend/security.log → aplica decisoes via bouncer
Prometheus scrape backend:5000/metrics (quando existir) + node-exporter

Cookie cliente_session: HttpOnly+Secure+SameSite=Strict+Domain=dsplayground.com.br
(env COOKIE_DOMAIN no backend) — viaja entre apex (landing CF Pages), app.X
(dashboard) e api.X same-site.

Dashboard do cliente (detalhes em ark/docs/dashboard-cliente.md):
  Browser → app.dsplayground.com.br/cliente/metricas/* → nginx auth_request /__cliente_auth_gate
        → Flask /cliente/auth/gate (valida cookie cliente_session — funciona porque Domain=eTLD+1)
        → 200 + header X-WEBAUTH-USER=<site_id>
        → nginx propaga pro Grafana
        → Grafana auth.proxy confia no header e mapeia user
        → 401 → redirect 302 pra https://dsplayground.com.br/cliente/login (landing CF Pages)
```

Detalhes completos em `/opt/portifolio/ark/docs/servidor-producao.md`.

## Comandos operacionais

Sempre que possivel, use os alvos do `Makefile` em `/opt/portifolio/ark/Makefile` (invocar a partir de `/opt/portifolio`):

```bash
make -f ark/Makefile ps                # estado dos containers da app
make -f ark/Makefile logs              # tail -f backend
make -f ark/Makefile restart           # restart backend + frontend
make -f ark/Makefile dev               # compose up -d (rebuild se preciso)
make -f ark/Makefile monitoring-up     # Prometheus + Grafana
make -f ark/Makefile crowdsec-up       # CrowdSec
make -f ark/Makefile ansible-check     # playbook dry-run (**hoje quebra — ver pendencias**)
make -f ark/Makefile ansible-apply     # aplicar playbook
```

Comandos docker uteis fora do Makefile:

```bash
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
docker stats --no-stream
docker logs --tail 200 -f portifolio-backend
docker inspect portifolio-backend --format '{{.State.Health.Status}}'
```

Health checks da aplicacao (via loopback — backend bindando so em `127.0.0.1:5000`, so Nginx alcanca). Em prod o blueprint tem `url_prefix=/api`; em dev local nao tem prefixo (ver `app.py:31`).

```bash
curl -s http://127.0.0.1:5000/health/app
curl -s http://127.0.0.1:5000/health/socketio
curl -s http://127.0.0.1:5000/health/influxdb
```

## CI / CD (GitHub Actions + self-hosted runner)

Quatro workflows em `.github/workflows/`:

| Workflow | Trigger | Responsabilidade |
|---|---|---|
| `ci.yml` | PR, push em `main` | `docker-compose config`, ansible syntax, frontend lint+test+build, backend lint+test |
| `prod-regression.yml` | push em paths sensiveis + cron diario 03:17 UTC | smoke via curl: sem debugger Werkzeug, sem `/console`, sem rota sem prefixo `/api`, bundle estatico servido |
| `deploy.yml` | `workflow_run` CI OK em `main` (+ `workflow_dispatch`) | CD app: runner na VPS roda `git reset --hard origin/main` + `docker compose up -d --build --force-recreate --no-deps backend frontend` + health |
| `ansible-apply.yml` | push em `main` com path `ark/ansible/**` (+ `workflow_dispatch`) | CD infra: `make -f ark/Makefile ansible-apply` + recreate condicional do backend se `backend/.env` mudou (md5 antes/depois) |

**Limites do CD automatico:** roles Ansible / vault / templates de `.env` agora aplicam automaticamente via `ansible-apply.yml`. Os dois workflows compartilham concurrency group `deploy-production` — serializam pra evitar race entre apply (escreve `.env`) e rebuild (recreate de container). Mudancas em outros composes (`ark/monitoring/`, `ark/crowdsec/`) ainda exigem `make monitoring-up` / `crowdsec-up` manual — eles ficam fora do escopo do playbook principal.

**Self-hosted runner:** servico systemd `actions.runner.danpqdan-portifolio.vps-production.service`, roda como `deploy`, label `production-vps`, em `/opt/actions-runner/`. Necessario porque HostGator bloqueia SSH externo em `22022` — runner puxa jobs via HTTPS outbound.

**Risco:** runner em repo publico e perigoso (forks rodam com acesso ao host). Se o repo tornar-se publico, desinstalar o runner imediatamente.

**Rollback manual** (logado como `deploy`):
```bash
cd /opt/portifolio
git reset --hard <sha-anterior>
docker compose up -d --build --force-recreate --no-deps backend frontend
```

## Permissoes e bind-mounts

Grupo compartilhado **`analytics` GID 10001** e a ponte host↔container. Nao mude ownership de `/opt/portifolio` sem reler a tabela em `ark/docs/servidor-producao.md`. Regras criticas:

- `/opt/portifolio/backend/` usa SGID (`2770`) — novos arquivos herdam grupo `analytics`.
- `/opt/portifolio/backend/.env` e `ark/monitoring/.env` sao `0640` dono `deploy:analytics`. Nunca versionar.
- `/var/run/docker.sock` e `root:docker` — `deploy` entra pelo grupo `docker`.
- Nginx vhosts em `/etc/nginx/conf.d/portifolio.conf` (apex + api) e `portifolio.monitoring.conf` (grafana + influx), layout Rocky/RHEL, `root:root 0644`.
- TLS origin: `/etc/ssl/cloudflare-origin/fullchain.pem` (`0644`) + `privkey.pem` (`0600`), ambos `root:root`, validade ate 2041.

**Apos qualquer `Edit`/`Write` em arquivo sob `/opt/portifolio/` rodar `chown deploy:analytics <arquivo>`** — senao o container bate `EACCES` no runtime.

## Seguranca — o que NAO fazer

- **Nao expor `5000` (backend), `3000` (frontend), `8086` (InfluxDB), `3001` (Grafana) nem `5432` (Postgres) publicamente**. Em prod so Nginx acessa — bindings estao em `127.0.0.1:<porta>` (ou sem publish no caso do Postgres).
- **Nao adicionar `environment:` inline no `docker-compose.yml` para variaveis de runtime do backend**. A fonte unica e `backend/.env` gerado pelo Ansible (`templates/backend.env.j2`). Regressao desse padrao ressuscita o bug dev-em-prod (ver memoria `project_deploy_state.md`).
- **Nao rodar `docker compose down -v`** em nenhum dos tres composes — apaga volumes com series do InfluxDB, auth do Postgres, chaves RSA do backend, decisoes do CrowdSec e dashboards Grafana.
- **Nao editar configs direto no host** — sempre ajustar no repo e re-aplicar via Ansible/Compose. Mudanca manual se perde no proximo `ansible-apply`.
- **Nao versionar segredos**: `INFLUXDB_TOKEN`, `SECRET_KEY`, `ADMIN_API_TOKEN`, `POSTGRES_PASSWORD`, senha Grafana vivem em `group_vars/all.yml` (deveria estar em Ansible Vault — hoje em cleartext, ver pendencias) ou `.env` local (gitignored).
- **Rotacao de `postgres_password` exige rotacionar tambem o role no cluster** — coberto pela role `analytics-stack` (task `Rotacionar senha do role Postgres ...`) desde 2026-05-01 apos incidente de 502 publico. `POSTGRES_PASSWORD` em compose so e honrada no initdb. Detalhes em `ark/docs/servidor-producao.md` -> "Rotacao de postgres_password".
- **Nao usar `--no-verify`, `push --force`, `reset --hard`** sem autorizacao explicita.
- **DNS proxiado**: se algum subdominio estiver cinza (DNS only) na Cloudflare, o TLS quebra — o CF Origin Cert so vale quando o trafego passa pela laranja.

## Fluxo de mudanca em producao

1. Editar arquivo relevante dentro de `/opt/portifolio` (app) ou `/opt/portifolio/ark` (infra).
2. Se for infra gerenciada por Ansible: `make -f ark/Makefile ansible-check` primeiro (**hoje quebra por falta de `ignore_errors` na task de health — ver pendencias**), depois `ansible-apply`.
3. Se for so app (backend/frontend): o CD automatico ja cuida apos merge em `main`. Para deploy manual: `make -f ark/Makefile dev` e validar `/health/app`.
4. Conferir logs: `make -f ark/Makefile logs` e `docker logs` dos containers relacionados.
5. Nao comitar sem o usuario pedir. Quando pedir, seguir Conventional Commits em pt-BR (ver `AGENTS.md`).

## CORS e origens permitidas

Backend opera com CORS **estatico** por enquanto: lista vem de `cors_origins` em `group_vars/all.yml` (vault Ansible) -> `CORS_ORIGINS` no `.env` -> `Flask-CORS` + `socketio.cors_allowed_origins`. Cobre so dominios da propria plataforma (`dsplayground.com.br` + subdominios). **Nao escala para clientes** — cada novo dominio assinante exige editar o vault e re-aplicar.

Adicionar uma origem hoje:

1. `cd ark/ansible && ansible-vault edit group_vars/all.yml` (ajusta `cors_origins:`).
2. Commitar e abrir PR com a mudanca encriptada do vault. Apos merge em `main`, `ansible-apply.yml` aplica automaticamente e recria o backend (detecta mudanca de `.env` por hash md5).
3. Validar: `docker exec portifolio-backend env | grep CORS_ORIGINS`.

Hotfix urgente sem PR: `make -f ark/Makefile ansible-apply` na VPS + `docker compose up -d --force-recreate --no-deps backend`. Mas comitar a mudanca do vault depois pra prod nao divergir do repo.

Detalhes do plano de migracao para CORS dinamico (por `sites.dominios_permitidos`, ja previsto no schema do Postgres) em `docs/plano-clientes-ambientes.md` -> "CORS e origens permitidas".

## Observabilidade

- Logs da app sao estruturados (`evento=<nome> chave=valor`). Eventos-chave: `conectado`, `recebido`, `validado`, `rejeitado`, `persistido_*`, `erro_persistencia`, `backpressure`, `acesso_bloqueado`, `[ADMIN-AUDIT]`.
- `backend/security.log` rotaciona em 10 MB x 5 arquivos e e lido pelo CrowdSec.
- Grafana: `https://grafana.dsplayground.com.br` (via Nginx) — admin user/senha via `ark/monitoring/.env`.
- Prometheus: `http://<host>:9090` (ainda publico, **TODO**) — retencao 15 dias (`--storage.tsdb.retention.time=15d`).

## Estado dos fixes 2026-04-22 (revisado 2026-05-02)

**Aplicados em prod (confirmados):**
- ✅ Backend `gunicorn --worker-class eventlet -w 1` rodando.
- ✅ Certbot removido; CF Origin Cert e a unica fonte de TLS (validade ate 2041).
- ✅ Prometheus (`9090`) e node-exporter (`9100`) bindam em `127.0.0.1` no `ark/monitoring/docker-compose.monitoring.yml`. Sem porta publica externa.

**Codigo pronto no repo, falta efetivar via ansible-apply:**
- 🟡 Logger root do Flask separado do `security_logger` em `backend/app.py:91-96` (`propagate = False`, file handler exclusivo no logger nomeado `security`).
- 🟡 `roles/analytics-stack/tasks/main.yml` ja tem `when: not ansible_check_mode` nas tasks de health.

**A confirmar via SSH (so dah pra validar no host):**
- 🔍 **Vault encryption:** `group_vars/all.yml` na VPS deve estar criptografado (`$ANSIBLE_VAULT;1.1;AES256` na primeira linha).

## Marcos 2026-05-02

**Landing/dashboard cliente — reformulacao SaaS-grade:**
- ✅ Design system proprio em `landing/src/components/ui/` — 13 componentes (Badge, Tabs, Toast, Modal/EmptyState, MetricCard, ChartCard, Stepper, Breadcrumbs, etc.) com tokens semanticos (success/warning/danger/info) em `@theme` do Tailwind 4.
- ✅ 18 paginas Astro: home, /precos, /recursos, /seguranca, /sobre, /integracoes, /changelog, /status, 404/500 + area cliente (cadastro, login, esqueci-senha, painel, configuracoes 7 abas, onboarding wizard 3 passos, exportar).
- ✅ Telemetria explicita em milestones de funil (onboarding_step_concluido, key_copiada, snippet_copiado, primeiro_evento + trackConversion).
- ✅ Live counter no painel — polling /cliente/auth/configuracoes a cada 30s, pill "live ●" pulsante, pausa quando aba esconde.
- ✅ Mobile fix: Tabs com 7+ entradas usa `overflow-x-auto + whitespace-nowrap + flex-shrink-0` (era flex-wrap, empilhava feio em 375px).
- ✅ 5 links pra `github.com/danpqdan/portifolio/issues` substituidos por `mailto:contato@dsplayground.com.br?subject=...` (repo privado, links 404avam pra anonimo). CF Email Routing pra contato@ ja configurado.

**Stack landing/ atualizada (security audit):**
| Pacote | Antes | Depois |
|---|---|---|
| astro | ^4.16.7 | ^6.2.1 |
| @astrojs/tailwind | ^5.1.2 | removido (deprecated) |
| @tailwindcss/vite | — | ^4.2.4 |
| tailwindcss | ^3.4.13 | ^4.2.4 |
| vitest | ^2.1.3 | ^3.2.4 |
| happy-dom | ^15.7.4 | ^20.9.0 (CRITICAL RCE fix) |
| `overrides.yaml` | — | ^2.8.3 |

`tailwind.config.mjs` deletado — tokens em `@theme {}` em `src/styles/global.css`. `@tailwind base/components/utilities` → `@import "tailwindcss"`. `astro.config.mjs`: `integrations:[tailwind()]` → `vite:{plugins:[tailwindcss()]}`.

`npm audit`: **found 0 vulnerabilities** (era 12: 1 CRITICAL + 1 HIGH + 10 moderate).
Vitest: 245/245 verde. astro check 0 errors. astro build 18 paginas.

**Fixes CI 2026-05-02:**
- ✅ `backend/billing/test_plano_service.py` — testes legados usavam plano `pequeno`/`medio`/`grande` mas `plano_service.PLANO_DEFAULTS` ja refatorou pra `free`/`pro`. Renomeei tests + asserts.
- ✅ `backend/billing/test_routes.py` — esperava 4 planos, route lista 2. Atualizado.
- ✅ `backend/test_cliente_configuracoes.py` — mesma coisa, 4→2.
- ✅ Ansible `Subir stack com docker compose` quebrava com `Error while parsing JSON output of /bin/docker compose images --format json` quando container parado apontava pra imagem deletada. Pre-task `docker container prune -f` + `recreate: auto` em `roles/analytics-stack/tasks/main.yml`.

`SECRET_KEY=test pytest backend/` → 441 passed, 13 subtests.

**Workflow worktree:** trabalho em `D:/comercial-wt`, `D:/portifolio-wt`, `D:/portifolio-fix2/3` (criados ad-hoc com `git worktree add`) pra nao conflitar com working tree principal. Removidos no fim de cada PR.

**Nao e mais pendencia (do bloco anterior):** instalacao do bouncer-nginx via packagecloud — bouncer (`crowdsec-firewall-bouncer-nftables`) ja vem por default com a instalacao do CrowdSec via repo oficial.

## Quando em duvida

- Arquitetura e ordem de deploy → `ark/docs/servidor-producao.md` (fonte canonica)
- Como trafego entra → `ark/nginx/README.md` + `ark/nginx/portifolio.conf`
- Bloqueios automatizados → `ark/crowdsec/README.md`
- Provisionamento do zero → `ark/ansible/README.md` + `playbook.yml`
- Padroes de codigo da app → `AGENTS.md`

Se um comando puder afetar dados persistentes, a rede publica, ou derrubar servico — pergunte antes de executar.
