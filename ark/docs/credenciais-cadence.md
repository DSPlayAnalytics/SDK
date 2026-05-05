# Credenciais — cadencia de rotacao + procedimento

Tabela canonica de cadencia. Estado vivo em
`ark/docs/credenciais-rotacoes.yml` (parseado pelo workflow GHA
`credenciais-rotacao-reminder.yml` — abre issue 7d antes do
vencimento).

Sempre que rotacionar: atualiza `last_rotated` no yml + adiciona
linha no Changelog deste doc.

---

## Tabela mestre

| Credencial | Onde | Cadencia | Ultima rotacao | Por que essa cadencia |
|---|---|---|---|---|
| `ADMIN_API_TOKEN` | vault `admin_api_token` | 30d | (nunca) | Acesso a endpoints LGPD/admin. Token unico, sem MFA. |
| `INFLUXDB_TOKEN` (admin) | vault `influxdb_token` | 90d | (nunca) | Acesso total ao TSDB; archiver e backend dependem. |
| `POSTGRES_PASSWORD` (super) | vault `postgres_password` | 180d | 2026-05-02 | Super do cluster. Role app `portifolio_app` tem least-priv mas o super ainda existe. |
| `flask_secret_key` (SECRET_KEY) | vault `flask_secret_key` | 365d | (nunca) | Assina cookies de sessao. Rotacao invalida sessoes ativas — agendar com aviso. |
| `STRIPE_API_KEY` + `STRIPE_WEBHOOK_SECRET` | vault Stripe | sob demanda + apos suspeita | (nunca) | Stripe gerencia (rotation key direto na dashboard). Trocar so se comprometido. |
| `RESEND_API_KEY` | vault `resend_api_key` | 180d | (nunca) | Envia magic-link e notificacoes. Free tier 3k/mes. |
| `R2_ACCESS_KEY_ID` + `R2_SECRET_ACCESS_KEY` | vault R2 | 180d | (nunca) | Archiver + backup escrevem em bucket(s) R2. CF dashboard nao notifica vazamento. |
| `GRAFANA_ADMIN_PASSWORD` | vault `grafana_admin_password` | 180d | (nunca) | Admin Grafana — operador (cliente usa proxy auth, nao senha). |
| `NODE_AUTH_TOKEN` (PAT GitHub Packages) | GitHub Actions secret | 365d | (nunca) | Read-only `read:packages`. Vencimento padrao 1y. |
| RSA keys do `sdk_jwt` (`/app/data/keys/`) | volume Docker `backend_keys` | 365d | (nunca — issued at boot) | Assina JWT do SDK. Rotacao invalida JWTs em caches dos clientes (TTL curto mitiga). |
| SSH host keys (`/etc/ssh/ssh_host_*_key`) | host VPS | 365d | (nunca — issued at provision) | Compromisso reaparece em `known_hosts` dos clientes. |
| SSH client key (`deploy@vps`) | maquina do operador | sob demanda + apos saida de operador | — | Chave pessoal do administrador. |
| CF Origin Cert (`/etc/ssl/cloudflare-origin/*`) | host VPS | 15y (vence 2041) | 2026 (provisionamento) | CF emite ate 15y. So rotacionar antes se a private key vazar. |
| `.vault-password` (Ansible Vault) | host VPS + cofre offline | 365d | (nunca) | Decifra `group_vars/all.yml`. Compromisso = todos segredos vazam. **Backup off-site obrigatorio** — se perder, vault inacessivel. |
| Runner PAT self-hosted | GitHub Actions runner config | 365d | (nunca — issued at install) | Auth do runner com GitHub. Vence 1y se for PAT classico. |

---

## Procedimentos

### `ADMIN_API_TOKEN`

```bash
# 1. Gerar novo
NEW_TOKEN=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")

# 2. Atualizar vault
cd /opt/portifolio/ark/ansible
ansible-vault edit group_vars/all.yml
# substitui linha: admin_api_token: "<NEW_TOKEN>"

# 3. Aplicar (Ansible recria backend automaticamente se .env mudar)
make -f ../Makefile ansible-apply

# 4. Validar fingerprint novo no log
docker logs --tail 20 portifolio-backend | grep -i token_fp

# 5. Atualizar tooling/curl externo que use o token velho.

# 6. Commit do vault encriptado + atualizar credenciais-rotacoes.yml.
```

Audit interno usa `_fingerprint_admin_token()` (SHA256[:12]) — comparar antes/depois pra confirmar troca.

### `INFLUXDB_TOKEN`

InfluxDB tem tokens granulares — gerar um novo, atualizar vault, deletar antigo.

