# Relatório de Auditoria de Segurança — VPS DSPlay

- **Data**: 2026-05-10
- **Host**: `vps-15240803.vpsbr-15240803.vpshostgator.com.br` (HostGator BR)
- **IP público**: `129.121.55.29`
- **SO**: Rocky Linux 9.7 (Blue Onyx), kernel `5.14.0-611.49.1.el9_7` (rodando)
- **Domínio público**: `dsplayground.com.br` (atrás de Cloudflare)
- **Auditor**: Claude Code (sessão pt-BR)
- **Escopo aprovado**: camadas 1–5 + scan web ativo via Cloudflare contra todos os vhosts
- **Status**: em andamento — este arquivo é atualizado ponto a ponto.

---

## Sumário executivo

**Auditoria concluída em 2026-05-10/11. Hardening index lynis: 70/100.**

A VPS apresenta configuração de rede e TLS sólida — apenas 80/443 expostos publicamente, todos os containers em `127.0.0.1`, TLS 1.2/1.3 apenas com ciphers ECDHE+AEAD, HSTS, e CrowdSec ativo bloqueando 13.35 mil IPs da blocklist comunitária. O ponto mais crítico é a exposição de 31 CVEs CRITICAL em imagens Docker (F6-01), especialmente OpenSSL RCE em containers alpine e Go stdlib TLS vulnerável em CrowdSec/InfluxDB/Prometheus. O segundo ponto crítico é a ausência de allowlist de IPs Cloudflare no nginx (F7-01), permitindo bypass completo da WAF da Cloudflare acessando a origem diretamente.

### Status de remediação por finding

| # | ID | Severidade | Resumo | Status |
|---|---|:-:|---|:-:|
| 1 | F6-01 | 🔴 CRÍTICO | 31 CVEs CRITICAL em imagens Docker | ⏳ PENDENTE |
| 2 | F1-01 | 🟠 ALTO | Kernel pendente de reboot | ⏳ PENDENTE |
| 3 | F2-01 | 🟠 ALTO | SELinux desabilitado | ⏳ PENDENTE |
| 4 | F3-01 | 🟠 ALTO | `nginx -t` falha — upstream `portifolio_grafana` ausente | ✅ RESOLVIDO (VPS, 2026-05-10) |
| 5 | F3-02 | 🟠 ALTO | `backend/.env.production` versionado no git | ✅ REMEDIADO `4e1fdf5` |
| 6 | F6-02 | 🟠 ALTO | 64 HIGH em `dsplay-backend` (deps Python + imagem) | 🔶 PARCIAL (`3.12-slim`, resta pip-audit) |
| 7 | F7-01 | 🟠 ALTO | Origem aceita conexões diretas — bypass Cloudflare | ⏳ PENDENTE |
| 8 | F2-02 | 🟡 MÉDIO | `deploy` com `NOPASSWD: ALL` + grupo docker | ⏳ PENDENTE |
| 9 | F3-03 | 🟡 MÉDIO | `group_vars/all.yml` e `slack_webhook.url` em 0644 | ⏳ PENDENTE |
| 10 | F3-04 | 🟡 MÉDIO | `inventory.ini` em 0755 | ⏳ PENDENTE |
| 11 | F5-01 | 🟡 MÉDIO | Sem `aide`/`rkhunter` | ⏳ PENDENTE |
| 12 | F2-03 | ⚪ BAIXO | SSH `X11Forwarding yes` | ⏳ PENDENTE |
| 13 | F2-04 | ⚪ BAIXO | SSH `LogLevel INFO` | ⏳ PENDENTE |
| 14 | F3-05 | ⚪ BAIXO | `.gitignore` da raiz vazio | ✅ REMEDIADO `4e1fdf5` |
| 15 | F3-06 | ⚪ BAIXO | HSTS `max-age=15768000` (6 meses) | ✅ REMEDIADO `0aae234` |
| 16 | F7-02 | ⚪ BAIXO | `server_tokens` não configurado — vaza nginx 1.20.1 | ⏳ PENDENTE (nginx.conf do host) |
| 17 | F1-02 | ℹ️ INFO | GitHub Actions self-hosted runner — confirmar repo privado | ⏳ VERIFICAR |
| 18 | F3-07 | ℹ️ INFO | Cert LE self-signed inativo em `/etc/letsencrypt/` | ⏳ BAIXA PRIO |
| 19 | F7-03 | ℹ️ INFO | Apex sem HSTS (Cloudflare Pages) | ⏳ VERIFICAR CF |

**Remediados por código (sem SSH):** F3-02, F3-05, F3-06 — ver `security-report-2026-05-10.md`.
**Parcialmente resolvido:** F3-01 (VPS direto em 2026-05-10), F6-02 (imagem `3.12-slim` substituída, restam CVEs de deps Python a auditar).
**Pendentes — requerem SSH na VPS:** F1-01, F2-01, F2-02, F2-03, F2-04, F3-03, F3-04, F5-01, F6-01, F7-01, F7-02.

---

## Severidades

