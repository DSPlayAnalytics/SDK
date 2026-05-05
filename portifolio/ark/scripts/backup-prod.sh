#!/usr/bin/env bash
# backup-prod.sh — backup operacional dos volumes/dbs criticos.
#
# Cobre: postgres_data (via pg_dump), backend_keys, influxdb_config,
# monitoring_grafana-data. NAO cobre: prometheus (regenera-se), influxdb_data
# (archiver tiering ja cuida da parte de cliente).
#
# Procedimento:
#   1. Cria /var/lib/backup-prod/{ts}/
#   2. pg_dump | gzip do postgres
#   3. tar czf de cada volume Docker (read-only via alpine)
#   4. Manifesto sha256
#   5. Upload pra R2 — APENAS se $R2_BUCKET_BACKUP estiver definido E nao
#      vazio. Sem default — operador escolhe o bucket explicitamente no
#      vault (`r2_bucket_backup`) apos criar no CF dashboard.
#   6. Retencao local: 7 dias.
#
# Variaveis (lidas do .env do backend ou exportadas pelo systemd):
#   POSTGRES_USER, POSTGRES_DB              (default: portifolio, portifolio_auth)
#   R2_BUCKET_BACKUP                        (sem upload se vazio/nao definido)
#   R2_ACCOUNT_ID, R2_ACCESS_KEY_ID,        (do .env, via container archiver)
#   R2_SECRET_ACCESS_KEY                    (idem)
#
# Ver ark/docs/backup-restore.md.

set -euo pipefail

readonly POSTGRES_DB="${POSTGRES_DB:-portifolio_auth}"
readonly POSTGRES_USER="${POSTGRES_USER:-portifolio}"
readonly BACKUP_ROOT="/var/lib/backup-prod"
readonly LOG_FILE="/var/log/backup-prod.log"
readonly RETENCAO_DIAS_LOCAL=7
readonly -a VOLUMES=(
    "portifolio_backend_keys"
    "portifolio_influxdb_config"
    "monitoring_grafana-data"
)

readonly TS=$(date -u +%Y-%m-%dT%H-%M-%SZ)
readonly DIA=$(date -u +%Y-%m-%d)
readonly OUT_DIR="${BACKUP_ROOT}/${TS}"

# Logging com sanitizacao basica.
log() {
    local msg="$*"
    msg=$(echo "$msg" | sed -E \
        -e 's#(postgres(ql)?://[^:]+:)[^@]+(@)#\1***\3#g' \
        -e 's#([A-Z_]*(SECRET|TOKEN|PASSWORD|KEY)[A-Z_]*=)[^[:space:]"]+#\1***#g')
    printf '%s %s\n' "$(date -Iseconds)" "$msg" | tee -a "$LOG_FILE" >&2
}

mkdir -p "$BACKUP_ROOT" "$OUT_DIR"
chmod 0700 "$BACKUP_ROOT" "$OUT_DIR"

log "evento=backup_start ts=$TS"

# ----- 1. pg_dump -----------------------------------------------------------
log "evento=backup_postgres_start db=$POSTGRES_DB"
PGDUMP_FILE="${OUT_DIR}/postgres-${POSTGRES_DB}-${TS}.sql.gz"
if docker exec portifolio-postgres pg_dump \
        -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
        --no-owner --no-acl --clean --if-exists \
    | gzip -9 > "$PGDUMP_FILE"; then
    SIZE=$(stat -c %s "$PGDUMP_FILE")
    log "evento=backup_postgres_ok bytes=$SIZE arquivo=$(basename "$PGDUMP_FILE")"
else
    log "evento=backup_postgres_falhou"
    rm -f "$PGDUMP_FILE"
    exit 2
fi

# ----- 2. tar de volumes ----------------------------------------------------
for vol in "${VOLUMES[@]}"; do
    log "evento=backup_volume_start vol=$vol"
    OUT_TAR="${OUT_DIR}/volume-${vol}-${TS}.tar.gz"
    if docker run --rm \
        -v "${vol}:/source:ro" \
        alpine:3.20 tar czf - -C /source . > "$OUT_TAR" 2>>"$LOG_FILE"; then
        SIZE=$(stat -c %s "$OUT_TAR")
        log "evento=backup_volume_ok vol=$vol bytes=$SIZE arquivo=$(basename "$OUT_TAR")"
    else
        log "evento=backup_volume_falhou vol=$vol"
        rm -f "$OUT_TAR"
        continue
    fi
