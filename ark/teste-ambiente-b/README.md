# Ambiente B — VM Ubuntu real via Vagrant + VirtualBox

VM Ubuntu 22.04 LTS rodando localmente via **Vagrant + VirtualBox**. Diferenca para Ambiente A: tem **systemd real**, **kernel real**, **rede de host real**. Permite validar Docker rodando, UFW aplicando regras, fail2ban com jails, e a stack `analytics-stack` (backend + InfluxDB) subindo de verdade.

## O que valida (alem do que A ja cobre)

- UFW + fail2ban com regras reais (`firewall` tag deixa de ser pulada)
- Docker engine instalado e funcional
- `analytics-stack` rodando: backend Flask + Socket.IO + InfluxDB sobem em containers dentro da VM
- Health check do backend respondendo via loopback (`/health/app`)
- Retencao do bucket aplicada via `configurar_retencao.py`
- Idempotencia em apply real

## O que continua fora

- Certbot/Let's Encrypt real (precisa DNS publico — vai pra Ambiente C com VM com IP publico)
- CrowdSec com bouncer Nginx em producao (subimos o agente, mas sem trafego real e dificil exercer cenarios)

## Pre-requisitos

- VirtualBox (`D:\oracle_vm\VBoxManage.exe` no setup deste host)
- Vagrant (`C:\Program Files\Vagrant\bin\vagrant.exe`)
- `machinefolder` do VirtualBox apontando para `D:\virtualbox-vms` (ja configurado neste host com `VBoxManage setproperty machinefolder D:\virtualbox-vms`)
- ~2 GB de RAM livre, ~10 GB de disco em D:

## Rodar (Windows PowerShell)

```powershell
cd D:\portifolio\ark\teste-ambiente-b

# 1. Subir a VM (~3-5 min na primeira vez baixando a box bento/ubuntu-22.04)
vagrant up

# 2. Ansible 2.10 da apt e antigo demais para community.docker.docker_compose_v2.
#    Atualizar para >= 2.14 via pip:
vagrant ssh -c "sudo apt-get install -y python3-pip && sudo pip3 install --upgrade 'ansible>=8'"

# 3. Apply do playbook (firewall ON, certbot OFF)
vagrant ssh -c "sudo bash -c 'ANSIBLE_ROLES_PATH=/portifolio/ark/ansible/roles ansible-playbook -i /portifolio/ark/teste-ambiente-a/inventory-localhost.ini /portifolio/ark/teste-ambiente-b/playbook-teste-b.yml --skip-tags tls'"

# 4. Verificar que o backend subiu na VM
vagrant ssh -c "curl -s http://127.0.0.1:5000/health/app"

# 5. Idempotencia (re-rodar deve dar failed=0)
vagrant ssh -c "sudo bash -c 'ANSIBLE_ROLES_PATH=/portifolio/ark/ansible/roles ansible-playbook -i /portifolio/ark/teste-ambiente-a/inventory-localhost.ini /portifolio/ark/teste-ambiente-b/playbook-teste-b.yml --skip-tags tls'"

# 6. Limpar quando terminar
vagrant destroy -f
```

## Resultado validado

```
1ª execucao: ok=30  changed=12  failed=0
2ª execucao: ok=29  changed= 6  failed=0   (handlers + retencao re-disparam — esperado)
curl /health/app -> { "status": "healthy", "detalhe": { "active_sessions": 0, "timestamp": "..." } }
```

Ciclo aplicado: pacotes base + UFW + fail2ban + Docker engine + git clone do mount via `file:///portifolio` + `.env` renderizado + `docker compose up` (frontend, backend, influxdb) + retencao InfluxDB + nginx vhost ativo + handler reload nginx OK. Backend respondeu `/health/app` apos retries (containers do docker compose levam ~30s).

## Diferencas do `playbook-teste-b.yml`

Em vez de `vars_files:` (que tem precedencia maior que play `vars:` no Ansible — surpresa), todas as vars ficam inline no proprio playbook. Pre-tasks adicionais:

- `git config --system --add safe.directory '*'` — git 2.35+ recusa clonar de repo cujo dono e diferente do user (mount Vagrant aparece como root, deploy clona).
- `openssl` + cert self-signed em `/etc/letsencrypt/live/{{ dominio }}/` — substitui o certbot que esta `--skip-tags tls`.

Roles aplicadas: `base` (firewall ON), `docker`, `analytics-stack` (clone+compose+retencao), `nginx` (sem certbot). `monitoring` e `crowdsec` ficam pra runs separados via `--tags`.

## Ajustes descobertos durante a execucao

- `vars_files` perde para `play vars` na precedencia do Ansible. Inlinar varaveis evita confusao silenciosa de override.
- Git clone exige `safe.directory '*'` quando rodando contra um mount Vagrant (cross-uid).
- O backend Flask precisa de ate ~30s pos `docker compose up` para responder `/health/app` — o role `analytics-stack` ja faz `retries: 20 + delay: 3`.
- A box Ubuntu vem com Ansible 2.10 (apt) — incompativel com `community.docker.docker_compose_v2`. Upgrade via pip resolve.

## Limpeza

A VM consome 2 GB RAM e ~3-5 GB em disco. Sempre `vagrant halt` quando nao estiver testando, `vagrant destroy -f` quando terminar de vez.
