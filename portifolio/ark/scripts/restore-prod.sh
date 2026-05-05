#!/usr/bin/env bash
# restore-prod.sh — restore operacional a partir de backup local ou R2.
#
# READ-ONLY-by-default: lista snapshots disponiveis e procedimento.
# Restore real exige --confirm-restore <data> + --target <componente>.
#
# Procedimento documentado em ark/docs/backup-restore.md.

set -euo pipefail

readonly BACKUP_ROOT="/var/lib/backup-prod"
readonly POSTGRES_DB="${POSTGRES_DB:-portifolio_auth}"
readonly POSTGRES_USER="${POSTGRES_USER:-portifolio}"

uso() {
    cat <<EOF
restore-prod.sh — restore das partes criticas

Uso (modo seguro, default):
  restore-prod.sh list                         # lista snapshots locais e R2

Uso (modo destrutivo, exige confirmacao explicita):
  restore-prod.sh restore <component> <date>   # YYYY-MM-DD ou nome dir local
    component:
      postgres            — psql -f <dump> em portifolio_auth (DROP+CREATE)
      backend-keys        — restaura volume backend_keys (chaves RSA JWT)
      grafana             — restaura volume monitoring_grafana-data
      influxdb-config     — restaura volume influxdb_config

Exemplos:
  restore-prod.sh list
  restore-prod.sh restore postgres 2026-05-02

VARIAVEIS:
  RESTORE_FROM=local|r2  (default: local)
  YES_I_KNOW_WHAT_IM_DOING=1   (obrigatorio para restore real)

REGRA: nunca restaura sem confirmacao explicita. Em caso de duvida,
sempre rode \`list\` primeiro e leia ark/docs/backup-restore.md.
EOF
}

cmd_list() {
    echo "=== snapshots locais em $BACKUP_ROOT ==="
    if [[ -d "$BACKUP_ROOT" ]]; then
        ls -lh "$BACKUP_ROOT" 2>/dev/null | tail -n +2 | head -20
    else
        echo "(diretorio nao existe — backup nunca rodou neste host)"
    fi
    echo
    echo "=== R2 (snapshots remotos, se R2_BUCKET_BACKUP definido) ==="
    if docker ps --format '{{.Names}}' | grep -q portifolio-archiver; then
        docker exec -e BACKUP_BUCKET="${R2_BUCKET_BACKUP:-dsplayground-backup-prod}" \
            portifolio-archiver python3 -c "
import os
import boto3
from botocore.config import Config
try:
    s3 = boto3.client(
        's3',
        endpoint_url=f\"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com\",
        aws_access_key_id=os.environ['R2_ACCESS_KEY_ID'],
        aws_secret_access_key=os.environ['R2_SECRET_ACCESS_KEY'],
        config=Config(signature_version='s3v4'),
    )
    bucket = os.environ['BACKUP_BUCKET']
    resp = s3.list_objects_v2(Bucket=bucket, Prefix='prod/', MaxKeys=50)
    for o in resp.get('Contents', []):
        print(f\"{o['LastModified']:%Y-%m-%d %H:%M}  {o['Size']:>10}  {o['Key']}\")
    if not resp.get('Contents'):
        print('(bucket vazio — primeiro backup ainda nao rodou ou bucket errado)')
except Exception as e:
    print(f'erro listando R2: {e}')
" 2>&1 | head -30
    else
        echo "(container archiver nao esta rodando — nao da pra checar R2)"
    fi
}

cmd_restore() {
    local componente="$1"
    local data="$2"

    if [[ "${YES_I_KNOW_WHAT_IM_DOING:-0}" != "1" ]]; then
        echo "ERRO: restore destrutivo exige YES_I_KNOW_WHAT_IM_DOING=1" >&2
        echo "Antes de prosseguir:" >&2
        echo "  1. Ler ark/docs/backup-restore.md" >&2
        echo "  2. Confirmar que o snapshot escolhido cobre o ponto desejado" >&2
        echo "  3. Avisar a equipe que vai derrubar/restaurar prod" >&2
        echo "  4. Rodar com YES_I_KNOW_WHAT_IM_DOING=1 $0 $@" >&2
        exit 2
    fi

    local SOURCE_DIR
    if [[ -d "${BACKUP_ROOT}/${data}" ]]; then
        SOURCE_DIR="${BACKUP_ROOT}/${data}"
    else
        # Procura por prefixo
        SOURCE_DIR=$(ls -d "${BACKUP_ROOT}/${data}"* 2>/dev/null | head -1 || true)
    fi

    if [[ -z "$SOURCE_DIR" ]] || [[ ! -d "$SOURCE_DIR" ]]; then
        echo "ERRO: snapshot $data nao encontrado em $BACKUP_ROOT" >&2
        echo "Use \`$0 list\` pra ver disponiveis ou baixe do R2 primeiro." >&2
        exit 3
    fi

    echo "==> Snapshot: $SOURCE_DIR"
    echo "==> Componente: $componente"
    echo "==> Data: $data"
    echo
    case "$componente" in
        postgres)
            DUMP=$(ls "$SOURCE_DIR"/postgres-*.sql.gz 2>/dev/null | head -1)
            [[ -z "$DUMP" ]] && { echo "ERRO: postgres dump nao achado em $SOURCE_DIR"; exit 4; }
            echo "==> Vai aplicar $DUMP em portifolio_auth"
            echo "==> Em 10s. Ctrl+C pra abortar."
            sleep 10
            gunzip -c "$DUMP" | docker exec -i portifolio-postgres \
                psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1
            echo "==> Restore postgres OK"
            ;;
        backend-keys|grafana|influxdb-config)
            local VOL
            case "$componente" in
                backend-keys) VOL=portifolio_backend_keys ;;
                grafana) VOL=monitoring_grafana-data ;;
                influxdb-config) VOL=portifolio_influxdb_config ;;
            esac
            TAR=$(ls "$SOURCE_DIR"/volume-${VOL}-*.tar.gz 2>/dev/null | head -1)
            [[ -z "$TAR" ]] && { echo "ERRO: tar de $VOL nao achado"; exit 4; }
            echo "==> Vai esvaziar volume $VOL e restaurar de $TAR"
            echo "==> Em 10s. Ctrl+C pra abortar."
            sleep 10
            docker run --rm -v "$VOL:/target" -v "$TAR:/in.tar.gz:ro" alpine:3.20 \
                sh -c 'find /target -mindepth 1 -delete && tar xzf /in.tar.gz -C /target'
            echo "==> Restore $VOL OK"
            echo "==> NAO ESQUECA: restart dos containers que usam $VOL"
            ;;
        *)
            echo "Componente invalido: $componente"; uso; exit 1 ;;
    esac
}

case "${1:-help}" in
    list) cmd_list ;;
    restore)
        [[ $# -lt 3 ]] && { uso; exit 1; }
        cmd_restore "$2" "$3"
        ;;
    help|--help|-h|"") uso ;;
    *) uso; exit 1 ;;
esac