done

# ----- 3. Manifesto + checksum ---------------------------------------------
log "evento=backup_manifesto"
(cd "$OUT_DIR" && sha256sum *.sql.gz *.tar.gz 2>/dev/null > "manifest-${TS}.sha256")
log "evento=backup_manifesto_ok"

# ----- 4. Upload pra R2 (OPT-IN — exige R2_BUCKET_BACKUP) -------------------
# Se R2_BUCKET_BACKUP nao foi definido (vazio ou nao-existente), backup fica
# apenas local. Operador deve criar bucket no CF dashboard E adicionar a
# var ao vault (`r2_bucket_backup: <nome>`) pra ativar upload.
R2_BUCKET_BACKUP="${R2_BUCKET_BACKUP:-}"
if [[ -z "$R2_BUCKET_BACKUP" ]]; then
    log "evento=backup_upload_skip motivo=R2_BUCKET_BACKUP_nao_definido"
    log "evento=backup_done arquivos=$(find "$OUT_DIR" -type f | wc -l) tamanho=$(du -sh "$OUT_DIR" | cut -f1) modo=local-only"
    # Retencao local
    find "$BACKUP_ROOT" -mindepth 1 -maxdepth 1 -type d \
        -mtime "+$RETENCAO_DIAS_LOCAL" -exec rm -rf {} \; 2>>"$LOG_FILE" || true
    exit 0
fi

log "evento=backup_upload_start bucket=$R2_BUCKET_BACKUP"
UPLOAD_OK=0
UPLOAD_TOTAL=0
for f in "$OUT_DIR"/*; do
    [ -f "$f" ] || continue
    UPLOAD_TOTAL=$((UPLOAD_TOTAL + 1))
    BASE=$(basename "$f")
    KEY="prod/${DIA}/${BASE}"

    if docker cp "$f" "portifolio-archiver:/tmp/${BASE}" 2>/dev/null && \
       docker exec -e BACKUP_KEY="$KEY" -e BACKUP_BUCKET="$R2_BUCKET_BACKUP" \
            portifolio-archiver python3 -c "
import os, sys, boto3
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
    key = os.environ['BACKUP_KEY']
    base = os.path.basename(key)
    with open(f'/tmp/{base}', 'rb') as fh:
        data = fh.read()
    s3.put_object(Bucket=bucket, Key=key, Body=data)
    print(f'OK {key} {len(data)}b')
except Exception as e:
    print(f'FAIL {key}: {e}', file=sys.stderr)
    sys.exit(1)
" 2>>"$LOG_FILE"; then
        UPLOAD_OK=$((UPLOAD_OK + 1))
        log "evento=backup_upload_ok arquivo=$BASE key=$KEY"
        docker exec portifolio-archiver rm -f "/tmp/${BASE}" 2>/dev/null || true
    else
        log "evento=backup_upload_falhou arquivo=$BASE"
    fi
done

log "evento=backup_upload_resumo ok=$UPLOAD_OK total=$UPLOAD_TOTAL"

# ----- 5. Retencao local ----------------------------------------------------
log "evento=backup_cleanup_local retencao_dias=$RETENCAO_DIAS_LOCAL"
find "$BACKUP_ROOT" -mindepth 1 -maxdepth 1 -type d \
    -mtime "+$RETENCAO_DIAS_LOCAL" -exec rm -rf {} \; 2>>"$LOG_FILE" || true

# ----- 6. Resumo final ------------------------------------------------------
TOTAL_FILES=$(find "$OUT_DIR" -type f | wc -l)
TOTAL_SIZE=$(du -sh "$OUT_DIR" | cut -f1)
log "evento=backup_done arquivos=$TOTAL_FILES tamanho=$TOTAL_SIZE upload_ok=$UPLOAD_OK/$UPLOAD_TOTAL"

if (( UPLOAD_OK < UPLOAD_TOTAL )); then
    log "evento=backup_warn nem_tudo_subiu_pro_r2"
    exit 1
fi

exit 0