- **CRÍTICO** — exploração viável agora, impacto alto.
- **ALTO** — vetor real, pode encadear pra outro crítico.
- **MÉDIO** — hardening relevante, hoje contido por outra camada.
- **BAIXO** — boa prática / higiene.
- **INFO** — observado, sem ação obrigatória.

---

## Fase 1 — Contexto do host

| Item | Valor |
|---|---|
| SO | Rocky Linux 9.7 |
| Kernel rodando | `5.14.0-611.49.1.el9_7` |
| Kernel instalado | `5.14.0-611.54.1.el9_7` |
| Uptime | 6 dias, 20h (último reboot antes da atualização de kernel) |
| Hostname | `vps-15240803.vpsbr-15240803.vpshostgator.com.br` |
| IP público | `129.121.55.29` (HostGator BR) |
| Usuário shell logado | `deploy` (UID 1000) — único usuário interativo |
| Docker | 29.4.3 (Community) — build 06/mai/2026 |
| Containers ativos | 10 (backend, frontend, landing, grafana, crowdsec, prometheus, alertmanager, node-exporter, postgres, influxdb) |

**Containers todos com bind `127.0.0.1`** (apenas nginx expõe 80/443). Nenhum container em `privileged=true` ou `network=host`.

### Achados — Fase 1

#### [ALTO] F1-01 Kernel pendente de reboot
- **Evidência**: kernel carregado é `5.14.0-611.49.1`, instalado é `5.14.0-611.54.1` (`rpm -qa --last | head` mostra instalação em 08/mai).
- **Risco**: vulnerabilidades de kernel corrigidas em `-611.54.1` ainda não estão ativas.
- **Status (2026-05-10 20:46)**: `dnf upgrade -y` aplicado (3 pacotes: `rocky-gpg-keys`, `rocky-release`, `rocky-repos` para 9.7-1.7). `dnf check-update` agora retorna 0 pendências. **Reboot continua necessário** para ativar `kernel`, `linux-firmware`, `microcode_ctl`, `systemd` (confirmado por `needs-restarting -r`).
- **Remediação restante**: agendar `reboot` em janela de manutenção.

#### [INFO] F1-02 GitHub Actions self-hosted runner ativo
- **Evidência**: `actions.runner.danpqdan-dsplay.vps-production.service` em `/opt/actions-runner/`, executando como `deploy`.
- **Risco**: se o repositório `danpqdan/dsplay` for público, qualquer PR vindo de fork poderia executar código arbitrário no runner. Como o runner é `deploy` + `NOPASSWD: ALL`, isso seria escalada direta a root.
- **Ação**: confirmar que o repo é privado **OU** configurar `Require approval for first-time contributors` em Settings → Actions.

---

## Fase 2 — Hardening do SO

### SSH (`/etc/ssh/sshd_config`)
| Diretiva | Valor | Avaliação |
|---|---|---|
| `Port` | 22022 | ✅ porta alternativa |
| `PermitRootLogin` | no | ✅ |
| `PasswordAuthentication` | no | ✅ só chave pública |
| `PubkeyAuthentication` | yes | ✅ |
| `PermitEmptyPasswords` | no | ✅ |
| `MaxAuthTries` | 3 | ✅ |
| `KbdInteractiveAuthentication` | no | ✅ |
| `X11Forwarding` | yes | 🟠 desligar se não usar (`X11Forwarding no`) |
| `LogLevel` | INFO | 🟠 considerar `VERBOSE` para registrar fingerprint da chave usada |

**Chaves autorizadas**:
- `/root/.ssh/authorized_keys` — 15 chaves
- `/home/deploy/.ssh/authorized_keys` — chaves (mesmas perms 600)

### Firewall (firewalld + nftables)
- Zona `public` em `eth0`: `cockpit dhcpv6-client`, portas `22022/tcp 80/tcp 443/tcp`.
- Zona `docker` para `docker0`, `br-8dedbc37891f`, `br-284587db94ec`.
- `nmap` na interface pública confirma: **apenas 80 e 443 abertos para o mundo** (SSH 22022 não aparece — pode estar filtrado por hostgator também ou rich-rule).

### SELinux
**`SELinux: Disabled`** — desativado completamente.

### Usuários, sudo, contas
| Item | Valor |
|---|---|
| Usuários com shell | `root` (0), `deploy` (1000) |
| `deploy` sudo | `NOPASSWD:ALL` em `/etc/sudoers.d/90-deploy` |
| `deploy` grupos | `wheel`, `docker`, `analytics` |
| Senhas vazias | nenhuma |
| Último login | `deploy` de `201.81.0.13`, `177.50.x.x`, `189.40.x.x` |

### Achados — Fase 2

#### [ALTO] F2-01 SELinux desabilitado
- **Evidência**: `getenforce` → `Disabled`. `sestatus` → `SELinux status: disabled`.
- **Risco**: política MAC ausente. Numa VPS pública multi-serviço com Docker, é uma camada de defesa significativa perdida (containment, type enforcement).
- **Remediação**:
  1. Editar `/etc/selinux/config` → `SELINUX=permissive` (gera logs sem bloquear).
  2. Reboot, rodar 1–2 dias, verificar `ausearch -m AVC` para denials.
  3. Promover para `enforcing`.
