# CLAUDE.md — dsplay (monorepo)

Guia operacional para agentes trabalhando neste workspace. Para fluxo git subtree e comandos de dev, ver `README.md`.

---

## Estrutura e fontes canônicas

Este monorepo consolida 5 repositórios via **git subtree** (não submodules — um clone simples traz tudo):

| Diretório | Upstream | Visibilidade | Canônico aqui? |
|---|---|---|---|
| `sdk/` | `DSPlayAnalytics/SDK` | Público | ✅ sim |
| `landing/` | `DSPlayAnalytics/landing` | Público | ✅ sim |
| `backend/` | `DSPlayAnalytics/backend` | Privado | ✅ sim |
| `ark/` | `DSPlayAnalytics/ark` | Privado | ✅ sim |
| `portifolio/` | `danpqdan/portifolio` | Público | ⚠️ legado |

**`portifolio/` é o repo antigo** (antes da separação em org). Contém cópias de `ark/` e `backend/` que estão defasadas. Não editar `portifolio/ark/**` nem `portifolio/backend/**` — usar `ark/` e `backend/` na raiz.

---

## Onde está cada coisa

| Precisa de | Leia |
|---|---|
| Operação da VPS, containers, deploys, segurança | `portifolio/CLAUDE.md` |
| Arquitetura geral + estado atual do produto | `portifolio/docs/PROJETO.md` |
| Backend Flask (API, auth, ingestão, billing) | `backend/README.md` |
| SDK de analytics (WebSocket, eventos, LGPD) | `sdk/README.md` |
| Landing + portal do cliente (Astro 6) | `landing/README.md` |
| Infra geral (Nginx, Ansible, CrowdSec, monitoramento) | `ark/README.md` |
| Arquitetura de servidor + ordem de deploy | `ark/docs/servidor-producao.md` ← **fonte canônica** |
| Dashboard do cliente — design doc | `ark/docs/dashboard-cliente.md` |
| Configuração Nginx + auth_request Grafana | `ark/nginx/README.md` |
| Provisionamento Ansible | `ark/ansible/README.md` |
| Contrato de eventos SDK | `sdk/docs/schema-eventos.md` + `sdk/docs/eventos-analytics-catalogo.md` |
| Auditoria de segurança | `ark/docs/seguranca-auditoria-2026-05-02.md` |
| Backup + disaster recovery | `ark/docs/backup-restore.md` |

---

## Regras para agentes

### Antes de mexer em qualquer área

- **Backend** (`backend/`): leia `backend/influxdb_service.py` para entender nomes de tags/fields antes de escrever queries Flux. Nunca assuma nomes — verificar o código.
- **VPS / infra**: `portifolio/CLAUDE.md` tem as regras de ouro (o que NÃO fazer, permissões, ordem de mudança). Leia antes.
- **SDK** (`sdk/`): tem repo upstream público próprio. Mudanças aqui precisam de `git subtree push --prefix=sdk sdk main` para chegar no npm.

### Commits e branches

- Conventional Commits em **pt-BR**: `feat(backend): ...`, `fix(ark): ...`, `docs: ...`
- Nunca `--no-verify`, `push --force` em `main`, ou `reset --hard` sem autorização.

### Testes

| Projeto | Comando |
|---|---|
| backend | `SECRET_KEY=test pytest` (441 passing) |
| landing | `npm test` (245 passing) |
| sdk | `npm test` (89 unit tests) |
| infra | `ark/teste-ambiente-a/` (Docker Rocky 9) + `ark/teste-ambiente-b/` (Vagrant) |

---

## Stack resumida

**Backend** — Python 3.12, Flask 3.1, Socket.IO/Eventlet, InfluxDB 2.7 (bucket-per-tenant), PostgreSQL 16 (prod) / SQLite (dev), JWT RS256, Flask-Limiter, Prometheus, APScheduler, Boto3 (R2), Stripe, Resend.

**SDK** — TypeScript/ESM, Socket.IO-client, Vitest, esbuild. Publica em GitHub Packages como `@danpqdan/dsplayground-analytics-sdk`.

**Landing** — Astro 6, Tailwind 4, TypeScript, Vitest, Cloudflare Pages. Portal do cliente em `/cliente/*`.

**Infra** — Rocky Linux 9 (HostGator VPS), Nginx, Ansible, Docker Compose, CrowdSec, Prometheus + Grafana, Cloudflare (Full strict + CF Origin Cert).

---

## Armadilhas conhecidas

- `portifolio/CLAUDE.md` menciona `landing/` como **espelho manual** de `danpqdan/comercial`. No monorepo atual, `landing/` IS o canonical (subtree de `DSPlayAnalytics/landing`). A referência ao `comercial` é histórica — ignorar.
- `portifolio/README.md` referencia `frontend/` que não existe mais (foi separado em `sdk/` e `landing/`). Ignorar.
- InfluxDB substitui variável bash `${VAR:-default}` no provisioning do Grafana — usa só `$VAR` ou `${VAR}`.
- Socket.IO exige `async_mode='eventlet'` e `--worker-class eventlet -w 1` no Gunicorn. Sem isso handshake retorna `upgrades:[]`.
- Rotação de `postgres_password` exige rotacionar também o role no cluster (task Ansible `Rotacionar senha...` cuida disso desde 2026-05-01).
- `portifolio_backend_keys` (volume Docker com chaves RSA) nunca apagar — invalida todos os JWTs emitidos.
