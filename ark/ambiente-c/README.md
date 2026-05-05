# Ambiente C — Producao real (HostGator VPS, Rocky Linux 9)

Este e o **ambiente produtivo**. VPS HostGator provisionado com Rocky Linux 9.7, dominio `dsplayground.com.br` gerenciado pela Cloudflare, stack analytics completa atras de Nginx + Let's Encrypt.

Diferente dos ambientes A/B, aqui voce nao simula nada — o provisionamento bate num servidor real, DNS publico resolve o dominio e o certbot fala com o ACME de verdade.

## Servidor alvo

| item | valor |
|---|---|
| Provedor | HostGator VPS (vpshostgator.com.br) |
| OS | Rocky Linux 9.7 (Blue Onyx) |
| IP publico | `129.121.55.29` |
| Porta SSH | `22022` |
| User inicial | `root` (sera migrado para `deploy` no bootstrap) |
| Disco | 50 GB (40 GB livres pos install) |
| RAM | 1.7 GiB + 4 GiB swap |
| SELinux | **disabled** (default da imagem HostGator) |
| Firewalld | instalado, inativo — sera ativado pela role `base` |
| EPEL | **ja habilitado** |

## Pre-requisitos locais

- Chave SSH privada em `~/.ssh/vpn` (pareada com `authorized_keys` do root na VPS)
- Python 3.9+ no host local
- Ansible 8+ e collections:
  ```bash
  pip install --upgrade 'ansible>=8'
  ansible-galaxy collection install community.docker ansible.posix
  ```
- Dominio `dsplayground.com.br` com NS apontando para Cloudflare (ja feito no registro.br — ver `dns-cloudflare.md`)

## Modelo de permissoes (identico a A/B)

Hardening ja aplicado no repo: containers rodam non-root, compartilhando grupo `analytics` GID `10001`:

- Host: role `base` cria grupo `analytics` e adiciona `deploy` nele.
- Containers: `backend` roda como `app:analytics (10001:10001)`, `frontend` como `node (1000)` com grupo suplementar `analytics (10001)`.
- `/opt/portifolio` fica `deploy:analytics 0750`; `backend/` tem SGID (`2770`); `.env` fica `0640`; `security.log` fica `0660`.

Detalhes completos em `ark/docs/servidor-producao.md`. Validacao no Passo 8.

## Passo 1 — Validar DNS

O certbot so funciona se o nome resolve para o IP publico. Antes de rodar a role `nginx`, garanta:

```bash
dig +short dsplayground.com.br @1.1.1.1
# esperado: 129.121.55.29
```

Se ainda nao apontou, siga `dns-cloudflare.md` neste mesmo diretorio e aguarde a propagacao (1-5 min tipico).

## Passo 2 — Validar acesso SSH inicial

```bash
ssh -i ~/.ssh/vpn -p 22022 root@129.121.55.29 'cat /etc/os-release | head -3'
# esperado: NAME="Rocky Linux"  VERSION="9.7 ..."
```

Se falhar, revise:
- caminho da chave (no Windows em bash, use `/c/Users/<user>/.ssh/vpn`)
- porta 22022 (nao 22)
- fingerprint na primeira conexao (`-o StrictHostKeyChecking=accept-new`)

## Passo 3 — Preparar inventario e segredos

No diretorio `ark/ansible/`:

```bash
cp inventory.example.ini inventory.ini
cp group_vars/all.example.yml group_vars/all.yml
```

Editar `group_vars/all.yml` com segredos reais (**nao commitar**):

```bash
# gerar tokens
python3 -c "import secrets; print(secrets.token_urlsafe(32))"   # flask_secret_key
python3 -c "import secrets; print(secrets.token_urlsafe(32))"   # admin_api_token
openssl rand -hex 32                                            # influxdb_token
python3 -c "import secrets; print(secrets.token_urlsafe(16))"   # grafana_admin_password
```