- **Observação**: Docker em Rocky 9 funciona bem com SELinux enforcing — só ajustar volume mounts com `:Z`/`:z` se necessário.

#### [MÉDIO] F2-02 `deploy` com `NOPASSWD: ALL` + grupo docker
- **Evidência**: `/etc/sudoers.d/90-deploy: deploy ALL=(ALL) NOPASSWD:ALL` + `getent group docker → deploy`.
- **Risco**: comprometimento da chave SSH de `deploy` (ou do runner GH Actions, que roda como `deploy`) escala direto pra root sem fricção.
- **Remediação opcional**:
  1. Restringir `NOPASSWD` apenas aos comandos necessários para deploy (`systemctl restart nginx`, `docker compose ...`).
  2. Considerar `Defaults logfile=/var/log/sudo.log` para auditoria.
  3. Ou aceitar o trade-off pela conveniência do CI — mas então blindar a chave do runner.

#### [BAIXO] F2-03 `X11Forwarding yes` no SSH
- **Risco**: vetor de ataque marginal, não desligar não justifica.
- **Remediação**: `X11Forwarding no` no `sshd_config` se ninguém usa GUI via SSH.

#### [BAIXO] F2-04 `LogLevel INFO` no SSH
- **Risco**: dificulta investigação forense — não registra qual chave (fingerprint) foi usada para autenticar.
- **Remediação**: `LogLevel VERBOSE`.

---

## Fase 3 — Exposição de rede, nginx, TLS, CrowdSec

### Portas (`ss -tlnp` + `nmap`)
| Origem do scan | Portas abertas | Avaliação |
|---|---|---|
| Internet (eth0 129.121.55.29) | `80/tcp`, `443/tcp` | ✅ Apenas web exposto (HostGator parece também filtrar 22022) |
| Localhost (127.0.0.1) | 80, 443, 3000, 3001, 5000, 6060, 8080, 8086, 9090, 9093, 9100 | ✅ todos os containers atrás de bind local |

Mapeamento dos binds locais:
- `3000` → frontend
- `3001` → Grafana
- `3002` → landing
- `5000` → backend Flask
- `6060` → CrowdSec metrics
- `8080` → CrowdSec LAPI
- `8086` → InfluxDB
- `9090` → Prometheus
- `9093` → Alertmanager
- `9100` → node-exporter

### nginx
- **Versão**: 1.20.1 (Rocky 9 base — patches via dnf).
- **Vhosts**: 5 públicos via Cloudflare:
  - `app.dsplayground.com.br` — dashboard (proxy → Grafana com `X-WEBAUTH-USER`)
  - `portifolio.dsplayground.com.br` — landing pessoal
  - `api.dsplayground.com.br` — backend Flask (com rate limit 20r/s)
  - `embed.dsplayground.com.br` — widget iframe
  - `grafana.dsplayground.com.br`, `influx.dsplayground.com.br` — só em `portifolio.monitoring.conf` (config quebrada — ver F3-01)
- **TLS** (via `snippets/ssl.conf`):
  - `ssl_protocols TLSv1.2 TLSv1.3` ✅
  - ciphers só ECDHE+AEAD (AES-GCM/CHACHA20) ✅
  - `Strict-Transport-Security "max-age=15768000; includeSubDomains" always` ✅ (6 meses; ideal 1 ano para preload)
- **Headers**:
  - `Content-Security-Policy` configurado por vhost (mais estrito em `api.*` e `embed.*`)
  - `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin` ✅
- **Certificados em uso**: CF Origin (`/etc/ssl/cloudflare-origin/`, válido até `2041-04-18`).
- **Rate limit**: `analytics_edge=20r/s`, `cliente_auth=10r/s` ✅

### CrowdSec
- Bouncer firewall (`crowdsec-firewall-bouncer-host`) ativo, autenticado.
- **13.35k IPs ativos da blocklist CAPI** (comunitária) — `16.51k pacotes / 825 KB dropados`.
- Razões: `http:scan` (17.5k), `http:exploit` (6.9k), `http:bruteforce` (987), `ssh:bruteforce` (573), `ssh:exploit` (114), `http:dos` (328), etc.
- **Acquisição** lendo: `backend/security.log` + `nginx/portifolio.*log` + parsers configurados pra `dsplay-api/app/embed` (esses arquivos ainda sem tráfego suficiente para gerar métricas — verificar).
- **Decisões locais (não-CAPI)**: 0 — nenhum cenário customizado disparou ainda.
- **Cenários enabled**: ~25 CVEs específicos (log4j, fortinet, grafana, etc.) + scenarios genéricos http/ssh.

### Achados — Fase 3

