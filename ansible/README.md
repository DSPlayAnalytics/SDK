# Ansible

Provisionamento automatizado de servidor Linux **Rocky Linux 9** (RHEL 9 family) para rodar o portifolio analytics em producao. Alvo atual: VPS HostGator em `129.121.55.29`, dominio `dsplayground.com.br`.

Para o estado anterior (Debian/Ubuntu com UFW), ver branch `dev`.

## Preparar

```bash
cp inventory.example.ini inventory.ini
# inventory.ini ja vem com IP, porta 22022 e chave ~/.ssh/vpn

cp group_vars/all.example.yml group_vars/all.yml
# preencha os valores reais e criptografe com ansible-vault (ver secao abaixo)
```

Instale as collections requeridas (versoes fixadas em `requirements.yml` —
`community.docker` esta capada em `<5.0.0` porque a 5.x exige `ansible-core>=2.17`
e a VPS roda Ansible 2.15):

```bash
pip install --upgrade 'ansible>=8'
ansible-galaxy collection install -r ark/ansible/requirements.yml
# ou: make -f ark/Makefile ansible-deps
```

## Rodar

### Bootstrap (primeira execucao, como root)

Cria o usuario `deploy`, propaga `authorized_keys`, ativa firewalld + fail2ban, instala Docker.

```bash
ansible-playbook -i inventory.ini playbook.yml --tags base,docker -u root
```

### Execucoes seguintes (como deploy)

O inventario ja define `ansible_user=deploy`:

```bash
# dry-run
ansible-playbook -i inventory.ini playbook.yml --check --diff

# aplicar
ansible-playbook -i inventory.ini playbook.yml
```

Pelo Makefile da raiz: `make ansible-check` e `make ansible-apply`.

## O que instala

| role | responsabilidade |
|---|---|
| `base` | pacotes basicos via `dnf`, EPEL, firewalld, fail2ban, locale pt_BR, grupo `wheel`/`analytics`, usuario `deploy` com sudo NOPASSWD |
| `docker` | docker-ce + compose plugin do repo oficial CentOS, grupo docker |
| `analytics-stack` | clona repo em `/opt/portifolio`, gera `.env`, `docker compose up -d`, aplica retencao InfluxDB |
| `nginx` | Nginx + certbot (via EPEL), vhost em `/etc/nginx/conf.d/portifolio.conf`, cert Let's Encrypt, timer de renovacao |
| `crowdsec` | agente CrowdSec em container + bouncer Nginx via repo oficial CrowdSec |
| `monitoring` | Prometheus + Grafana via `docker-compose.monitoring.yml` |

Cada role tem `tasks/main.yml` e, quando aplicavel, `defaults/main.yml` e `handlers/main.yml`.

## Ordem interna do playbook

1. `base` (firewalld abre 22022/80/443, cria deploy + analytics)
2. `docker`
3. `analytics-stack` (app sobe primeiro, monitoring conecta depois)
4. `nginx` (proxy reverso + TLS)
5. `monitoring` (opt-in via `habilitar_monitoring`)
6. `crowdsec` (opt-in via `habilitar_crowdsec`)

Para rodar so uma role: `ansible-playbook -i inventory.ini playbook.yml --tags analytics-stack`.

## Segredos

### Ansible Vault (producao)

Em producao, `group_vars/all.yml` fica **criptografado com ansible-vault**. A senha mora em `/opt/portifolio/.vault-password` (fora do git, modo `0600`, dono `deploy`). O `ansible.cfg` desta pasta aponta automaticamente para esse arquivo via `vault_password_file`, entao `make ansible-check`/`make ansible-apply` leem o vault sem prompt.

Operacoes comuns:

```bash
cd ark/ansible

# ver o arquivo em claro (sem edit)
ansible-vault view group_vars/all.yml

# editar (abre $EDITOR com cleartext, re-criptografa ao salvar)
ansible-vault edit group_vars/all.yml

# criptografar um arquivo novo
ansible-vault encrypt group_vars/all.yml

# descriptografar em claro no disco (evitar — so use em emergencia)
ansible-vault decrypt group_vars/all.yml
```

Setup inicial (servidor novo):

```bash
# 1. gerar senha
openssl rand -base64 48 | tr -d '\n' > /opt/portifolio/.vault-password
chmod 0600 /opt/portifolio/.vault-password
chown deploy:analytics /opt/portifolio/.vault-password

# 2. criar all.yml a partir do example e criptografar
cp group_vars/all.example.yml group_vars/all.yml
# preencha os valores reais
ansible-vault encrypt group_vars/all.yml
```

**Nunca comitar** `inventory.ini` real, `group_vars/all.yml` em claro nem `.vault-password`. O `.gitignore` ja cobre os tres.

Tokens/senhas esperados em `group_vars/all.yml`:
- `flask_secret_key`, `admin_api_token`
- `influxdb_token`, `influxdb_init_password`
- `postgres_password`
- `grafana_admin_password`

## Diferencas vs branch `dev` (Debian/Ubuntu)

| area | dev (apt-based) | main (dnf/Rocky 9) |
|---|---|---|
| pacotes | `apt`, `apt_key`, `apt_repository` | `dnf`, `get_url` pro repo docker |
| firewall | `ufw` | `firewalld` (ansible.posix) |
| grupo sudo | `sudo` | `wheel` |
| locale | `locale_gen` | `glibc-langpack-pt` + `localectl` |
| nginx layout | `/etc/nginx/sites-available/` + symlink | `/etc/nginx/conf.d/*.conf` |
| docker repo | `download.docker.com/linux/ubuntu` | `download.docker.com/linux/centos/docker-ce.repo` |
| SELinux | N/A | disabled pela imagem HostGator — sem setbool necessario |

## Referencias

- Fluxo completo de primeiro provisionamento: `ark/ambiente-c/README.md`
- DNS no Cloudflare: `ark/ambiente-c/dns-cloudflare.md`
- Arquitetura operacional detalhada: `ark/docs/servidor-producao.md`
