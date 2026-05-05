#!/usr/bin/env bash
# agent-smoke.sh — monitor defensivo dos servicos de producao
#
# Roda 17 checks read-only contra a stack rodando em /opt/portifolio.
# Sai com:
#   0 = tudo OK (silencioso)
#   1 = alguma falha (imprime relatorio markdown em stdout/stderr)
#
# Uso:
#   /opt/portifolio/ark/scripts/agent-smoke.sh
#
# Para rodar a cada 30 min: usar /opt/portifolio/ark/systemd/agent-smoke.timer.
#
# REGRAS:
#   - READ-ONLY. Nao executa Edit/Write/git/docker compose.
#   - Sem trafego destrutivo (POST/DELETE em qualquer endpoint).
#   - Throttle: rate-limit interno via timeout curto + sequencial.
#   - Apos 3 falhas consecutivas no MESMO teste, gera arquivo de incidente
#     em /tmp/agent-smoke-INCIDENT-<ts>.log.
#   - Nao logar valores de SECRET_KEY/INFLUXDB_TOKEN/ADMIN_API_TOKEN/
#     POSTGRES_PASSWORD/STRIPE_*/RESEND_API_KEY/NODE_AUTH_TOKEN nem cookies.

set -uo pipefail

readonly ESTADO_DIR="/var/lib/agent-smoke"
readonly STREAK_FILE="${ESTADO_DIR}/falhas-consecutivas.tsv"
readonly LAST_ERR_FILE="${ESTADO_DIR}/last-errors.txt"
mkdir -p "$ESTADO_DIR" 2>/dev/null || true

declare -a FALHAS=()
declare -a SEVERIDADES=()
declare -a OUTPUTS=()

registrar_falha() {
    local id="$1" nome="$2" severidade="$3" output="$4"
    FALHAS+=("$id|$nome")
    SEVERIDADES+=("$severidade")
    OUTPUTS+=("$output")
}

# Sanitiza output antes de printar (regex contra padroes comuns de credencial).
sanitizar() {
    sed -E \
        -e 's#(postgres(ql)?://[^:]+:)[^@]+(@)#\1***\3#g' \
        -e 's#(Bearer )[A-Za-z0-9._-]+#\1***#g' \
        -e 's#(token=)[A-Za-z0-9._-]+#\1***#g' \
        -e 's#([A-Z_]*(SECRET|TOKEN|PASSWORD|KEY)[A-Z_]*=)[^[:space:]"]+#\1***#g'
}

http_code() {
    curl -s -o /dev/null -w '%{http_code}' -m "$1" "$2" 2>/dev/null || echo "000"
}

# 1. Containers de pe ----------------------------------------------------
saida=$(docker ps --format '{{.Names}} {{.Status}}' 2>&1)
qtd=$(echo "$saida" | grep -c '^portifolio-')
nao_ok=$(echo "$saida" | grep -E 'Restarting|Exited|unhealthy' || true)
if (( qtd < 8 )) || [[ -n "$nao_ok" ]]; then
    registrar_falha 1 "containers-pe" CRITICAL "qtd=$qtd nao_ok=${nao_ok:-none}"
fi

