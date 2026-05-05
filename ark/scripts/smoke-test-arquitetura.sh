#!/usr/bin/env bash
# Smoke test da arquitetura de produção pós-cutover app.X (2026-04-30).
#
# Valida o fluxo end-to-end:
#   1. apex (CF Pages) responde 200
#   2. portifolio.X (Vite) responde 200
#   3. api.X /health/app reporta ambiente=production
#   4. app.X responde 200 e redireciona auth-required pra apex/cliente/login
#   5. CORS de api.X aceita app.X como origin
#   6. POST /cliente/auth/cadastro retorna 201 + Set-Cookie com Domain=dsplayground.com.br
#   7. Cookie reusado em api.X /cliente/auth/me retorna 200
#   8. Cookie reusado em app.X /cliente/metricas/ retorna 200 (Grafana)
#
# Clean-room: cria conta de teste descartável e DELETA via Postgres no fim
# (sucesso OU falha). Cascade FKs em sites cuidam de clientes_users,
# site_dominios, publishable_keys, quotas, consumo_diario.
# O bucket Influx fica até expirar retenção (7d free) — bucket vazio.
#
# Vars opcionais:
#   SKIP_CLEANUP=1   pula deleção (debugging — conta persiste no Postgres)
#   APEX, APP, API, PORTFOLIO  override hosts (default: prod)
#   SSH_KEY=~/.ssh/vpn  chave pra SSH na VPS (default: ~/.ssh/vpn)
#   SSH_HOST=129.121.55.29  IP HostGator
#   SSH_USER=deploy SSH_PORT=22022
#
# Uso:
#   bash ark/scripts/smoke-test-arquitetura.sh
#
# Saída: 0 se todos passaram, 1 se algum falhou.

set -uo pipefail

APEX="${APEX:-https://dsplayground.com.br}"
APP="${APP:-https://app.dsplayground.com.br}"
API="${API:-https://api.dsplayground.com.br}"
PORTFOLIO="${PORTFOLIO:-https://portifolio.dsplayground.com.br}"

# Cores ANSI (skip se não-TTY)
if [ -t 1 ]; then
  GREEN="\033[1;32m"; RED="\033[1;31m"; YELLOW="\033[1;33m"; CYAN="\033[1;36m"; RESET="\033[0m"
else
  GREEN=""; RED=""; YELLOW=""; CYAN=""; RESET=""
fi

SSH_KEY="${SSH_KEY:-$HOME/.ssh/vpn}"
SSH_HOST="${SSH_HOST:-129.121.55.29}"
SSH_USER="${SSH_USER:-deploy}"
SSH_PORT="${SSH_PORT:-22022}"
SKIP_CLEANUP="${SKIP_CLEANUP:-0}"

PASS=0
FAIL=0
COOKIE_JAR=$(mktemp)
TEST_SLUG=""

cleanup() {
  rm -f "$COOKIE_JAR"
  if [ -z "$TEST_SLUG" ] || [ "$SKIP_CLEANUP" = "1" ]; then
    return
  fi
  echo
  echo -e "${CYAN}== cleanup conta de teste (slug=$TEST_SLUG) ==${RESET}"
  if ! ssh -i "$SSH_KEY" -p "$SSH_PORT" -o IdentitiesOnly=yes -o StrictHostKeyChecking=no \
       -o ConnectTimeout=10 -o BatchMode=yes \
       "$SSH_USER@$SSH_HOST" 'echo connected' >/dev/null 2>&1; then
    echo -e "  ${YELLOW}⚠ SSH indisponível — cleanup skip. Para limpar:${RESET}"
    echo "    ssh deploy@<vps> docker exec portifolio-postgres psql -U portifolio -d portifolio_auth -c \"DELETE FROM sites WHERE slug='$TEST_SLUG';\""
    return
  fi
  # Postgres cascateia DELETE em sites pra clientes_users, site_dominios,
  # publishable_keys, quotas, consumo_diario, emissoes_jwt (FK CASCADE).
  out=$(ssh -i "$SSH_KEY" -p "$SSH_PORT" -o IdentitiesOnly=yes -o StrictHostKeyChecking=no \
        "$SSH_USER@$SSH_HOST" \
        "docker exec portifolio-postgres psql -U portifolio -d portifolio_auth -t -c \"DELETE FROM sites WHERE slug='$TEST_SLUG' RETURNING id, slug;\"" 2>&1)
  if echo "$out" | grep -q "$TEST_SLUG"; then
    echo -e "  ${GREEN}✓${RESET} site deletado: $(echo "$out" | tr -d '\r' | xargs)"
  else
    echo -e "  ${YELLOW}⚠ DELETE não retornou linha — pode já ter sido removido. Output:${RESET}"
    echo "    $out"
  fi
  echo -e "  ${CYAN}ℹ${RESET} bucket Influx \`cliente_$TEST_SLUG\` continua (expira em 7d)"
}
trap cleanup EXIT

