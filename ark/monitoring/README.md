# Monitoring — Prometheus + Grafana

Stack opt-in de observabilidade. Sobe separada do `docker-compose.yml` do app, com rede propria. O backend expoe metricas em `/metrics` (follow-up do plano backend — quando estiver pronto, aparece automaticamente no Prometheus).

## Componentes

- **Prometheus** — coleta metricas a cada 15s do backend e do node-exporter; avalia regras em `prometheus/rules/*.yml` e dispara alertas pro Alertmanager.
- **Alertmanager** — recebe alertas firing do Prometheus, agrupa, deduplica, encaminha pra Slack `#alerts-prod` via Incoming Webhook (P4 audit).
- **Grafana** — provisionamento automatico de datasource Prometheus + InfluxDB.
- **node-exporter** — metricas de host (CPU, memoria, disco).

## Subir local

```bash
make monitoring-up

# interfaces:
# http://localhost:9090   Prometheus
# http://localhost:3001   Grafana (admin / admin na primeira vez — trocar)
```

## Provisionamento

`grafana/provisioning/datasources/` e `grafana/provisioning/dashboards/` sao montados read-only. Alterar datasources ou dashboard base exige edicao nos arquivos e `make monitoring-down && make monitoring-up`.

### Datasource InfluxDB

Definido em `grafana/provisioning/datasources/datasources.yml`. Usa **substituicao de env vars** do Grafana (so suporta `$VAR` ou `${VAR}`, **nao** `${VAR:-default}` da bash). Variaveis sao passadas pelo `docker-compose.monitoring.yml`:

```yaml
environment:
  INFLUXDB_TOKEN: ${INFLUXDB_TOKEN:-dev-local-influxdb-token}
  INFLUXDB_ORG:   ${INFLUXDB_ORG:-zen}
  INFLUXDB_BUCKET: ${INFLUXDB_BUCKET:-portifolio_prod}
```

E precisam tambem estar no `ark/monitoring/.env` (gitignored). Token deve **bater com o que o container InfluxDB foi inicializado** — volume `portifolio_influxdb_data` guarda o token na primeira subida; mudar `.env` depois nao re-inicializa o banco.

### Dashboards base — `dashboards/*.json`

Provisionados automaticamente em toda org de tenant via `redo_dashboards.py`:
`page-views`, `engajamento`, `web-vitals`, `event-explorer`. Cada um foca em um
recorte (visitas, interacao, performance, eventos custom). Templates usam o
placeholder `__BUCKET__` que e substituido pelo bucket do tenant na importacao.

**Padrao Flux importante**: sempre `group(columns: ["<tag>"])` ANTES de
`aggregateWindow(fn: sum)`. Inverter resulta em uma serie por `session_id`
com valores 0 — visualmente confuso.

### Auth.proxy do Grafana

Pra suportar dashboard self-service do cliente em `/cliente/metricas` (ver `ark/docs/dashboard-cliente.md`), o Grafana e configurado com:

```yaml
GF_SERVER_ROOT_URL: https://dsplayground.com.br/cliente/metricas/
GF_SERVER_SERVE_FROM_SUB_PATH: "true"
GF_AUTH_PROXY_ENABLED: "true"
GF_AUTH_PROXY_HEADER_NAME: X-WEBAUTH-USER
GF_AUTH_PROXY_AUTO_SIGN_UP: "true"
GF_AUTH_PROXY_HEADERS: "Role:X-WEBAUTH-PAPEL"
GF_AUTH_PROXY_WHITELIST: "127.0.0.1, ::1, 172.16.0.0/12, 10.0.0.0/8"
GF_USERS_AUTO_ASSIGN_ORG_ROLE: Viewer
```

Quando o nginx propaga `X-WEBAUTH-USER=<site_id>`, o Grafana auto-cria um user com `username=<site_id>` e role Viewer. Sem o header (acesso direto via `grafana.dsplayground.com.br`), Grafana cai pro login form admin (porque `GF_AUTH_DISABLE_LOGIN_FORM=false`).

## Alertmanager → Slack

Pipeline de alerta: regra Prometheus dispara → Alertmanager agrupa →
posta no canal `#alerts-prod` via Slack Incoming Webhook.

Regras iniciais (ver `prometheus/rules/alerts.yml`):
- `InstanceDown` (severity=critical, for=2m) — qualquer container scrape.
- `HostHighDiskUsage` (>85% por 10min, warning).
- `HostHighMemoryUsage` (>90% por 5min, warning).
- `HostHighCpuLoad` (>90% por 15min, warning).
- `HostFilesystemReadOnly` (FS virou ro, critical).

### Setup do webhook (uma vez por workspace)

1. https://api.slack.com/apps → **Create New App** → From scratch
2. **Features → Incoming Webhooks** → toggle **Activate**
3. **Add New Webhook to Workspace** → escolhe `#alerts-prod`
4. Copia a URL (formato `https://hooks.slack.com/services/T.../B.../...`)
5. Cola no vault Ansible: `ansible-vault edit ark/ansible/group_vars/all.yml`
   → `slack_webhook_alerts: "https://hooks.slack.com/services/..."`
6. `make -f ark/Makefile ansible-apply` — role `monitoring` cria
   `ark/monitoring/alertmanager/slack_webhook.url` (gitignored, mode
   `0644` porque alertmanager roda como `nobody` UID 65534 e nao tem
   acesso ao group `analytics` do host).
7. Recreate do alertmanager pra recarregar config:
   `docker compose -f ark/monitoring/docker-compose.monitoring.yml up -d`

### Validacao

```bash
# config valida?
docker exec portifolio-alertmanager amtool check-config /etc/alertmanager/alertmanager.yml
docker exec portifolio-prometheus promtool check rules /etc/prometheus/rules/alerts.yml

# disparar alerta de teste manual:
curl -X POST http://127.0.0.1:9093/api/v2/alerts \
  -H 'Content-Type: application/json' \
  -d '[{"labels":{"alertname":"TesteSmoke","severity":"warning","instance":"manual"},
       "annotations":{"summary":"smoke test","description":"ignorar"}}]'

# em ate ~30s (group_wait), aparece em #alerts-prod
```

## Producao

- Role Ansible `monitoring` (em `ark/ansible/roles/monitoring/`) usa este mesmo compose — mesmo binario, mesma config.
- Senha do Grafana vem do `GF_SECURITY_ADMIN_PASSWORD` no `.env` real.
- Exponha Grafana atras de Nginx com autenticacao adicional (SSO ou basic auth) — em prod o nginx do host ja faz isso via `auth_request` no path `/cliente/metricas/`.
- Ajuste `retention` do Prometheus (`--storage.tsdb.retention.time=15d`) conforme necessidade — 15 dias e o default.