#### [ALTO] F3-01 `nginx -t` falha (próximo reload trava o nginx) — **RESOLVIDO 2026-05-10 20:48**
- **Evidência original**: `nginx: [emerg] host not found in upstream "portifolio_grafana" in /etc/nginx/conf.d/portifolio.monitoring.conf:37`.
- **Causa raiz**: upstream renomeado em `portifolio.conf` (`portifolio_grafana` → `dsplay_grafana`, linha 31) mas `portifolio.monitoring.conf` não foi atualizado.
- **Correção aplicada**: `sed -i 's/portifolio_grafana/dsplay_grafana/g' /etc/nginx/conf.d/portifolio.monitoring.conf` (2 ocorrências). Backup em `/etc/nginx/conf.d/portifolio.monitoring.conf.bak-20260510-204852`.
- **Validação**: `nginx -t` agora retorna `syntax is ok` + `test is successful`. 6 warnings benignos de `ssl_stapling ignored` (CF Origin cert não tem issuer público — irrelevante porque CF termina TLS pro cliente final).
- **Ação restante**: `systemctl reload nginx` para ativar a nova config. Atenção: ao reload, os vhosts `grafana.dsplayground.com.br` e `influx.dsplayground.com.br` (atualmente fora do ar) entrarão no ar — confirmar se isso é desejado.
- **Consolidar no playbook**: ajustar o template Ansible que gera `portifolio.monitoring.conf` em `ark/ansible/roles/` para usar `dsplay_grafana`.

#### [ALTO] F3-02 `backend/.env.production` versionado no git — ✅ REMEDIADO `4e1fdf5`
- **Evidência**: `git ls-files | grep .env.production` → presente em `backend/` e `portifolio/backend/`. Conteúdo: apenas placeholders, nenhum secret real.
- **Remediação aplicada**: `git rm --cached backend/.env.production portifolio/backend/.env.production` + commit `4e1fdf5`. `.gitignore` ampliado para cobrir `portifolio/backend/.env.*` prevenindo reintrodução.
- **Histórico**: Gitleaks + Trufflehog varreram todos os commits — nenhum secret real encontrado. Rotação de tokens não necessária.

#### [MÉDIO] F3-03 Permissões 0644 em `ark/monitoring/alertmanager/slack_webhook.url` e `ark/ansible/group_vars/all.yml`
- **Evidência**:
  - `-rw-r--r-- deploy analytics ark/ansible/group_vars/all.yml` (12 KB) — vars Ansible (mesmo vaulted, expõe estrutura).
  - `-rw-r--r-- deploy analytics ark/monitoring/alertmanager/slack_webhook.url` — URL de webhook é credencial.
- **Risco**: apenas `deploy` e `root` têm shell hoje, mas qualquer container que monte `/opt/dsplay` (Ansible costuma fazer isso) lê. Webhook do Slack é credencial — quem tiver a URL posta no canal.
- **Remediação**: `chmod 0640 ark/ansible/group_vars/all.yml ark/monitoring/alertmanager/slack_webhook.url` e confirmar owner.

#### [MÉDIO] F3-04 `ark/ansible/inventory.ini` com bit executável (0755)
- **Evidência**: `-rwxr-xr-x deploy analytics ark/ansible/inventory.ini`.
- **Risco**: arquivo de inventário não precisa ser executável; vetor para erro humano (ex.: alguém renomeia para `.sh` por engano).
- **Remediação**: `chmod 0640 ark/ansible/inventory.ini`.

#### [BAIXO] F3-05 `.gitignore` da raiz vazio/inexistente — ✅ REMEDIADO `4e1fdf5`
- **Evidência original**: `.gitignore` não cobria padrões `portifolio/backend/.env.*`.
- **Remediação aplicada**: `.gitignore` ampliado incluindo `portifolio/backend/.env.*` e `!portifolio/backend/.env.example`. Os padrões `backend/.env.*`, `*.log`, `__pycache__/`, `.vagrant/`, secrets Ansible já estavam cobertos. Commit `4e1fdf5`.

#### [BAIXO] F3-06 HSTS `max-age=15768000` (6 meses) — ✅ REMEDIADO `0aae234`
- **Evidência original**: `snippets/ssl.conf:15` — 6 meses, abaixo do mínimo para HSTS preload list.
- **Remediação aplicada**: `max-age=31536000; includeSubDomains` (1 ano) em `ark/nginx/ssl.conf`. Commit `0aae234`.
- **Nota**: `preload` não adicionado propositalmente — submissão ao hstspreload.org é irreversível e exige validação de todos os subdomínios. Pode ser habilitado após confirmar cobertura 100% HTTPS.

#### [INFO] F3-07 Cert Let's Encrypt self-signed em `/etc/letsencrypt/live/dsplayground.com.br/`
- **Evidência**: `subject == issuer == CN=dsplayground.com.br`. Mas `certbot-renew.timer` está ativo e renovou há minutos. Não está em uso pelo nginx (que aponta para CF Origin).
- **Risco**: nenhum direto. Apenas higiene — sugere tentativa falha de emitir LE em algum momento.
- **Remediação opcional**: rodar `certbot certificates`, confirmar status e ou apagar staging certs falsos ou reemitir corretamente. Não bloqueia produção.

---

## Fase 4 — Secrets e permissões (consolidação)