```bash
# 1. Logar no influxdb container
docker exec -it portifolio-influxdb influx auth list

# 2. Criar novo token com mesmas permissoes do atual
docker exec portifolio-influxdb influx auth create \
  --org zen --all-access \
  --description "rotated $(date -I)"
# anotar o token gerado

# 3. Atualizar vault, ansible-apply (recria backend + archiver)

# 4. Apos validacao (logs sem erro de auth no influxdb), deletar token antigo
docker exec portifolio-influxdb influx auth delete --id <id-antigo>
```

### `POSTGRES_PASSWORD` (super)

Rotacao tem trap conhecido — `POSTGRES_PASSWORD` em compose e honrada **so no initdb**. Mudar exige tambem `ALTER ROLE`. Procedimento documentado em `ark/docs/servidor-producao.md` -> "Rotacao de postgres_password" (role `analytics-stack`, task ja idempotente).

```bash
# 1. Gerar nova senha
NEW=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")

# 2. ansible-vault edit group_vars/all.yml -> postgres_password: "<NEW>"

# 3. ansible-apply — role rotaciona via ALTER ROLE + recria backend
make -f ark/Makefile ansible-apply

# 4. Validar
docker exec portifolio-postgres psql -U portifolio -d portifolio_auth -c '\du'
docker logs --tail 20 portifolio-backend | grep -i postgres
```

Coberto pela memoria `project: rotacao-postgres-password-cobertura` desde 2026-05-01 apos incidente de 502.

### `flask_secret_key`

⚠️ Rotacionar **invalida todas as sessoes ativas** (cookie `cliente_session` quebra). Agendar fora do horario comercial + comunicar.

```bash
NEW=$(python3 -c "import secrets; print(secrets.token_urlsafe(64))")
ansible-vault edit group_vars/all.yml   # flask_secret_key
make -f ark/Makefile ansible-apply
# sessoes ativas: usuarios precisam relogar
```

### Resend / R2 / Grafana / Stripe

Padrao similar: gerar nova key no provider, vault edit, ansible-apply, deletar antiga
no provider apos validacao.

### RSA keys do sdk_jwt

```bash
# Backup das chaves atuais (caso precise re-emitir JWTs nao-revogados)
docker run --rm -v portifolio_backend_keys:/keys -v /tmp:/dump alpine \
  tar czf /dump/sdk_jwt_keys_$(date -I).tar.gz /keys

# Gerar novas
docker exec portifolio-backend python -c "
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
print(priv.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode())
print(priv.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode())
" > /tmp/keys.pem
# substituir manualmente em /var/lib/docker/volumes/portifolio_backend_keys/_data/sdk_jwt_{private,public}.pem

# Restart backend
docker compose restart backend

# Clientes do SDK pegam a public key nova no proximo refresh (TTL 5min default).
```

### SSH host keys

```bash
sudo ssh-keygen -A -f /etc/ssh/   # regenera todos
sudo systemctl restart sshd
# avisar todos os operadores: "VPS rotacionou host keys, atualizar known_hosts"
ssh-keygen -F vps-15240803.vpsbr-15240803.vpshostgator.com.br
# (do lado do operador) limpar e reconectar.
```

### `.vault-password` (Ansible Vault)

```bash
# 1. Gerar nova
NEW_VPW=$(python3 -c "import secrets; print(secrets.token_urlsafe(48))")

# 2. Re-encriptar vault com nova senha
cd /opt/portifolio/ark/ansible
ansible-vault rekey group_vars/all.yml --new-vault-password-file <(echo "$NEW_VPW")

# 3. Atualizar /opt/portifolio/.vault-password (cuidado com ownership: deploy:deploy 0600)
sudo bash -c "echo '$NEW_VPW' > /opt/portifolio/.vault-password"
sudo chown deploy:deploy /opt/portifolio/.vault-password
sudo chmod 0600 /opt/portifolio/.vault-password

# 4. **OBRIGATORIO**: copiar nova senha pra cofre off-site (1Password/Bitwarden).
# Sem ela, vault e inacessivel se o filesystem do host for perdido.

# 5. Commit do vault re-encriptado em main.
```

---

## Como atualizar este doc

1. Quando rotacionar uma credencial: atualizar `last_rotated` em
   `credenciais-rotacoes.yml` + adicionar linha no Changelog deste doc.
2. Quando adicionar credencial nova: incluir em ambos os arquivos +
   procedimento aqui.
3. Workflow `credenciais-rotacao-reminder.yml` parsea o yml todo dia 1
   do mes 09:00 UTC; abre issue se `today >= last_rotated + cadence - 7d`.

---

## Changelog

- **2026-05-02** — Rotacao `postgres_password` apos refactor de role
  (Postgres role split S2 audit). Confirmacao: `ALTER ROLE` rodou,
  backend recriado, sem erro 502.
- **2026-05-04** — Doc criado consolidando cadencias.