ok()   { echo -e "  ${GREEN}✓${RESET} $1"; PASS=$((PASS+1)); }
fail() { echo -e "  ${RED}✗${RESET} $1"; FAIL=$((FAIL+1)); }
info() { echo -e "  ${CYAN}ℹ${RESET} $1"; }
section() { echo; echo -e "${YELLOW}== $1 ==${RESET}"; }

# ============== 1. Apex (CF Pages) ==============
section "1. Apex CF Pages"
code=$(curl -sk -o /dev/null -w "%{http_code}" "$APEX/")
if [ "$code" = "200" ]; then ok "apex GET / → 200"; else fail "apex GET / → $code"; fi

server=$(curl -sk -I "$APEX/" | grep -i '^server:' | head -1 | tr -d '\r')
if echo "$server" | grep -qi cloudflare; then ok "apex servido por Cloudflare ($server)"; else fail "apex Server header inesperado: $server"; fi

# Astro: deve haver path /_astro/ no body
if curl -sk "$APEX/" | grep -q '/_astro/'; then ok "apex contém asset /_astro/* (Astro build)"; else fail "apex sem /_astro/* — landing pode não estar no CF Pages"; fi

# ============== 2. portifolio.X (Vite) ==============
section "2. portifolio.X (Vite build)"
code=$(curl -sk -o /dev/null -w "%{http_code}" "$PORTFOLIO/")
if [ "$code" = "200" ]; then ok "portifolio.X GET / → 200"; else fail "portifolio.X GET / → $code"; fi

# Vite: deve haver /assets/ no body
if curl -sk "$PORTFOLIO/" | grep -qE '/assets/[a-zA-Z0-9._-]+\.(js|css)'; then
  ok "portifolio.X contém /assets/* (Vite build)"
else fail "portifolio.X sem /assets/* — bundle não servido"; fi

# ============== 3. api.X health ==============
section "3. api.X health"
body=$(curl -sk "$API/health/app")
code=$(curl -sk -o /dev/null -w "%{http_code}" "$API/health/app")
if [ "$code" = "200" ]; then ok "api.X /health/app → 200"; else fail "api.X /health/app → $code"; fi
if echo "$body" | grep -q '"ambiente":"production"'; then
  ok "ambiente=production confirmado"
else fail "ambiente NÃO é production: $body"; fi

# ============== 4. app.X redirect 401 ==============
section "4. app.X redirect sem cookie"
loc=$(curl -sk -I "$APP/cliente/metricas/" | grep -i '^location:' | tr -d '\r' | awk '{print $2}')
code=$(curl -sk -o /dev/null -w "%{http_code}" "$APP/cliente/metricas/")
if [ "$code" = "302" ]; then ok "app.X /cliente/metricas/ sem cookie → 302"; else fail "esperado 302, veio $code"; fi
if echo "$loc" | grep -q "https://dsplayground.com.br/cliente/login"; then
  ok "302 Location aponta apex/cliente/login (correto)"
else fail "Location inesperado: $loc (deveria apontar apex)"; fi

# ============== 5. CORS api.X aceita app.X ==============
section "5. CORS api.X"
cors=$(curl -sk -X OPTIONS "$API/cliente/auth/login" \
  -H "Origin: https://app.dsplayground.com.br" \
  -H "Access-Control-Request-Method: POST" \
  -I 2>&1 | grep -i 'access-control-allow-origin' | tr -d '\r')
if echo "$cors" | grep -q 'app.dsplayground.com.br'; then
  ok "api.X CORS permite app.X"
else fail "api.X CORS NÃO permite app.X: $cors"; fi

# ============== 6. Cadastro + Set-Cookie Domain ==============
section "6. POST /cadastro + Set-Cookie Domain"
TS=$(date +%s)
SHORT_ID=$(openssl rand -hex 3 2>/dev/null || head -c 6 /dev/urandom | xxd -p | head -c 6)
TEST_EMAIL="smoke+$TS@dsplayground.com.br"
TEST_SLUG="smoke-$SHORT_ID"
TEST_SENHA="smoke-test-pass-$TS"