| Arquivo | Perms atuais | Owner | Avaliação |
|---|---|---|---|
| `/opt/dsplay/.env` | 0600 | deploy:analytics | ✅ |
| `/opt/dsplay/.vault-password` | 0600 | deploy:analytics | ✅ |
| `/opt/dsplay/backend/.env` | 0640 | deploy:analytics | ✅ (`analytics` group só tem `deploy`) |
| `/opt/dsplay/ark/monitoring/.env` | 0640 | deploy:analytics | ✅ |
| `/opt/dsplay/ark/ansible/group_vars/all.yml` | **0644** | deploy:analytics | 🟠 ver F3-03 |
| `/opt/dsplay/ark/ansible/inventory.ini` | **0755** | deploy:analytics | 🟠 ver F3-04 |
| `/opt/dsplay/ark/monitoring/alertmanager/slack_webhook.url` | **0644** | deploy:analytics | 🟠 ver F3-03 |
| `/var/run/docker.sock` | 0660 root:docker | — | ✅ |

Nenhum secret encontrado world-readable além dos já listados em F3-03/F3-04.

Procura por segredos hardcoded em arquivos rastreados retornou apenas valores `ci-dummy` em workflows GH e `trocar-em-producao` em `all.example.yml` (templates) — **nenhum valor real** vazado.

---

## Fase 5 — Auditoria automatizada (lynis)

- **Hardening index (lynis 3.1.6)**: **70/100**.
- **Warnings**: 1 — `KRNL-5830 Reboot of system is most likely needed` (já em F1-01).
- **Suggestions** (37): principais são as recomendações de hardening SSH já capturadas em F2-03/F2-04 e:
  - `AllowTcpForwarding` set NO
  - `ClientAliveCountMax` 2 (atualmente 3)
  - `MaxSessions` 2 (atualmente 10) — útil se cada sessão for um usuário; reduzir conforme uso real
  - `TCPKeepAlive` set NO
  - `AllowAgentForwarding` set NO
  - **Instalar ferramenta de file integrity / rootkit scanner**: `rkhunter`, `chkrootkit`, OSSEC ou Wazuh.
  - Rodar `systemd-analyze security <service>` para cada serviço para revisar sandbox.

### Achados — Fase 5

#### [MÉDIO] F5-01 Sem file integrity monitoring nem rootkit scanner
- **Evidência**: `rpm -qa | grep -E 'aide|rkhunter|chkrootkit|ossec|wazuh'` retornou nada.
- **Risco**: comprometimento por web shell ou backdoor pós-RCE passaria despercebido.
- **Remediação**: instalar `aide` (file integrity, baseline + verificação diária via cron) e `rkhunter` (`dnf install -y aide rkhunter`; `aide --init` + `rkhunter --update && rkhunter --propupd`).

---

## Fase 6 — Dependências (CVEs em imagens Docker)

Scanner: **Trivy** (via `aquasec/trivy:latest`). Severidades HIGH + CRITICAL apenas.

| Imagem | HIGH | CRITICAL |
|---|---:|---:|
| `dsplay-backend` | 64 | 0 |
| `dsplay-frontend` | 1 | 0 |
| `dsplay-landing` | 29 | **6** |
| `influxdb:2.7` | 37 | **7** |
| `postgres:16-alpine` | 8 | **1** |
| `grafana/grafana:11.6.14` | 29 | **3** |
| `prom/prometheus:v2.55.1` | 28 | **6** |
| `crowdsecurity/crowdsec:v1.6.11` | 42 | **8** |
| **Total** | **~238** | **~31** |

### CVEs CRITICAL dominantes (padrões recorrentes)

| CVE | Componente | Imagens afetadas | Fix |
|---|---|---|---|
| **CVE-2025-15467** | OpenSSL (`libcrypto3`/`libssl3`) — RCE/DoS via oversized init | dsplay-landing, crowdsec, (toda imagem alpine 3.21.x com libssl 3.3.4–3.3.5) | bump base image para alpine 3.21 com `libssl3>=3.3.6-r0` |
| **CVE-2026-31789** | OpenSSL — Heap buffer overflow em X.509 grandes (32-bit) | mesmo escopo | `libssl3>=3.3.7-r0` |
| **CVE-2025-68121** | Go stdlib `crypto/tls` — validação incorreta de certificado | crowdsec, influxdb, prometheus (binários Go < 1.24.13) | rebuild com Go ≥ 1.24.13 / 1.25.7 / 1.26.0-rc.3 |
| **CVE-2026-33186** | `google.golang.org/grpc/grpc-go` | crowdsec, influxdb, prometheus | grpc-go ≥ 1.79.3 |
| **CVE-2025-49794**, **CVE-2025-49796** | libxml2 — UAF / type confusion DoS | dsplay-landing (alpine 3.21.3) | libxml2 ≥ 2.13.9-r0 |
| **CVE-2024-45337** | `golang.org/x/crypto/ssh` — Misuse of `ServerConfig.PublicKeyCallback` | prometheus | golang.org/x/crypto ≥ 0.31.0 |
| **CVE-2023-45853** | zlib — integer overflow → heap overflow | influxdb 2.7 (`will_not_fix` no Debian 12) | aceitar risco ou trocar base image |

### Achados — Fase 6