Preencher os campos correspondentes em `all.yml`. Deixar `flask_secret_key` e `admin_api_token` != placeholder — o `pre_tasks` do playbook quebra se detectar os defaults.

Para producao, **criptografar**:

```bash
ansible-vault encrypt group_vars/all.yml
# rodar playbooks com --ask-vault-pass
```

## Passo 4 — Bootstrap (primeira execucao como root)

Roda so `base` e `docker` como `root`. Ao final:
- `deploy` existe, no grupo `wheel,analytics,docker`, com sudo NOPASSWD
- `authorized_keys` de root copiada para `~deploy/.ssh/`
- firewalld ativo liberando 22022/80/443
- Docker engine pronto

```bash
cd ark/ansible

ansible-playbook \
  -i inventory.ini \
  playbook.yml \
  --tags base,docker \
  -u root
```

Valide que o `deploy` aceita SSH:

```bash
ssh -i ~/.ssh/vpn -p 22022 deploy@129.121.55.29 'id'
# esperado: uid=... groups=...,wheel,analytics,docker
```

## Passo 5 — Provisionamento completo (ja como deploy)

Com `deploy` operacional, rodar o playbook inteiro — o inventario ja tem `ansible_user=deploy`:

```bash
# dry-run primeiro (ve o diff, nao aplica)
ansible-playbook -i inventory.ini playbook.yml --check --diff

# aplicar
ansible-playbook -i inventory.ini playbook.yml
```

Ordem interna (ja configurada):
1. `base` — re-valida firewalld + fail2ban
2. `docker` — re-valida engine
3. `analytics-stack` — clona/atualiza repo em `/opt/portifolio`, gera `.env`, `docker compose up -d`, aplica retencao
4. `nginx` — instala Nginx + certbot, renderiza vhost para `dsplayground.com.br`, emite cert Let's Encrypt
5. `monitoring` — Prometheus + Grafana (opt-in via `habilitar_monitoring=false` para pular)
6. `crowdsec` — agente + bouncer Nginx (opt-in via `habilitar_crowdsec=false`)

Para re-deploy so da aplicacao: `--tags analytics-stack`.
Para refazer so o Nginx+TLS: `--tags nginx`.

## Passo 6 — Validar a stack

```bash
# Do seu host local
curl -I https://dsplayground.com.br/
# esperado: HTTP/2 200 (ou 301 se o path redireciona)

ssh -i ~/.ssh/vpn -p 22022 deploy@129.121.55.29 'docker ps'
# esperado: portifolio-backend, portifolio-frontend, portifolio-influxdb rodando
```

Dentro da VPS (via SSH como deploy):

```bash
systemctl status nginx           # active (running)
systemctl status firewalld       # active (running)
systemctl status fail2ban        # active (running)
firewall-cmd --list-all          # ports: 22022 80 443
sudo tail -n 20 /opt/portifolio/backend/security.log
```

## Passo 7 — Certbot e renovacao

A role `nginx` habilita `certbot-renew.timer`. Conferir:

```bash
systemctl list-timers | grep certbot
# certbot-renew.timer deve aparecer com next run agendado

# forcar teste de renovacao (dry-run, nao consome quota)
sudo certbot renew --dry-run
```

Se o primeiro emission falhou (ex.: DNS ainda nao propagado), rodar manualmente:

```bash
sudo certbot --nginx -d dsplayground.com.br \
  --agree-tos --non-interactive \
  -m danieltisantos@gmail.com --redirect
```

## Passo 8 — Validacao do hardening (owner:group)

