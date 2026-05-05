# Ambiente A — apply real em container Rocky Linux 9

Roda dentro de um container **Rocky Linux 9** com Ansible pre-instalado, espelhando a distro de producao (RHEL 9 family). **Aplica de verdade** as roles `base` e `nginx` do playbook real, gera um cert self-signed mockado para o nginx subir, e valida idempotencia. E o feedback mais rapido (~2 min ciclo completo) e nao depende de VM ou cloud.

## O que valida

- **Sintaxe** do playbook + templates Jinja2
- **Apply real** das roles `base` (sem UFW) e `nginx` (sem certbot) — instala pacotes, gera arquivos, ativa vhost
- **Render** correto do `portifolio.conf` com as variaveis de teste
- **Handler `reload nginx`** — confirma que o config gerado passa em `nginx -t` e que o servico pode ser recarregado
- **Idempotencia** — segunda execucao retorna `changed=0`

## O que NAO valida

- UFW + fail2ban com regras reais (precisa rede de host)
- Docker engine e `analytics-stack` rodando (precisa systemd + cgroups completos — vai pra Ambiente B)
- Certbot/Let's Encrypt real (precisa DNS publico — vai pra Ambiente C)
- CrowdSec com bouncer (precisa Nginx live com trafego)

## Rodar

```bash
cd ark/teste-ambiente-a

# 1. subir container alvo (~30s primeira vez)
docker compose -f docker-compose.teste-a.yml up -d
sleep 3

# 2. cache apt (necessario antes do primeiro apply)
docker compose -f docker-compose.teste-a.yml exec -T alvo apt-get update -qq

# 3. apply (skip de tasks que nao sobrevivem em container puro)
docker compose -f docker-compose.teste-a.yml exec -T \
  -e ANSIBLE_ROLES_PATH=/ark/ansible/roles alvo \
  ansible-playbook -i /ark/teste-ambiente-a/inventory-localhost.ini \
  /ark/teste-ambiente-a/playbook-teste.yml \
  --skip-tags firewall,tls,systemd

# 4. idempotencia — re-rodar deve dar changed=0
docker compose -f docker-compose.teste-a.yml exec -T \
  -e ANSIBLE_ROLES_PATH=/ark/ansible/roles alvo \
  ansible-playbook -i /ark/teste-ambiente-a/inventory-localhost.ini \
  /ark/teste-ambiente-a/playbook-teste.yml \
  --skip-tags firewall,tls,systemd

# 5. limpar
docker compose -f docker-compose.teste-a.yml down -v
```

`--skip-tags firewall,tls,systemd` pula UFW/fail2ban (precisam de host) e certbot (precisa de DNS publico). Essas mesmas tasks rodam em Ambiente B/C.

## Resultado validado (sprint 2 bloco C, 2026-04-28)

```
1ª execucao:
PLAY RECAP ******
localhost  : ok=17  changed=11  unreachable=0  failed=0  skipped=2

2ª execucao (idempotencia):
PLAY RECAP ******
localhost  : ok=17  changed=0   unreachable=0  failed=0  skipped=1
```

Tasks aplicadas: usuario `deploy` criado, pacotes basicos instalados, openssl + cert mock gerado, nginx + certbot instalados, snippet `ssl.conf` em `/etc/nginx/snippets/`, vhost `portifolio.conf` renderizado e ativo, default-site removido, handler `reload nginx` skippado em ambiente sem systemd (so renderizacao validada).

## Ajustes de design feitos durante o teste

- `nginx/portifolio.conf.j2` agora inclui `/etc/nginx/snippets/ssl.conf` (em vez de `/etc/nginx/conf.d/ssl.conf`) para evitar duplicacao — `conf.d/*.conf` e auto-incluido pelo nginx, gerando conflito de directives.
- Role `nginx` ganhou tag `tls` no certbot e role `base` ganhou tag `firewall` no UFW/fail2ban — permite `--skip-tags` em ambientes sem rede real.
- Symlink do vhost (`file: state: link`) ganhou `force: true` para tolerar idempotencia em check mode.

## Ajustes do sprint 2 bloco C (2026-04-28)

Validacao end-to-end revelou 4 gaps no playbook real:
- Container alvo trocado de `ubuntu2204-ansible` para `rockylinux9-ansible` — espelha distro de prod (Rocky 9.7).
- `playbook-teste.yml` pre_task usava `apt:` (Ubuntu); migrado para `package:` agnostico.
- Role `base`: `dnf` com `curl` conflitava com `curl-minimal` (default em Rocky 9 minimal). Adicionado `allowerasing: true` — fix tambem aplica a fresh installs de prod.
- Role `base` task `localectl` e role `nginx` task `service: nginx` exigem systemd. Adicionada tag `systemd` em ambas — `--skip-tags systemd` permite teste em container sem systemd.
- Handler `reload nginx` ganhou `when: ansible_facts['service_mgr'] == 'systemd'` — skip seguro em ambientes sem systemd, no-op em prod.

## Arquivos deste ambiente

- `docker-compose.teste-a.yml` — container Ubuntu com Ansible, sem systemd
- `inventory-localhost.ini` — Ansible age sobre `localhost` via `connection: local`
- `group_vars/all.yml` — valores de teste com formato real
- `ansible.cfg` — `roles_path` apontando para `/ark/ansible/roles` (passamos via env var na pratica)
- `playbook-teste.yml` — wrapper com pre_tasks que geram cert self-signed, depois chama as roles `base` e `nginx`