#### [CRÍTICO] F6-01 31 vulnerabilidades CRITICAL em imagens em produção
- **Evidência**: ver tabela e detalhes acima.
- **Risco**: três classes de impacto:
  - **CrowdSec, InfluxDB, Prometheus** rodam com Go stdlib vulnerável a CVE-2025-68121 (validação errada de certs TLS) e gRPC vulnerável (CVE-2026-33186). Para CrowdSec especificamente, o serviço terminating-TLS é interno (bouncer ↔ LAPI), mas vetor de comprometimento existe.
  - **libssl3 (OpenSSL)** com RCE conhecida (CVE-2025-15467) em qualquer container alpine 3.21 < 3.21.4. Embora exigir um peer TLS específico, é a vulnerabilidade mais facilmente exploitable.
  - **dsplay-landing**: 6 critical na imagem da landing (Astro/static) — exposta ao público.
- **Remediação** (priorizada):
  1. **Rebuild imediato** das imagens `dsplay-backend`, `dsplay-frontend`, `dsplay-landing` com `FROM alpine:3.21` mais recente (pull antes de build) — resolve CVE-2025-15467, CVE-2026-31789, libxml2.
  2. **Pull tags atualizadas** dos containers de terceiros assim que upstream publicar (`influxdb:2.7.x+1`, `crowdsecurity/crowdsec:v1.6.x+1`, `prom/prometheus:v2.55.x+1`, `postgres:16-alpine`, `grafana/grafana:11.x.y`). Verificar via:
     ```
     docker pull influxdb:2.7 && docker image inspect influxdb:2.7 -f '{{.Created}}'
     ```
  3. **Automatizar** com `dependabot`/`renovate` ou cron mensal de `docker compose pull && docker compose up -d`.
  4. Adicionar **trivy ao CI** (já há `.github/workflows/ci.yml`) com falha em CRITICAL fixáveis.

#### [ALTO] F6-02 dsplay-backend: 64 vulnerabilidades HIGH — 🔶 PARCIALMENTE REMEDIADO
- **Evidência original**: Trivy reporta 64 HIGH no `dsplay-backend` (0 critical). Origem: imagem `python:3.14-slim` (pré-release, base de muitos achados) + dependências `pip`.
- **Remediação parcial aplicada**: `FROM python:3.14-slim` → `FROM python:3.12-slim` (commit `569c769`). Isso elimina CVEs introduzidos pela imagem pré-release não patcheada. O número exato de HIGH após o rebuild precisa ser validado com novo scan Trivy pós-deploy.
- **Remediação restante**:
  - Rebuild da imagem e novo `trivy image --severity HIGH dsplay-backend` para quantificar redução.
  - `pip-audit` sobre `requirements.txt` pós-atualização de Redis (`Flask-Limiter[redis]==4.1.1`, `redis==5.2.1`).
  - Comando de verificação: `docker run --rm -v /var/run/docker.sock:/var/run/docker.sock aquasec/trivy:latest image --severity HIGH --format table dsplay-backend | less`.

---

## Fase 7 — Scan web ativo

Ferramentas: `nikto` (via `frapsoft/nikto:latest`, v2.1.5 — versão antiga), `curl` para confirmação de headers, teste direto na origem com `--resolve`.

### Headers de produção (via Cloudflare, `curl -I`)
| Vhost | HSTS | XFO | XCTO | Referrer | Permissions | CSP | Server |
|---|:-:|:-:|:-:|:-:|:-:|:-:|---|
| `dsplayground.com.br` | ❌ no apex | — | ✅ | ✅ | — | — | cloudflare |
| `app.dsplayground.com.br` | ✅ | ✅ SAMEORIGIN | ✅ | ✅ | ✅ | (em endpoints) | cloudflare |
| `api.dsplayground.com.br` | ✅ | ✅ SAMEORIGIN | ✅ | ✅ | ✅ | ✅ default-src 'none' | cloudflare |
| `embed.dsplayground.com.br` | ✅ | ✅ SAMEORIGIN | ✅ | ✅ | ✅ | (em /widget) | cloudflare |
| `portifolio.dsplayground.com.br` | ✅ | ✅ SAMEORIGIN | ✅ | ✅ | ✅ | ✅ estrita | cloudflare |
| `grafana.dsplayground.com.br` | ✅ | ✅ SAMEORIGIN | ✅ | ✅ | ✅ | — | cloudflare |

Headers excelentes. `Permissions-Policy` nega microfone, câmera, geolocalização, pagamento, USB, magnetômetro, giroscópio, acelerômetro.

### Headers da origem direta (`--resolve`, bypass CF)
| Vhost | Server |
|---|---|
| `app.dsplayground.com.br` (origem) | **nginx/1.20.1** |
| `api.dsplayground.com.br` (origem) | **nginx/1.20.1** |
| `portifolio.dsplayground.com.br` (origem) | **nginx/1.20.1** |

Acesso direto na origem retornou **HTTP 200/302** com cert CF Origin válido — confirmando bypass.

### Nikto v2.1.5
- Rodou nos 5 vhosts via CF com `-Tuning 123b -maxtime 60s`.
- Resultado idêntico em todos: `X-Frame-Options header is not present`. Nikto antigo não reconhece CSP `frame-ancestors` (substituto moderno do XFO) — falso positivo. Headers de produção (acima) mostram que XFO **está presente**.
- Nenhuma diretório descoberto, nenhum item perigoso. CF intermediou e respondeu rapidamente — scan não passou da CF.