# 2. Health backend ------------------------------------------------------
inicio=$(date +%s%N)
resp=$(curl -sf -m 5 http://127.0.0.1:5000/health 2>&1)
rc=$?
fim=$(date +%s%N)
ms=$(( (fim - inicio) / 1000000 ))
if (( rc != 0 )) || ! grep -q '"status":"healthy"' <<<"$resp" || ! grep -q '"influxdb":"connected"' <<<"$resp"; then
    registrar_falha 2 "health-backend" CRITICAL "rc=$rc latencia=${ms}ms resp=${resp:0:200}"
fi

# 3. Metrics backend -----------------------------------------------------
linhas=$(curl -sf -m 5 http://127.0.0.1:5000/metrics 2>/dev/null | grep -c portifolio_eventos_recebidos_total || echo 0)
if (( linhas < 1 )); then
    registrar_falha 3 "metrics-eventos" HIGH "linhas=$linhas"
fi

# 4. Frontend loopback ---------------------------------------------------
code=$(http_code 5 http://127.0.0.1:3000/)
[[ "$code" != "200" && "$code" != "304" ]] && \
    registrar_falha 4 "frontend-loopback" HIGH "http=$code"

# 5. Landing loopback ----------------------------------------------------
code=$(http_code 5 http://127.0.0.1:3002/)
[[ "$code" != "200" && "$code" != "304" ]] && \
    registrar_falha 5 "landing-loopback" HIGH "http=$code"

# 6. Edge portfolio ------------------------------------------------------
sleep 1
saida=$(curl -sI -m 10 https://portifolio.dsplayground.com.br/ \
        -H 'User-Agent: dsplayground-smoke/1.0' 2>&1)
code=$(echo "$saida" | head -1 | awk '{print $2}')
if [[ "$code" != "200" ]]; then
    registrar_falha 6 "portifolio-edge" HIGH "http=$code"
fi

# 7. API edge health -----------------------------------------------------
sleep 1
resp=$(curl -s -m 10 https://api.dsplayground.com.br/health 2>&1)
if ! grep -q '"status":"healthy"' <<<"$resp" || ! grep -q '"influxdb":"connected"' <<<"$resp"; then
    registrar_falha 7 "api-edge-health" CRITICAL "resp=${resp:0:200}"
fi

# 8. Auth gate sem cookie ------------------------------------------------
sleep 1
code=$(http_code 10 https://api.dsplayground.com.br/cliente/auth/gate)
if [[ "$code" != "401" ]]; then
    registrar_falha 8 "auth-gate-sem-cookie" HIGH "http=$code (esperado 401)"
fi

# 9. Endpoints sensiveis -------------------------------------------------
expostos=()
for path in /metrics /api/metrics /console /admin /admin/clientes; do
    sleep 1
    code=$(http_code 10 "https://api.dsplayground.com.br$path")
    if [[ "$code" == "200" ]]; then
        expostos+=("$path:200")
    fi
done
if (( ${#expostos[@]} > 0 )); then
    registrar_falha 9 "endpoint-sensivel-exposto" CRITICAL "${expostos[*]}"
fi

# 10. Embed widget -------------------------------------------------------
sleep 1
code_root=$(http_code 10 https://embed.dsplayground.com.br/)
sleep 1
saida_widget=$(curl -sI -m 10 https://embed.dsplayground.com.br/widget/teste/teste 2>&1)
code_widget=$(echo "$saida_widget" | head -1 | awk '{print $2}')
csp=$(echo "$saida_widget" | grep -i 'content-security-policy' | grep -ic 'frame-ancestors')
problemas_embed=()
[[ "$code_root" != "404" ]] && problemas_embed+=("root=$code_root(esperado 404)")
[[ "$code_widget" != "200" ]] && problemas_embed+=("widget=$code_widget(esperado 200)")
(( csp == 0 )) && problemas_embed+=("CSP-frame-ancestors-ausente")
if (( ${#problemas_embed[@]} > 0 )); then
    registrar_falha 10 "embed-widget" HIGH "${problemas_embed[*]}"
fi

# 11. Grafana ------------------------------------------------------------
sleep 1
code=$(http_code 10 https://grafana.dsplayground.com.br/login)
# Grafana pode redirecionar 301 -> /login OK; aceitar 200 ou 30x.
if [[ ! "$code" =~ ^(200|301|302)$ ]]; then
    registrar_falha 11 "grafana-edge" HIGH "http=$code"
fi

# 12. Socket.IO handshake ------------------------------------------------
sleep 1
code=$(http_code 5 'https://api.dsplayground.com.br/socket.io/?EIO=4&transport=polling')
[[ "$code" != "200" ]] && \
    registrar_falha 12 "socketio-handshake" HIGH "http=$code"

# 13. TLS validade -------------------------------------------------------
notafter=$(echo | timeout 8 openssl s_client -servername api.dsplayground.com.br \
            -connect api.dsplayground.com.br:443 2>/dev/null | \
            openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2)
if [[ -z "$notafter" ]]; then
    registrar_falha 13 "tls-cert" CRITICAL "nao foi possivel ler cert"
else
    expira_em=$(date -d "$notafter" +%s 2>/dev/null || echo 0)
    agora=$(date +%s)
    dias=$(( (expira_em - agora) / 86400 ))
    if (( dias < 30 )); then
        registrar_falha 13 "tls-cert" CRITICAL "expira em ${dias}d ($notafter)"
    fi
fi

# 14. Espaco em disco ----------------------------------------------------
uso=$(df -P /var/lib/docker /opt/portifolio 2>/dev/null | awk 'NR>1 {gsub("%","",$5); print $6"="$5}')
problema_disco=""
while read -r linha; do
    [[ -z "$linha" ]] && continue
    pct=$(echo "$linha" | cut -d= -f2)
    if (( pct >= 85 )); then
        problema_disco+="$linha "
    fi
done <<<"$uso"
if [[ -n "$problema_disco" ]]; then
    sev=CRITICAL
    pct_max=$(echo "$problema_disco" | tr ' ' '\n' | cut -d= -f2 | sort -n | tail -1)
    (( pct_max < 90 )) && sev=HIGH
    registrar_falha 14 "disco-cheio" "$sev" "$problema_disco"
fi

# 15. Logs de erro recentes ---------------------------------------------
mkdir -p "$(dirname "$LAST_ERR_FILE")"
errs_atuais=$(docker logs --since 30m --tail 50 portifolio-backend 2>&1 | \
              grep -iE 'error|exception|traceback' | head -20)
if [[ -n "$errs_atuais" ]]; then
    if [[ -f "$LAST_ERR_FILE" ]]; then
        novos=$(comm -23 <(echo "$errs_atuais" | sort -u) \
                        <(sort -u "$LAST_ERR_FILE" 2>/dev/null) | head -10)
        if [[ -n "$novos" ]]; then
            registrar_falha 15 "logs-erro-novos" HIGH "$(echo "$novos" | sanitizar | head -10)"
        fi
    fi
    echo "$errs_atuais" > "$LAST_ERR_FILE"
fi

# 16. CrowdSec decisoes (informacional) ---------------------------------
decisoes=$(docker exec portifolio-crowdsec cscli decisions list -o json 2>/dev/null | \
           python3 -c 'import sys,json
try: d=json.load(sys.stdin) or []
except: d=[]
print(len(d))' 2>/dev/null || echo "?")
# So reporta se inesperadamente alto (>50 = onda de ataque)
if [[ "$decisoes" =~ ^[0-9]+$ ]] && (( decisoes > 50 )); then
    registrar_falha 16 "crowdsec-decisoes-altas" INFO "decisions=$decisoes"
fi

# 17. Postgres + Influx --------------------------------------------------
pg=$(docker exec portifolio-postgres pg_isready -U portifolio 2>&1)
if ! grep -q 'accepting connections' <<<"$pg"; then
    registrar_falha 17 "postgres-ping" CRITICAL "$pg"
fi
inf=$(docker exec portifolio-influxdb influx ping 2>&1)
if [[ "$inf" != "OK" ]]; then
    registrar_falha 17 "influx-ping" CRITICAL "$inf"
fi

# Atualiza streak counter -----------------------------------------------
ts=$(date +%s)
> "${STREAK_FILE}.tmp"
declare -A vistos
for i in "${!FALHAS[@]}"; do
    id_nome="${FALHAS[$i]}"
    vistos["$id_nome"]=1
done

# Carrega streaks anteriores e incrementa/zera
declare -A streaks
if [[ -f "$STREAK_FILE" ]]; then
    while IFS=$'\t' read -r k v; do
        streaks["$k"]="$v"
    done < "$STREAK_FILE"
fi

incidentes=()
for id_nome in "${!vistos[@]}"; do
    prev="${streaks[$id_nome]:-0}"
    novo=$(( prev + 1 ))
    echo -e "${id_nome}\t${novo}" >> "${STREAK_FILE}.tmp"
    if (( novo >= 3 )); then
        incidentes+=("$id_nome (streak=$novo)")
    fi
done
mv "${STREAK_FILE}.tmp" "$STREAK_FILE"

if (( ${#incidentes[@]} > 0 )); then
    inc_file="/tmp/agent-smoke-INCIDENT-${ts}.log"
    {
        echo "Incidente agent-smoke @ $(date -Iseconds)"
        echo "Falhas com streak >=3:"
        printf '  - %s\n' "${incidentes[@]}"
        echo
        echo "Snapshot do relatorio atual:"
        for i in "${!FALHAS[@]}"; do
            printf '  [%s] %s -- %s\n' \
                "${SEVERIDADES[$i]}" "${FALHAS[$i]}" "${OUTPUTS[$i]}"
        done
    } > "$inc_file"
    chmod 0640 "$inc_file" 2>/dev/null || true
fi

# Saida -----------------------------------------------------------------
if (( ${#FALHAS[@]} == 0 )); then
    echo "OK"
    exit 0
fi

echo "FAIL: ${#FALHAS[@]} teste(s) falharam"
for i in "${!FALHAS[@]}"; do
    id_nome="${FALHAS[$i]}"
    sev="${SEVERIDADES[$i]}"
    out=$(echo "${OUTPUTS[$i]}" | sanitizar | head -10)
    printf -- '- [%s] #%s: %s\n  %s\n' "$sev" \
        "${id_nome%%|*}" "${id_nome##*|}" "$out"
done

if (( ${#incidentes[@]} > 0 )); then
    echo
    echo "INCIDENTES (streak >=3): /tmp/agent-smoke-INCIDENT-${ts}.log"
fi

# Acao sugerida (heuristica simples)
echo
sev_max=INFO
for s in "${SEVERIDADES[@]}"; do
    [[ "$s" == "CRITICAL" ]] && sev_max=CRITICAL && break
    [[ "$s" == "HIGH" ]] && sev_max=HIGH
done
case "$sev_max" in
    CRITICAL)
        echo "Acao sugerida: 'docker compose ps' + 'docker logs --tail 200 portifolio-backend' e checar nginx -t."
        ;;
    HIGH)
        echo "Acao sugerida: revisar o teste especifico antes do proximo ciclo (30min) virar incidente."
        ;;
    *)
        echo "Acao sugerida: monitorar; degradacao parcial."
        ;;
esac

exit 1