info "criando conta: email=$TEST_EMAIL slug=$TEST_SLUG"
resp=$(curl -sk -X POST "$API/cliente/auth/cadastro" \
  -H 'Content-Type: application/json' \
  -H "Origin: $APEX" \
  -c "$COOKIE_JAR" \
  -i \
  -d "{\"email\":\"$TEST_EMAIL\",\"senha\":\"$TEST_SENHA\",\"nome_site\":\"Smoke $TS\",\"slug\":\"$TEST_SLUG\"}" 2>&1)

http_code=$(echo "$resp" | grep -E '^HTTP/' | tail -1 | awk '{print $2}')
set_cookie=$(echo "$resp" | grep -i '^set-cookie:' | head -1 | tr -d '\r')

if [ "$http_code" = "201" ]; then ok "cadastro retornou 201"; else fail "cadastro retornou $http_code (esperado 201)"; fi
if echo "$set_cookie" | grep -q 'cliente_session='; then ok "Set-Cookie inclui cliente_session"; else fail "Set-Cookie sem cliente_session: $set_cookie"; fi
if echo "$set_cookie" | grep -q 'Domain=dsplayground.com.br'; then
  ok "Set-Cookie tem Domain=dsplayground.com.br"
else fail "Set-Cookie SEM Domain=dsplayground.com.br: $set_cookie"; fi
if echo "$set_cookie" | grep -qi 'Secure'; then ok "Set-Cookie tem Secure"; else fail "Set-Cookie sem Secure"; fi
if echo "$set_cookie" | grep -qi 'HttpOnly'; then ok "Set-Cookie tem HttpOnly"; else fail "Set-Cookie sem HttpOnly"; fi
if echo "$set_cookie" | grep -qi 'SameSite=Strict'; then ok "Set-Cookie tem SameSite=Strict"; else fail "Set-Cookie sem SameSite=Strict"; fi

# ============== 7. /cliente/auth/me com cookie ==============
section "7. api.X /me com cookie"
me=$(curl -sk -b "$COOKIE_JAR" "$API/cliente/auth/me")
me_code=$(curl -sk -b "$COOKIE_JAR" -o /dev/null -w "%{http_code}" "$API/cliente/auth/me")
if [ "$me_code" = "200" ]; then ok "/me retornou 200 com cookie"; else fail "/me retornou $me_code"; fi
if echo "$me" | grep -q "$TEST_EMAIL"; then ok "/me reporta email correto"; else fail "/me não reconhece email: $me"; fi
if echo "$me" | grep -q '"papel":"admin"'; then ok "/me confirma papel=admin"; else fail "/me sem papel=admin: $me"; fi

# ============== 8. app.X /cliente/metricas/ com cookie ==============
section "8. app.X /cliente/metricas/ com cookie"
mx_code=$(curl -sk -b "$COOKIE_JAR" -o /dev/null -w "%{http_code}" "$APP/cliente/metricas/")
mx_loc=$(curl -sk -b "$COOKIE_JAR" -I "$APP/cliente/metricas/" | grep -i '^location:' | tr -d '\r' | awk '{print $2}')
# Esperado: 200 (Grafana renderiza) OU 302 internal pra /cliente/metricas/login (Grafana próprio).
# Se for 302 pra apex/cliente/login = falhou (cookie não foi reconhecido).
if [ "$mx_code" = "200" ] || [ "$mx_code" = "302" ] && ! echo "$mx_loc" | grep -q 'dsplayground.com.br/cliente/login'; then
  ok "app.X autenticou (HTTP $mx_code)"
elif echo "$mx_loc" | grep -q 'dsplayground.com.br/cliente/login'; then
  fail "app.X redirecionou pra apex/cliente/login → cookie NÃO reconhecido"
else
  fail "app.X retornou $mx_code (esperado 200 ou 302 interno Grafana)"
fi

# ============== Resumo ==============
echo
echo -e "${YELLOW}========== RESUMO ==========${RESET}"
echo -e "  ${GREEN}PASS: $PASS${RESET}"
echo -e "  ${RED}FAIL: $FAIL${RESET}"

# Cleanup automático no trap EXIT (acima)

[ $FAIL -eq 0 ] || exit 1