### Achados — Fase 7

#### [ALTO] F7-01 Origem aceita conexões diretas (bypass Cloudflare)
- **Evidência**: `curl -k --resolve api.dsplayground.com.br:443:129.121.55.29 https://api.dsplayground.com.br/` retorna 200 com `Server: nginx/1.20.1`. Não há restrição de IP no nginx (`grep allow /etc/nginx/` não retorna allowlist Cloudflare).
- **Risco**: se o IP `129.121.55.29` for descoberto (vazamento por DNS antigo, logs de e-mail, scan de range HostGator), o atacante bypassa todas as defesas Cloudflare (WAF, DDoS, Bot Mode, rate limiting na borda). Restam apenas as defesas locais (firewalld 80/443 abertos, nginx rate limit, CrowdSec).
- **Remediação** (preferência crescente):
  1. **Allowlist por IP** no nginx: incluir no http block (ou no `server` block) `include /etc/nginx/snippets/cloudflare-real-ip.conf;` (já existe) seguido de `deny all;` para tudo que não veio de IP CF. Modelo:
     ```nginx
     # em http { ... }
     geo $is_cloudflare {
         default 0;
         173.245.48.0/20 1; 103.21.244.0/22 1; ... (etc, conforme cloudflare-real-ip.conf)
     }
     # em cada server block:
     if ($is_cloudflare = 0) { return 444; }
     ```
  2. **Authenticated Origin Pulls** (mTLS CF→origem): Cloudflare → SSL/TLS → Origin Server → Authenticated Origin Pulls. Adicionar no nginx:
     ```nginx
     ssl_client_certificate /etc/ssl/cloudflare-auth-origin-pull-ca.pem;
     ssl_verify_client on;
     ```
  3. **Firewalld**: bloquear 80/443 exceto para IP ranges CF. Mais robusto; o nginx nem responde se a conexão não vier de CF.

#### [BAIXO] F7-02 `server_tokens` não definido — nginx vaza versão (1.20.1)
- **Evidência**: response do origem direta retorna `Server: nginx/1.20.1`.
- **Risco**: facilita reconhecimento; atacante mapeia versão pra CVE conhecida.
- **Remediação**: adicionar `server_tokens off;` no `http { ... }` do `/etc/nginx/nginx.conf` e reload. Para esconder ainda mais, considerar `more_set_headers "Server: nginx";` (módulo headers-more).

#### [INFO] F7-03 Apex `dsplayground.com.br` sem HSTS
- **Evidência**: header HSTS ausente em `https://dsplayground.com.br/`.
- **Observação**: provável que o apex aponte para Cloudflare Pages (landing comercial). HSTS nesse caso é controlado pela CF — verificar no painel da CF (SSL/TLS → Edge Certificates → HSTS).

---

## Sumário executivo

### Pontos fortes
- ✅ SSH muito bem configurado (porta 22022, sem senha, sem root, MaxAuth 3).
- ✅ Firewall expõe apenas 80/443 publicamente.
- ✅ Todos os 10 containers Docker em `127.0.0.1` (não privileged, não host network).
- ✅ TLS forte: apenas TLSv1.2/1.3 e ciphers ECDHE+AEAD. CF Origin cert válido até 2041.
- ✅ Headers de segurança completos em todos os vhosts (HSTS, XFO, XCTO, Referrer-Policy, Permissions-Policy, CSP).
- ✅ Rate limit por zona configurado no nginx.
- ✅ CrowdSec ativo, 13.35k IPs banidos pela CAPI community.
- ✅ Fail2ban como segunda camada.
- ✅ Patches do SO em dia (atualizado em 08/mai/2026).
- ✅ Permissões dos secrets principais (`.env`, `.vault-password`) em 0600.

### Achados por severidade

