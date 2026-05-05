# Backup + Disaster Recovery — runbook

Cobre o que **e** backup nesta VPS (postgres, chaves JWT, grafana, influx
config), como funciona, como restaurar, e como testar drill. Endereca o
gap P0 da auditoria de seguranca 2026-05-02.

## Sumario

- [O que esta protegido (e o que nao esta)](#o-que-esta-protegido-e-o-que-nao-esta)
- [Como instalar](#como-instalar)
- [Como rodar manual](#como-rodar-manual)
- [Como restaurar](#como-restaurar)
- [Drill de restore](#drill-de-restore)
- [Custos e dimensionamento](#custos-e-dimensionamento)

## O que esta protegido (e o que nao esta)

`backup-prod.sh` cobre os volumes Docker **insubstituiveis**:

| Volume / DB | Como | Por que e critico |
|---|---|---|
| `postgres_data` | `pg_dump --clean --if-exists` | Auth multi-tenant: clientes, sites, publishable_keys, sessoes, magic-links, billing/Stripe, idempotencia, embed JWT revogados. **Perda = clientes voltam do zero.** |
| `backend_keys` | `tar czf` (12KB) | Chaves RSA do JWT. **Perda = todos SDK tokens e embed JWTs ja emitidos viram invalidos.** Re-emissao requer cliente reinstalar widget. |
| `monitoring_grafana-data` | `tar czf` (1.4MB) | Dashboards configurados, datasources, users. Recriacao manual leva horas. |
| `influxdb_config` | `tar czf` (8KB) | Token admin + bucket config. Sem isso, restore do influx exige re-setup. |

Volumes **NAO** cobertos (decisao explicita):

| Volume | Razao |
|---|---|
| `influxdb_data` | **Archiver** (`backend/archiver/`) ja faz tiering pra R2 com retencao por cliente. Backup ponto-a-ponto seria duplicacao + custo. **Trade-off**: nao ha point-in-time restore do estado do bucket — so reconstrucao via archiver. |
| `monitoring_prometheus-data` | Metricas sao derivadas (scrape de outros containers). Retencao 15d. Restore = perde 15d de hist mas tudo se recupera. |

## Como instalar

### 1. Criar bucket R2 dedicado (operador, uma vez)

**Operador escolhe o nome.** Nao ha default no script — se a var
`R2_BUCKET_BACKUP` nao for definida, o backup roda apenas LOCAL.

Sugestao de nome: `dsplayground-backup-prod`. Configuracao recomendada
no Cloudflare dashboard → R2:

```
Versionamento:  ON  (importante: protege contra apagamento acidental)
Lifecycle:      3 regras:
                  - prefix prod/  retain 30 days  →  Standard-IA
                  - prefix prod/  retain 90 days  →  delete current
                  - prefix prod/  retain 365 days →  delete versions
```

Versionamento + lifecycle e o que da retencao real. Sem versionamento,
qualquer `delete` acidental no bucket vira perda permanente.

### 2. Adicionar `r2_bucket_backup` ao vault (depois de criar o bucket)

```bash
cd /opt/portifolio/ark/ansible
ansible-vault edit group_vars/all.yml
# adicionar com o NOME EXATO que voce criou no CF dashboard:
#   r2_bucket_backup: <NOME_REAL_DO_BUCKET>
```

E no `templates/backend.env.j2`, adicionar (proximo de R2_BUCKET):
```
R2_BUCKET_BACKUP={{ r2_bucket_backup | default('') }}
```

`default('')` (vazio) e proposital — sem bucket, backup fica local.
Force o operador a configurar explicitamente apos criar o bucket.

E rodar `make -f ark/Makefile ansible-apply` pra propagar pro container.

### 3. Instalar systemd service + timer

```bash
sudo cp /opt/portifolio/ark/systemd/backup-prod.service /etc/systemd/system/

sudo tee /etc/systemd/system/backup-prod.timer > /dev/null <<'UNIT'
[Unit]
Description=Backup operacional diario dsplayground 03:30 UTC
Documentation=file:/opt/portifolio/ark/docs/backup-restore.md

[Timer]
# 03:30 UTC todo dia (apos archiver 03:00 UTC).
# OnCalendar e UTC-based por default em systemd.
OnCalendar=*-*-* 03:30:00 UTC
Persistent=true
RandomizedDelaySec=10min
Unit=backup-prod.service

[Install]
WantedBy=timers.target
UNIT

sudo systemctl daemon-reload
sudo systemctl enable --now backup-prod.timer
systemctl list-timers backup-prod.timer
```

## Como rodar manual

```bash
sudo /opt/portifolio/ark/scripts/backup-prod.sh
echo "exit=$?"
```

Output em `/var/log/backup-prod.log`. Snapshots locais em
`/var/lib/backup-prod/<timestamp>/`.

Exit codes:
- `0` — tudo OK (postgres dump + volumes + upload R2)
- `1` — backup local OK mas nem tudo subiu pra R2 (warning)
- `2` — pg_dump falhou (critico)

## Como restaurar

### Listar snapshots

```bash
/opt/portifolio/ark/scripts/restore-prod.sh list
```

Mostra snapshots locais (`/var/lib/backup-prod/`) e remotos (R2 prefix
`prod/`).

### Restaurar (destrutivo — exige confirmacao)

```bash
# Postgres (DROP + recreate em portifolio_auth)
YES_I_KNOW_WHAT_IM_DOING=1 \
  /opt/portifolio/ark/scripts/restore-prod.sh restore postgres 2026-05-02

# Backend keys (substitui volume; restart backend depois)
YES_I_KNOW_WHAT_IM_DOING=1 \
  /opt/portifolio/ark/scripts/restore-prod.sh restore backend-keys 2026-05-02
docker compose up -d --force-recreate --no-deps backend archiver

# Grafana
YES_I_KNOW_WHAT_IM_DOING=1 \
  /opt/portifolio/ark/scripts/restore-prod.sh restore grafana 2026-05-02
docker compose -f ark/monitoring/docker-compose.monitoring.yml \
  up -d --force-recreate --no-deps grafana
```

**Antes de restaurar postgres em prod**:
1. Avise a equipe (downtime ~1-2min do backend)
2. Considere parar o backend primeiro: `docker compose stop backend`
3. Faca um snapshot atual antes: `sudo /opt/portifolio/ark/scripts/backup-prod.sh`
4. Restaurar
5. Restart backend
6. Validar `curl http://127.0.0.1:5000/health`

### Baixar snapshot do R2 (se nao ha local)

```bash
# Listar
/opt/portifolio/ark/scripts/restore-prod.sh list

# Baixar via boto3 dentro do archiver:
DIA=2026-05-02
ARQUIVO=postgres-portifolio_auth-2026-05-02T03-30-00Z.sql.gz

docker exec -e BACKUP_BUCKET=dsplayground-backup-prod \
    -e BACKUP_KEY="prod/${DIA}/${ARQUIVO}" \
    portifolio-archiver python3 -c "
import os, boto3
from botocore.config import Config
s3 = boto3.client(
    's3',
    endpoint_url=f\"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com\",
    aws_access_key_id=os.environ['R2_ACCESS_KEY_ID'],
    aws_secret_access_key=os.environ['R2_SECRET_ACCESS_KEY'],
    config=Config(signature_version='s3v4'),
)
s3.download_file(os.environ['BACKUP_BUCKET'], os.environ['BACKUP_KEY'], f'/tmp/{os.path.basename(os.environ[\"BACKUP_KEY\"])}')
print('OK')
"

# Copia pra host:
mkdir -p /var/lib/backup-prod/${DIA}-r2
docker cp portifolio-archiver:/tmp/${ARQUIVO} /var/lib/backup-prod/${DIA}-r2/
```

## Drill de restore

Trimestralmente, rodar este procedimento num **ambiente staging** (ou
container effemero):

1. Subir VPS-test (ou stack docker compose nova num diretorio limpo)
2. Baixar snapshot mais recente do R2
3. Restaurar todos os componentes via `restore-prod.sh`
4. Validar:
   - `psql -d portifolio_auth -c "SELECT count(*) FROM sites"` — bate com prod?
   - Backend sobe? `/health` retorna `influxdb:connected`?
   - Grafana abre? Dashboards aparecem?
   - SDK token continua sendo emitido com chaves RSA restauradas?
5. Documentar tempo total (RTO) e ultimo snapshot disponivel (RPO).

**Cadencia**: trimestral (Q1, Q2, Q3, Q4). Anotar resultado em
`ark/docs/seguranca-auditoria-2026-05-02.md` na tabela de manutencao.

## Custos e dimensionamento

Todo backup junto: ~250MB/dia. Com retencao 90d = ~22GB no R2.

R2 pricing (2026): $0.015/GB/mes Standard, $0.01/GB/mes Standard-IA.
- 7 dias Standard:  1.7GB × 0.015 = $0.025/mes
- 83 dias Std-IA:  20.3GB × 0.01  = $0.203/mes
- **Total: ~$0.23/mes** (vs custo de perder tudo: incalculavel)

Egress de R2 e gratuito quando voce le da mesma rede CF — restore via
container archiver nao paga egress.

Rate de upload: ~250MB de uma vez todo dia, 03:30 UTC. Banda VPS
HostGator: 100Mbps. Tempo upload: ~25s. Negligivel.

## Troubleshooting

### "backup-prod.timer nao roda"

```bash
systemctl list-timers backup-prod.timer
journalctl -u backup-prod.service --since '1 day ago' --no-pager
```

Se OnCalendar nao agendado, conferir clock UTC: `timedatectl`. O timer
e UTC, mas systemd lista em local time.

### "evento=backup_upload_falhou"

Causa comum: bucket nao existe ou credenciais R2 erradas. Verifique:
```bash
docker exec portifolio-archiver env | grep ^R2_
```

E que o bucket `dsplayground-backup-prod` existe no CF dashboard.

### "pg_dump: connection failed"

Postgres nao esta rodando ou senha errada. Verifique:
```bash
docker compose ps postgres
docker exec portifolio-postgres pg_isready -U portifolio
```

### "Espaco em disco insuficiente"

`/var/lib/backup-prod` precisa de ~250MB livre por snapshot × 7 dias =
~1.8GB. Em VPS HostGator com 50GB total e 67% usado, sobram 16GB —
dobrar de tamanho leva semanas. Monitorar via `agent-smoke.sh` (item 14).

## Revisao recorrente

- **Cada apply do Ansible**: confirmar que `R2_BUCKET_BACKUP` aparece no
  `backend/.env` e no container.
- **Mensal**: rodar `restore-prod.sh list` e confirmar que `prod/<ontem>/`
  tem 4 arquivos (postgres + 3 volumes) + manifest.
- **Trimestral**: rodar drill completo conforme [Drill de restore](#drill-de-restore).
- **Anual**: revisar lifecycle do bucket R2; ajustar retencao se LGPD
  ou compliance mudarem.