```bash
# grupo analytics GID 10001
getent group analytics
# esperado: analytics:x:10001:deploy

id deploy
# esperado: uid=1000 groups=...,wheel,analytics,docker

# ownership do /opt/portifolio
ls -ld /opt/portifolio /opt/portifolio/backend /opt/portifolio/backend/.env
# /opt/portifolio                drwxr-x--- deploy analytics
# /opt/portifolio/backend        drwxrws--- deploy analytics    (SGID)
# /opt/portifolio/backend/.env   -rw-r----- deploy analytics    (0640)

# users dentro dos containers
docker exec portifolio-backend id
# esperado: uid=10001(app) gid=10001(analytics)

docker exec portifolio-frontend id
# esperado: uid=1000(node) groups=...,10001(analytics)

# security.log gravavel pelo container
docker exec portifolio-backend sh -c 'echo teste >> /app/security.log && tail -n1 /app/security.log'
# esperado: teste (sem permission denied)
```

## Passo 9 — Cenarios adicionais

1. **CrowdSec em acao** — disparar 6 chamadas a `/admin/analytics/sessao/x` com token errado em 1 min; `sudo cscli decisions list` mostra o ban.
2. **Backup InfluxDB** — `docker compose exec influxdb influx backup /tmp/backup --token $TOKEN` + validar tar.gz.
3. **Multipla conexao Socket.IO** — abrir `https://dsplayground.com.br` em duas abas, verificar `evento=conectado` com sids distintos.

## Troubleshooting

### A — Certbot falha com `unauthorized` ou `NXDOMAIN`

Sintoma: `Some challenges have failed` durante a emissao.

Causa comum: DNS ainda nao resolve para `129.121.55.29`, ou Cloudflare esta com **proxy ativo (nuvem laranja)** — isso quebra o HTTP-01 challenge porque o trafego nao bate diretamente no servidor.

Fix:
```bash
dig +short dsplayground.com.br @1.1.1.1  # confirma IP
```
No Cloudflare: primeiro provisionamento com **nuvem cinza (DNS only)**. Apos cert emitido, voce pode religar proxy se quiser CDN.

### B — `ansible.posix.firewalld: module not found`

Sintoma: role `base` falha ao abrir portas.

Causa: collection `ansible.posix` nao instalada. Fix no host local:

```bash
ansible-galaxy collection install ansible.posix community.docker
```

### C — SSH com deploy falha apos bootstrap

Sintoma: `Permission denied (publickey)`.

Causa: a task que copia `authorized_keys` de root so roda se `/root/.ssh/authorized_keys` existe. Confirme:

```bash
ssh -i ~/.ssh/vpn -p 22022 root@129.121.55.29 'ls -l /root/.ssh/authorized_keys /home/deploy/.ssh/authorized_keys'
```

Se o arquivo do deploy nao existe, rodar o bootstrap de novo: `ansible-playbook ... --tags base -u root`.

### D — `Aguardar backend responder health` falha na primeira execucao

Sintoma: `post_tasks` faz 10 retries e desiste.

Causa: build dos containers + pull da `influxdb:2.7` em VPS com 1.7 GiB de RAM pode demorar mais que 50s. Fix: re-rodar so a tag `app`:

```bash
ansible-playbook -i inventory.ini playbook.yml --tags analytics-stack
```

Na segunda execucao as imagens ja estao em cache.

### E — `dnf: Error: Unable to find a match: crowdsec-nginx-bouncer`

Sintoma: role `crowdsec` termina a task do bouncer com falha.

Causa: o repo do CrowdSec pode nao ter o RPM publicado para `el9` no momento. A task tem `ignore_errors: true` — o agente sobe mesmo assim. Para instalar o bouncer manualmente:

```bash
sudo curl -s https://install.crowdsec.net | bash
sudo dnf install -y crowdsec-firewall-bouncer-nftables
```

### F — `firewall-cmd: Authorization failed` dentro do container

Sintoma: `docker exec` pra algo que precisa de firewall falha.

Causa: containers nao devem tocar firewalld do host — se aparece, revisar `--privileged` indevido no compose.

## O que fazer quando terminar

Este ambiente e permanente — nao "desligar" como VirtualBox. Para **desprovisionar**:

```bash
# dentro da VPS como deploy
cd /opt/portifolio
docker compose down -v
```

E depois, no painel HostGator, destruir a VPS. Dominio permanece no Registro.br.