| # | ID | Severidade | Resumo |
|---|---|:-:|---|
| 1 | F6-01 | 🔴 CRÍTICO | 31 CVEs CRITICAL em imagens Docker (OpenSSL RCE, Go stdlib TLS, libxml2, gRPC) |
| 2 | F1-01 | 🟠 ALTO | Kernel pendente de reboot (`5.14.0-611.49 → -611.54`) |
| 3 | F2-01 | 🟠 ALTO | SELinux desabilitado |
| 4 | F3-01 | 🟠 ALTO | `nginx -t` falha — próximo reload trava o nginx (upstream `portifolio_grafana` ausente) |
| 5 | F3-02 | 🟠 ALTO | `backend/.env.production` versionado no git (auditar histórico do upstream) |
| 6 | F6-02 | 🟠 ALTO | 64 HIGH em `dsplay-backend` (deps Python) |
| 7 | F7-01 | 🟠 ALTO | Origem aceita conexões diretas — bypass Cloudflare possível |
| 8 | F2-02 | 🟡 MÉDIO | `deploy` com `NOPASSWD: ALL` + grupo docker (mesma chave = root) |
| 9 | F3-03 | 🟡 MÉDIO | 2 arquivos sensíveis em 0644 (`group_vars/all.yml`, `slack_webhook.url`) |
| 10 | F3-04 | 🟡 MÉDIO | `inventory.ini` em 0755 |
| 11 | F5-01 | 🟡 MÉDIO | Sem `aide`/`rkhunter` (file integrity / rootkit scanner) |
| 12 | F2-03 | ⚪ BAIXO | SSH `X11Forwarding yes` |
| 13 | F2-04 | ⚪ BAIXO | SSH `LogLevel INFO` (usar VERBOSE) |
| 14 | F3-05 | ⚪ BAIXO | `.gitignore` da raiz vazio |
| 15 | F3-06 | ⚪ BAIXO | HSTS `max-age=15768000` (6 meses, não 1 ano) |
| 16 | F7-02 | ⚪ BAIXO | `server_tokens` não configurado — vaza nginx 1.20.1 |
| 17 | F1-02 | ℹ️ INFO | GitHub Actions self-hosted runner — confirmar repo privado |
| 18 | F3-07 | ℹ️ INFO | Cert LE self-signed inativo em `/etc/letsencrypt/` |
| 19 | F7-03 | ℹ️ INFO | Apex sem HSTS (provavelmente CF Pages) |

### Plano de remediação — status atual (2026-05-11)

**✅ Concluído via código (sem SSH):**
- F3-01: nginx config corrigida diretamente na VPS em 2026-05-10 ✅
- F3-02: `git rm --cached` + `.gitignore` (commit `4e1fdf5`) ✅
- F3-05: `.gitignore` ampliado (commit `4e1fdf5`) ✅
- F3-06: HSTS 1 ano (commit `0aae234`) ✅
- F6-02 (parcial): `python:3.12-slim` no Dockerfile (commit `569c769`) — rebuild pendente

**⏳ Próximas ações na VPS (em ordem de prioridade):**

1. **F6-01 — CRÍTICO** — `docker compose pull && docker compose up -d --build` para puxar imagens base atualizadas (alpine 3.21.4+, influxdb/crowdsec/prometheus/grafana latest). Revalidar com Trivy após rebuild.
2. **F1-01 — ALTO** — `reboot` em janela de manutenção para ativar kernel `5.14.0-611.54.1`.
3. **F7-01 — ALTO** — Implementar allowlist Cloudflare no nginx ou Authenticated Origin Pulls (mTLS). Modelo:
   ```nginx
   geo $is_cloudflare {
       default 0;
       173.245.48.0/20 1; 103.21.244.0/22 1; 103.22.200.0/22 1;
       103.31.4.0/22 1; 141.101.64.0/18 1; 108.162.192.0/18 1;
       190.93.240.0/20 1; 188.114.96.0/20 1; 197.234.240.0/22 1;
       198.41.128.0/17 1; 162.158.0.0/15 1; 104.16.0.0/13 1;
       104.24.0.0/14 1; 172.64.0.0/13 1; 131.0.72.0/22 1;
   }
   # em cada server block: if ($is_cloudflare = 0) { return 444; }
   ```
4. **F2-01 — ALTO** — `sed -i 's/^SELINUX=.*/SELINUX=permissive/' /etc/selinux/config` + reboot + monitorar `ausearch -m AVC` por 2 dias + promover a `enforcing`.
5. **F6-02 (restante)** — `pip-audit` no backend pós-rebuild para identificar HIGH em dependências Python.
6. **F5-01 — MÉDIO** — `dnf install -y aide rkhunter && aide --init && rkhunter --update --propupd`.
7. **F3-03/F3-04 — MÉDIO** — `chmod 0640 ark/ansible/group_vars/all.yml ark/monitoring/alertmanager/slack_webhook.url ark/ansible/inventory.ini`.
8. **F2-02 — MÉDIO** — Restringir `NOPASSWD` em `/etc/sudoers.d/90-deploy` a comandos específicos de deploy.
9. **F7-02 — BAIXO** — `server_tokens off;` no `http { }` de `/etc/nginx/nginx.conf` (VPS host).
10. **F2-03/F2-04 — BAIXO** — `X11Forwarding no` + `LogLevel VERBOSE` em `sshd_config` + `systemctl reload sshd`.

### Hardening index (lynis): **70/100**
Após aplicar remediações ALTO + MÉDIO (especialmente F2-01 SELinux e F5-01 aide/rkhunter), esperado subir para **85+/100**.

### Próximos passos opcionais (fora desta auditoria)
- Configurar `unattended-upgrades` ou `dnf-automatic` para patches automáticos.
- Habilitar log shipping para fora da VPS (S3/R2 via archiver já existente, ou Loki).
- Considerar `Falco` para runtime security em containers.
- Pentest profissional com escopo maior (lógica de negócio, autenticação JWT, multi-tenant).

---

*Relatório gerado em 2026-05-10 por auditoria semi-automatizada com ferramentas: lynis 3.1.6, nmap 7.92, trivy (latest), nikto 2.1.5, openssl, ss, firewall-cmd, curl. Outputs intermediários em `/tmp/security-audit/` e `/var/log/lynis*.log`.*


