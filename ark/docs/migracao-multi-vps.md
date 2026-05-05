# Migração multi-VPS — monorepo → split + LB + CDN

> Plano de evolução arquitetural pra sair do monorepo de VPS única (HostGator)
> pra topologia escalável: estáticos no CDN, API stateless atrás de load balancer,
> dados num host dedicado. Estado atual canônico em `docs/PROJETO.md` e
> `ark/docs/servidor-producao.md`. **Este doc é o caminho de execução.**

---

## 1. TL;DR

Migrar de **1 VPS HostGator** (1 vCPU / 1.7 GB / SPOF) pra **5 VMs especializadas**:

```
1 VPS LB (nginx + sticky session + CrowdSec)
2 VPS API (Flask + Socket.IO, stateless, redundância)
1 VPS data (Postgres + InfluxDB + Prometheus + Grafana)
0 VPS estáticos (Cloudflare Pages)
```

**6 fases incrementais**, cada uma com rollback testável em <30min, executadas em **8-12 semanas calendário** sem janela de manutenção total maior que 30min (dados aproveitam não haver clientes pagantes).

**Custo mensal alvo** (Cenário A — DigitalOcean São Paulo, latência BR <30ms): **~US$ 84/mês ≈ R$ 420**. Cenário B (Hetzner EU, latência ~180ms BR, custo R$ 135) descrito como alternativa.

**Decisões-chave já tomadas:** 4 repos separados · Cloudflare Pages pros estáticos · nginx self-hosted pro LB · sticky session via `ip_hash` (Redis adapter quando >2 nós) · Postgres+Influx no mesmo host data · Origin Cert só no LB · GHCR pra deploy via tag de imagem · self-hosted runner central na VPS LB.

---

## 2. Estado atual

```
                          Cloudflare (CDN + DNS proxy + WAF)
                                    │
                                    ▼
                         VPS HostGator (Rocky 9.7)
                         1 vCPU · 1.7 GB · 50 GB
                         ┌─────────────────────────────┐
                         │ Nginx host (TLS, rate-limit)│
                         └────────────┬────────────────┘
                                      ▼
                    ┌─────────────────┼─────────────────┐
                    │                 │                 │
                  apex             portifolio.X      api.X
                    │                 │                 │
                    ▼                 ▼                 ▼
              landing(3002)    frontend(3000)    backend(5000)
                                                       │
                              ┌────────────────────────┼────────────────────────┐
                              ▼                        ▼                        ▼
                       postgres (rede docker)   influxdb(8086)          backend_keys vol
                       grafana(3001)            prometheus(9090)        crowdsec(6060)
```

**Single points of failure (8/8):**

1. VPS HostGator inteira — qualquer falha de host, todo produto cai.
2. Nginx do host — falha = nada chega.
3. Backend único — restart = downtime de Socket.IO.
4. InfluxDB único — corrupção = perda de dados de TODOS os clientes.
5. Postgres único — corrupção = perda de auth de TODOS os clientes.
6. Volume `backend_keys` — chaves RSA não replicadas; perda = invalida JWT em circulação.
7. CI/CD acoplado — runner está na própria VPS; se VPS down, deploy também.
8. DNS × IP único — sem DNS round-robin, todo tráfego cai no IP único.

**Capacidade:** ~1.200 sessões concorrentes (gargalo CPU). Detalhes em `docs/PROJETO.md` §9.

---

## 3. Topologia alvo

### 3.1 Diagrama detalhado

```
                                     Internet
                                        │
                         ┌──────────────┴──────────────┐
                         │   Cloudflare DNS + CDN      │
                         │   (proxied, Full strict)    │
                         └──────┬───────────────┬──────┘
                                │               │
                  estáticos     │               │     dinâmico (api/auth/socketio)
                                ▼               ▼
                  ┌──────────────────────┐   ┌────────────────────────┐
                  │  Cloudflare Pages    │   │  VPS LB                │
                  │                      │   │  (nginx + CrowdSec)    │
                  │  • dsplayground.X    │   │                        │
                  │    (landing Astro)   │   │  • TLS termination     │
                  │  • portifolio.X      │   │  • sticky ip_hash      │
                  │    (portfolio React) │   │  • health check 5s     │
                  └──────────────────────┘   │  • drain on deploy     │
                                             │  • api.dsplayground.X  │
                                             │  • app.dsplayground.X  │
                                             │    (dashboard logado)  │
                                             └─────┬──────┬───────────┘
                                                   │      │
                                       rede privada│      │rede privada
                                                   ▼      ▼
                                           ┌──────────┐ ┌──────────┐
                                           │ VPS api-1│ │ VPS api-2│ ...api-N
                                           │  Flask   │ │  Flask   │
                                           │ Socket.IO│ │ Socket.IO│
                                           │stateless │ │stateless │
                                           └─────┬────┘ └─────┬────┘
                                                 │            │
                                                 └─────┬──────┘
                                                       │ rede privada
                                                       ▼
                                           ┌─────────────────────────┐
                                           │ VPS data (privada)      │
                                           │ • Postgres 16           │
                                           │ • InfluxDB 2.7          │
                                           │ • Prometheus            │
                                           │ • Grafana (auth.proxy)  │
                                           └─────────────────────────┘

   CI/CD:
     • Self-hosted runner central na VPS LB
     • SSH outbound do runner pros api-N (rede privada)
     • Build artefatos vão pro GitHub Container Registry (ghcr.io)
     • Cada api-N faz `docker pull` da tag promovida
```

### 3.2 Inventário e custo (Cenário A — São Paulo)

| Host | Provedor / spec | vCPU/RAM/SSD | Custo/mês | Função |
|---|---|---|---|---|
| **CDN estáticos** | Cloudflare Pages (free) | — | **US$ 0** | landing + portfolio servidos do edge |
| **VPS LB** | DigitalOcean SP `s-1vcpu-2gb` | 1/2 GB/50 GB | **US$ 12** | nginx LB + CrowdSec + GH runner |
| **VPS api-1** | DigitalOcean SP `s-2vcpu-4gb` | 2/4 GB/80 GB | **US$ 24** | Flask + Socket.IO |
| **VPS api-2** | DigitalOcean SP `s-2vcpu-4gb` | 2/4 GB/80 GB | **US$ 24** | Flask + Socket.IO (redundância) |
| **VPS data** | DigitalOcean SP `s-2vcpu-4gb` | 2/4 GB/80 GB | **US$ 24** | Postgres + Influx + Prom + Grafana |
| **Backups** | Cloudflare R2 (10 GB free, depois $0.015/GB) | — | **US$ 0.50** | pg_dump + influx backup diários |
| **Cloudflare LB** (opcional, fase 5+) | $5/mês + $0.50/M req | — | **(US$ 5)** | health-routing geográfico se >1 região |
| | | **TOTAL Fase 5** | **US$ 84.50 ≈ R$ 425** | |

**Cenário B alternativo** (Hetzner Cloud EU, latência BR ~180 ms): substitui DO SP por Hetzner CPX21 (€7.05) e CPX11 (€3.79). Total: **~€24.20 ≈ R$ 135**. Use **se custo > latência** for restrição real.

### 3.3 Princípios de design

1. **Stateless API**: qualquer node atende qualquer request — exceto Socket.IO sticky por `ip_hash` na fase 4-5.
2. **Estado fora do nó de app**: DB, volumes persistentes e secrets vivem na VPS data.
3. **Estáticos no edge**: zero hop até a origem pra HTML/CSS/JS — CDN absorve tráfego de browser.
4. **Adicionar capacidade = `terraform apply`**: nenhuma mudança em código requer mais um nó.
5. **Cada fase entrega valor sem quebrar a anterior**: rollback em <30min, dados sempre presentes em pelo menos 2 lugares (origem + backup remoto) durante migração.

---

## 4. Decisões resolvidas

### 4.1 Split de repositórios — **4 repos**

| Aspecto | Escolha | Trade-off | Reabrir se... |
|---|---|---|---|
| **Repos** | `dsplayground-api` · `dsplayground-landing` · `dsplayground-portfolio` · `dsplayground-infra` | Mais ciclos de release independentes vs maior coordenação em mudanças cross-cutting | Rate de PR cross-repo > 30% dos PRs em 1 mês |
| **Onde mora `provisionar_cliente.py`** | `dsplayground-api/scripts/` | Deploy junto com backend (mesmo `pip install`) | — |
| **Onde mora Ansible/Terraform** | `dsplayground-infra` | Centralizar provisionamento de tudo num lugar | — |
| **Portfolio do Daniel pode ser público** | Sim (no repo separado) | Sem risco de runner ou secrets do produto | — |
| **SDK** | Já está separado (`dsplayground-analytics-sdk`) | — | — |

**Por quê 4 e não 3:** `dsplayground-portfolio` (showcase pessoal do Daniel) tem ciclo de release totalmente diferente de `dsplayground-landing` (copy comercial). Misturar = pulls/builds desnecessários. E portfolio precisa ser público (memória `project_portfolio_vs_produto`).

### 4.2 CDN dos estáticos — **Cloudflare Pages**

| Aspecto | Escolha | Trade-off | Reabrir se... |
|---|---|---|---|
| **Provider** | Cloudflare Pages | Já usa CF DNS; integração nativa; free tier 500 builds/mês | CF Pages limitar build artifact a <25 MB virar problema |
| **Deploy** | GitHub Action oficial `cloudflare/pages-action@v1`, push em `main` → produção; PR → branch preview | Vendor lock-in moderado | Quiser branch preview com custom domain (precisa plano pago) |
| **GitHub Packages auth no build** | Var `NODE_AUTH_TOKEN` configurada como Pages secret (não fica em build log) | — | — |
| **Fallback se CF cair** | Aceitar — CF tem 4-9s uptime; downtime de CF = downtime do mundo | Sem mitigação local viável | CF outage > 4h em 1 ano |

**Custom domain:** `dsplayground.com.br` aponta CNAME pro projeto Pages; CF auto-emite cert do domínio na borda. Origin Cert atual continua válido pro LB.

### 4.3 Provedor das VPS — **DigitalOcean São Paulo (recomendado) / Hetzner Cloud (alternativa custo)**

| Aspecto | Escolha primária | Alternativa | Reabrir se... |
|---|---|---|---|
| **Provedor** | DigitalOcean região SP1 | Hetzner Cloud (Helsinki) | Custo > 30% do MRR em 6 meses |
| **VPS API** | `s-2vcpu-4gb` ($24/mo) | CPX21 (€7.05) | Sustained CPU > 80% por 1h |
| **VPS LB** | `s-1vcpu-2gb` ($12/mo) | CPX11 (€3.79) | LB CPU > 70% (raro — nginx é leve) |
| **VPS data** | `s-2vcpu-4gb` ($24/mo) | CX22 (€5.79) | Postgres p95 query > 500ms ou Influx ingest > 5k pts/s |
| **Latência BR** | <30ms (SP→SP) | ~180ms (BR→EU) | — |
| **Terraform provider** | Sim, oficial e estável | Sim, oficial | — |
| **Rede privada interna** | DO VPC grátis | Hetzner Networks grátis | — |

**Custo decisivo:** se MRR < R$ 500 nos primeiros 3 meses, considerar mover pra Hetzner. Senão, manter SP — UX > custo no estágio comercial.

### 4.4 Load balancer — **nginx self-hosted em VPS dedicada**

| Aspecto | Escolha | Trade-off | Reabrir se... |
|---|---|---|---|
| **Tipo** | nginx OSS (não Plus) self-hosted | Cloudflare LB ($5/mo + $0.50/M req) | Tráfego sustentado > 5M req/mês (CF LB fica mais econômico) |
| **TLS** | Termina no LB (CF Origin Cert wildcard) | Encaminha plain HTTP pros api-N na VPC privada | Adicionar provedor diferente pros api-N (perde rede privada) |
| **Sticky session** | `ip_hash` (módulo nativo OSS) | Cookie sticky exigiria nginx-plus ou módulo Lua | >5% mobile users com NAT compartilhado reportarem session loss |
| **Health check** | `proxy_next_upstream` passivo + script externo `keepalived`-style: curl `/health/app` a cada 5s; remove do upstream após 2 falhas | Active health check OSS é simples mas reativo | Falha de detecção > 30s em incidente real |
| **Drain on deploy** | Ansible task: marca node como `down` no upstream, sleep 30s, deploy, sleep 5s, restaura | — | — |
| **CrowdSec** | Roda no LB (única borda de entrada do tráfego API) | Lê `/var/log/nginx/access.log` do LB; bouncer aplica decisões | Tráfego direto aos api-N (vazamento de IP) |

### 4.5 Sticky session pra Socket.IO — **`ip_hash` agora; Redis adapter quando >2 nós**

| Estágio | Estratégia | Por quê | Critério de promoção |
|---|---|---|---|
| **Fase 3-4 (1-2 nós)** | nginx `ip_hash` no upstream | Zero código adicional, OSS nativo | — |
| **Fase 5+ (>2 nós OU mobile NAT problem)** | `socket.io-redis` adapter + Redis dedicado na VPS data | Permite qualquer nó atender qualquer client; resiliente a re-LB | Reconnects causando session loss em >5% das sessões OU >2 nós permanentes |

**Onde Redis vai morar quando entrar:** mesma VPS data (cargas complementares com Postgres/Influx — Redis é leve em RAM, ~50 MB pro adapter).

### 4.6 Persistência — **VPS data dedicada agora; replica/managed quando justificar**

| Componente | Estado inicial (Fase 2) | Promoção | Critério |
|---|---|---|---|
| **Postgres 16** | Single instance + pg_dump diário pra R2 | Primary + replica leitura | Latência p95 query > 500ms sustentada por 1h, OU clientes pagos > 10 |
| **InfluxDB 2.7 OSS** | Single instance + `influx backup` diário pra R2 | InfluxDB Cloud (paid) | Tamanho do volume > 30 GB, OU taxa de ingest > 5k pts/s, OU primeiro cliente Pro contratado |
| **Backup** | Cron diário 03:00 UTC, retenção 7 dias em R2 | + retenção mensal em R2 (long-term) | Compliance LGPD do primeiro cliente exigir retenção > 30d |
| **Backups RSA `backend_keys`** | rsync diário pra R2 (criptografado com `age`) | — | — |

**Por quê não managed agora:** AWS RDS/Aurora SP custa $50+/mês mínimo; InfluxDB Cloud Free tem limite de 5 GB. Sem clientes pagantes, não justifica.

### 4.7 Migração de DNS / TLS — **Origin Cert só no LB; LB↔API plain HTTP em VPC privada**

| Aspecto | Escolha | Trade-off | Reabrir se... |
|---|---|---|---|
| **Origin Cert** | Único, instalado só no LB (válido até 2041) | Renovar manualmente em 2041 (CF avisa) | API nodes em provedor diferente do LB (sem VPC privada) |
| **TLS LB↔API** | Plain HTTP via VPC privada DO | Simples, sem certs internos | Se 1 dos critérios acima (mTLS necessário) |
| **mTLS interno** | Não agora | Adiciona complexidade de rotação de certs | Múltiplos provedores OU >3 nós OU compliance exigir |
| **CrowdSec** | Migra inteiro pro LB | Vê todo tráfego de entrada; api-N não precisam | api-N expostos diretamente |

**Migração do cert:** copiar `/etc/ssl/cloudflare-origin/{fullchain,privkey}.pem` da HostGator pra VPS LB. Não regerar (válido até 2041, sem benefício em rotacionar).

### 4.8 CI/CD pós-split — **registry-based + runner central**

| Aspecto | Escolha | Trade-off | Reabrir se... |
|---|---|---|---|
| **Registry** | GitHub Container Registry (`ghcr.io/danpqdan/dsplayground-api:<sha>`) | Free pra repos privados, integrado ao GH Actions | Migrar pra repo público (GHCR continua free) |
| **Build** | Cada `release.yml` builda + push imagem com tag `<sha>` e `latest` | Imagens reproduzíveis, rollback `docker pull <sha-anterior>` | — |
| **Deploy** | `deploy.yml` SSH outbound do runner pros api-N: `docker pull && docker compose up -d --no-deps` | Drain implícito via LB durante restart (sticky cai pro outro nó) | — |
| **Self-hosted runner** | 1 central na VPS LB (não nos api-N) | Runner único = SPOF de deploy, mas rápido restaurar | Repo público sem mitigação (forks rodam código) |
| **Rollback** | `docker pull ghcr.io/.../api:<sha-anterior>` em <2min | Imagens ficam no registry indefinidamente (sem GC) | — |

**Self-hosted runner em VPS DO:** SSH externo permitido (HostGator bloqueia 22022; DO não bloqueia 22 nem 22022). Pode até promover pra cloud-hosted runner GitHub se segurança virar problema (deploy via SSH chave armazenada como secret).

### 4.9 Observabilidade multi-host — **Prometheus central com static config + logs locais**

| Aspecto | Escolha | Trade-off | Reabrir se... |
|---|---|---|---|
| **Prometheus** | Único, na VPS data | Scrape cross-VPC funciona | >5 nodes (overhead de scrape vira problema) |
| **Service discovery** | File-based (`targets.yml`) gerado pelo Ansible | Simples; novo nó = re-aplicar Ansible | Auto-scaling real (raro) — então Consul ou DO API SD |
| **Logs** | Local (cada VM) + filebeat OPCIONAL pra Loki | Sem custo de storage centralizado agora | Volume > 1 GB/dia OU compliance exigir centralização |
| **Tracing** | Não agora | OpenTelemetry adiciona dependência sem ROI claro | Bug de produção exigir trace distribuído |
| **Alertas** | Alertmanager → Discord webhook (pessoal do Daniel) | Free, push notification | Time crescer (>1 dev) — então PagerDuty/OpsGenie |

**Scrape config:**
```yaml
scrape_configs:
  - job_name: 'api'
    file_sd_configs:
      - files: ['/etc/prometheus/targets/api.yml']
  - job_name: 'lb'
    static_configs:
      - targets: ['lb-internal:9100']
  - job_name: 'data-self'
    static_configs:
      - targets: ['localhost:9100']
```

Ansible role `api-node` adiciona o IP novo em `/etc/prometheus/targets/api.yml` na VPS data e dispara reload (`SIGHUP`).

### 4.10 Bootstrapping de nó novo — **Terraform + cloud-init + Ansible role**

| Etapa | Ferramenta | Tempo target |
|---|---|---|
| **Provisionar VPS** | `terraform apply -target=module.api_node[2]` | ~60s |
| **Cloud-init** | Instala Docker, configura usuário `deploy`, baixa chave SSH do runner | ~3 min |
| **Ansible role `api-node`** | `make -f ark/Makefile ansible-apply -t api-node -l api-3` | ~5 min |
| **Pull imagem + start** | `docker compose up -d` (compose copiado pelo Ansible) | ~2 min |
| **LB inclui no upstream** | Ansible task no LB regenera `upstream.conf` + `nginx -s reload` | ~30s |
| **Health check valida** | `curl https://api.dsplayground.com.br/health/app` (via LB, deve responder do api-3) | ~30s |
| **TOTAL** | | **<12 min** ✅ meta atingida |

---

## 5. Plano de migração em fases

> **Convenção em todas as fases:**
> - **Pré-requisito**: o que precisa estar pronto antes
> - **Passos**: comandos numerados executáveis
> - **Validação**: comando exato + saída esperada
> - **Rollback**: como reverter em <30min
> - **Tempo**: calendário (incluindo testes e janela de manutenção, se houver)

### Fase 0 — Prep: split de repositórios (semana 1-2, sem downtime)

**Pré-requisito:** monorepo `portifolio` em `dev` no estado canônico atual; suite verde (211 backend + 15 landing).

**Passos:**

1. **Criar 4 repos vazios no GitHub:**
   ```
   gh repo create danpqdan/dsplayground-api --private
   gh repo create danpqdan/dsplayground-landing --private
   gh repo create danpqdan/dsplayground-portfolio --public
   gh repo create danpqdan/dsplayground-infra --private
   ```

2. **Extrair history preservando blame** com `git filter-repo`:
   ```bash
   # Em working copy fresh do monorepo
   git clone git@github.com:danpqdan/portifolio.git ../portifolio-backend
   cd ../portifolio-backend
   git filter-repo --path backend --path-rename backend/:
   git remote add origin git@github.com:danpqdan/dsplayground-api.git
   git push -u origin main

   # Repetir pra landing/, frontend/, ark/
   ```

3. **Setup CI por repo:** copiar `.github/workflows/ci.yml` adaptado pra cada repo (lint + test + build, sem deploy).

4. **Validação:**
   - `gh run list -R danpqdan/dsplayground-api --limit 1` → status `completed success`
   - Cada repo builds standalone (`docker build` ou `npm run build`)
   - `git log --oneline | head -20` em cada repo mostra history relevante (não tudo do monorepo)

5. **Manter monorepo `portifolio` como autoritativo até Fase 4** — todos os deploys ainda saem dele. Os 4 repos novos só entram em `release.yml` e deploy a partir da Fase 3.

**Rollback:** apagar os 4 repos novos. Monorepo intacto.

**Tempo:** 2-4 dias úteis (1 desenvolvedor) — extração + CI por repo + validação.

---

### Fase 1 — Estáticos pro CDN (semana 2-3, downtime ~5 min)

**Pré-requisito:** Fase 0 completa; `dsplayground-landing` e `dsplayground-portfolio` com CI verde.

**Passos:**

1. **Criar projetos no Cloudflare Pages:**
   ```
   wrangler pages project create dsplayground-landing --production-branch main
   wrangler pages project create dsplayground-portfolio --production-branch main
   ```

2. **Adicionar secrets no Cloudflare Pages:**
   ```
   wrangler pages secret put NODE_AUTH_TOKEN --project-name=dsplayground-landing
   # Cole o PAT GitHub com read:packages
   wrangler pages secret put PUBLIC_API_URL --project-name=dsplayground-landing
   # https://api.dsplayground.com.br
   ```

3. **Adicionar GH Action de deploy nos repos:**
   ```yaml
   # .github/workflows/deploy-pages.yml em cada repo de estático
   on: { push: { branches: [main] } }
   jobs:
     deploy:
       runs-on: ubuntu-latest
       steps:
         - uses: actions/checkout@v4
         - uses: actions/setup-node@v4
           with: { node-version: 22 }
         - run: npm ci && npm run build
           env:
             NODE_AUTH_TOKEN: ${{ secrets.NODE_AUTH_TOKEN }}
             PUBLIC_API_URL: ${{ vars.PUBLIC_API_URL }}
         - uses: cloudflare/pages-action@v1
           with:
             apiToken: ${{ secrets.CF_API_TOKEN }}
             accountId: ${{ secrets.CF_ACCOUNT_ID }}
             projectName: dsplayground-landing
             directory: dist
   ```

4. **Push em `main`** dos dois repos → CF Pages builda + publica em `<projeto>.pages.dev`.

5. **Validação prévia ao DNS cutover:**
   - `curl https://dsplayground-landing.pages.dev/` → HTTP 200
   - `curl https://dsplayground-portfolio.pages.dev/` → HTTP 200
   - Lighthouse perf score > atual da HostGator

6. **DNS cutover** (Cloudflare dashboard):
   - `dsplayground.com.br` (apex) → CNAME flatten pra `dsplayground-landing.pages.dev`
   - `portifolio.dsplayground.com.br` → CNAME pra `dsplayground-portfolio.pages.dev`
   - Aplicar; CF propaga em <1 min (já está laranja)

7. **Limpar nginx do host** — remover blocos `location /` dos vhosts apex e portifolio.X (mas **manter** o vhost de `api.X`!).

8. **Stop dos containers obsoletos:**
   ```
   docker compose stop landing frontend
   ```
   (Não remover ainda — fase 1 só DNS-redirect; containers ficam parados como rollback rápido.)

**Validação pós-cutover:**
- `curl -I https://dsplayground.com.br/` → header `cf-ray` presente, `server: cloudflare`
- `curl -I https://api.dsplayground.com.br/health/app` → 200 (ainda na HostGator, intacto)
- Browser: navegar landing inteira, formulários funcionam (apontam pra api.X correto)
- 0 errors no Cloudflare Pages logs
- Lighthouse mobile: LCP < 2.5s

**Rollback** (testar antes!):
- DNS: reverter os 2 CNAMEs pra IP da HostGator (registro A)
- `docker compose start landing frontend` (~30s)
- Total <5 min

**Tempo:** 3-5 dias úteis (1 dev) — incluindo branch preview + Lighthouse.

---

### Fase 2 — VPS data dedicada (semana 3-5, downtime 15-30 min)

**Pré-requisito:** Fase 1 estável por 1 semana; backup recente do Postgres + InfluxDB validado.

**Passos:**

1. **Provisionar VPS data** (DO `s-2vcpu-4gb` em SP1):
   ```bash
   cd dsplayground-infra/terraform
   terraform apply -target=module.vps_data
   # Outputs: vps_data_ipv4 (público), vps_data_private_ipv4 (VPC)
   ```

2. **Cloud-init** instala Docker + configura WireGuard de VPC entre VPS data e HostGator (intermediário; tunnel cai depois quando api-N estiverem em DO).

3. **Ansible role `vps-data`:**
   - Instala compose `data-stack/docker-compose.yml` (Postgres + Influx + Prom + Grafana + node-exporter)
   - Volumes nomeados: `data_postgres_data`, `data_influxdb_data`, `data_grafana_data`, `data_prometheus_data`
   - Não expõe portas externamente; bind tudo em `0.0.0.0:<port>` mas `ufw` só libera da subnet VPC

4. **Migração de dados (janela de manutenção):**

   ```bash
   # Anuncia manutenção (status page)
   # Para HostGator backend (Socket.IO disconnect)
   ssh deploy@hostgator "docker compose stop backend"

   # 1) Postgres
   ssh deploy@hostgator "docker exec portifolio-postgres pg_dumpall -U portifolio" \
     | ssh deploy@vps-data "docker exec -i data-postgres psql -U portifolio"
   # validar contagem de rows: SELECT count(*) FROM sites; em ambos deve bater.

   # 2) InfluxDB
   ssh deploy@hostgator "docker exec portifolio-influxdb influx backup /tmp/influx-backup"
   ssh deploy@hostgator "tar czf - -C /tmp influx-backup" \
     | ssh deploy@vps-data "tar xzf - -C /tmp"
   ssh deploy@vps-data "docker exec data-influxdb influx restore /tmp/influx-backup"

   # 3) backend_keys (chaves RSA do JWT)
   ssh deploy@hostgator "tar czf - -C /var/lib/docker/volumes/portifolio_backend_keys/_data ." \
     | ssh deploy@vps-data "mkdir -p /tmp/keys && tar xzf - -C /tmp/keys"
   # Volume vai ser remontado nos api-N na fase 3 — guardar em R2 também
   ```

5. **Atualizar backend HostGator** pra apontar `TENANTS_DATABASE_URL` e `INFLUXDB_URL` pra IP privado da VPS data (via WireGuard):
   ```
   sed -i 's/postgres:5432/10.x.x.x:5432/' /opt/portifolio/backend/.env
   sed -i 's|http://influxdb:8086|http://10.x.x.x:8086|' /opt/portifolio/backend/.env
   docker compose up -d --force-recreate backend
   ```

6. **Stop e remove containers postgres+influxdb na HostGator** — só backend continua lá.

**Validação:**
- `curl https://api.dsplayground.com.br/health/app` → 200
- `curl https://api.dsplayground.com.br/health/influxdb` → 200
- Login no dashboard cliente → vê dados históricos (queries InfluxDB do bucket cliente_X retornam)
- `docker logs portifolio-backend` em HostGator: 0 erros de conexão

**Rollback** (em <30min):
- Subir Postgres + InfluxDB de volta na HostGator a partir dos volumes originais (NÃO removidos, só parados)
- Reverter `.env` do backend
- `docker compose up -d --force-recreate backend`

**Tempo:** 5-7 dias úteis (provisionamento + Ansible role + 1 dia de migração com janela de manutenção em horário de baixo tráfego, ex: domingo 03:00 UTC).

---

### Fase 3 — VPS LB + 1 API node (semana 5-7, downtime ~5 min)

**Pré-requisito:** Fase 2 estável por 1 semana.

**Passos:**

1. **Provisionar VPS LB** (DO `s-1vcpu-2gb` SP1) e **api-1** (DO `s-2vcpu-4gb` SP1):
   ```bash
   terraform apply -target=module.vps_lb -target=module.api_node[1]
   ```

2. **Configurar VPC privada** entre LB ↔ api-1 ↔ data (mesma rede DO).

3. **Ansible role `lb`:**
   - nginx + CrowdSec
   - vhost `api.dsplayground.com.br` com upstream `api_pool`:
     ```nginx
     upstream api_pool {
         ip_hash;
         server 10.0.1.10:5000 max_fails=2 fail_timeout=30s;  # api-1 IP privado
         keepalive 32;
     }
     ```
   - TLS termination com Origin Cert copiado da HostGator
   - CrowdSec config migrada (decisões existentes preservadas via export/import)

4. **Ansible role `api-node`:**
   - Docker + compose mínimo: só backend
   - `.env` com `TENANTS_DATABASE_URL` e `INFLUXDB_URL` apontando pra IP privado da VPS data
   - Volume `backend_keys` montado a partir de R2 (rsync no boot via cloud-init)
   - Pull imagem `ghcr.io/danpqdan/dsplayground-api:latest`

5. **Validação prévia ao DNS cutover** (sem trocar DNS ainda):
   - SSH túnel: `ssh -L 8888:lb-internal:443 deploy@vps-lb`
   - `curl -k -H 'Host: api.dsplayground.com.br' https://localhost:8888/health/app` → 200
   - Verificar log nginx no LB: request bate em api-1 corretamente

6. **DNS cutover de `api.dsplayground.com.br`:**
   - Cloudflare: `api.X` → muda IP do registro A pra IP público da VPS LB
   - Mantém proxied (laranja)
   - TTL CF é 5 min; clientes velhos podem demorar 5 min pra reconectar

7. **Stop backend na HostGator** após validar tráfego no LB:
   ```
   ssh deploy@hostgator "docker compose stop backend"
   ```

**Validação:**
- `curl https://api.dsplayground.com.br/health/app` → 200, header `x-served-by: api-1` (adicionar isso no nginx do api-1 pra rastreabilidade)
- Socket.IO: cliente reconecta em <5s, recebe `connect` event, envia `analytics_data` evento, recebe ACK
- Grafana dashboard cliente continua funcionando (auth.proxy via LB)
- CrowdSec no LB: lendo `/var/log/nginx/access.log` da VPS LB (não da HostGator)

**Rollback:**
- DNS: reverter `api.X` pro IP da HostGator
- `ssh deploy@hostgator "docker compose start backend"`
- Total <5 min

**Tempo:** 5-7 dias úteis.

---

### Fase 4 — API node 2 (semana 7-9, sem downtime)

**Pré-requisito:** Fase 3 estável por 1 semana.

**Passos:**

1. **Provisionar api-2** (DO `s-2vcpu-4gb` SP1):
   ```bash
   terraform apply -target=module.api_node[2]
   ```

2. **Ansible role `api-node`** aplica idêntico ao api-1.

3. **Adicionar api-2 no upstream do LB:**
   ```nginx
   upstream api_pool {
       ip_hash;
       server 10.0.1.10:5000 max_fails=2 fail_timeout=30s;  # api-1
       server 10.0.1.11:5000 max_fails=2 fail_timeout=30s;  # api-2
       keepalive 32;
   }
   ```
   - Ansible regenera + `nginx -s reload`

4. **Validação de sticky session (crítica):**
   - Browser: abre dashboard, monitora rede
   - Request 1 vai pra api-X (X = api-1 ou api-2 dependendo de IP)
   - Recarrega página: deve ir pro mesmo X (`ip_hash` é determinístico)
   - Restart do api-X: cliente cai pro outro nó (LB faz failover) — Socket.IO reconnect resolve

5. **Teste de drain** (deploy real):
   ```bash
   # No LB: marca api-1 como down
   ansible-playbook -i inventory.ini drain.yml -e node=api-1
   # Aguarda 30s pra conexões drenarem
   # Deploy api-1: docker pull + restart
   ssh deploy@api-1 "docker pull ghcr.io/.../api:<sha> && docker compose up -d --no-deps backend"
   # Health check: curl http://10.0.1.10:5000/health/app → 200
   # Restaura no LB
   ansible-playbook -i inventory.ini undrain.yml -e node=api-1
   ```

**Validação:**
- 2 nós aparecem no upstream do nginx (`/nginx_status`)
- Request rate split aproximadamente 50/50 ao longo de 1h (depende de distribuição de IPs)
- Web Vitals dashboard intacto (sem perda de eventos)
- Socket.IO: 0 reconnects "anormais" (>5/min) após estabilização

**Rollback:**
- Remover api-2 do upstream + `nginx -s reload`
- `terraform destroy -target=module.api_node[2]`
- Total <10 min

**Tempo:** 3-5 dias úteis.

---

### Fase 5 — Automação de scale (semana 9-12)

**Pré-requisito:** Fase 4 estável por 1 semana.

**Passos:**

1. **Refatorar Terraform** pra módulo reutilizável:
   ```hcl
   # dsplayground-infra/terraform/modules/api-node/main.tf
   variable "node_index" { type = number }
   resource "digitalocean_droplet" "api" {
     name = "api-${var.node_index}"
     size = "s-2vcpu-4gb"
     region = "sp1"
     # ...
   }
   ```

2. **Ansible role `api-node` totalmente idempotente:**
   - Re-aplicar 100x = mesmo resultado
   - Tags pra reaproveitar: `--tags docker`, `--tags app`, `--tags lb-register`

3. **Auto-update do upstream nginx no LB:**
   - Ansible task na role `lb` regenera `/etc/nginx/conf.d/upstream.conf` a partir de inventário
   - Roda automaticamente quando `api-node` adiciona/remove host

4. **Documentação de operação:**
   - `dsplayground-infra/docs/scale-up.md`: passos pra adicionar nó (espelho desta fase)
   - `dsplayground-infra/docs/scale-down.md`: passos pra remover nó com drain

5. **Teste end-to-end:**
   ```bash
   # Cenário: simulando "preciso de api-3 agora"
   time terraform apply -var="api_node_count=3"
   time ansible-playbook -i inventory.ini playbook.yml -l api-3
   # Meta: total <15 min
   ```

6. **Decisão pendente:** se decidir Cloudflare LB ($5/mês), migra DNS de `api.X` pra CF LB pool com 2 origens (LB-A em SP1, LB-B em outro DC) — escopo da Fase 6.

**Validação:**
- `terraform apply` → `ansible-playbook` → primeiro request com sucesso em <15 min
- Documentação suficiente pra outro dev fazer sem ajuda

**Rollback:** scale automation é aditivo; sem rollback necessário (mantém modo manual da Fase 4).

**Tempo:** 5-7 dias úteis.

---

## 6. Migração de dados — checklist de detalhe

### 6.1 Postgres

**Tamanho atual:** confirmar antes da Fase 2 com `docker exec portifolio-postgres psql -U portifolio -c "SELECT pg_size_pretty(pg_database_size('portifolio_auth'));"` — esperado < 100 MB no estágio atual (sem clientes pagos).

**Procedimento (janela ~5 min):**
```bash
# 1) Backup final
ssh deploy@hostgator "docker exec portifolio-postgres pg_dumpall -U portifolio --clean --if-exists" > backup-final.sql
gzip backup-final.sql && wrangler r2 object put backups/postgres/$(date +%Y%m%d-final).sql.gz --file backup-final.sql.gz

# 2) Para backend
ssh deploy@hostgator "docker compose stop backend"

# 3) Restore na VPS data
cat backup-final.sql | ssh deploy@vps-data "docker exec -i data-postgres psql -U portifolio"

# 4) Validação
ssh deploy@vps-data "docker exec data-postgres psql -U portifolio -d portifolio_auth -c '
  SELECT count(*) AS sites FROM sites;
  SELECT count(*) AS users FROM clientes_users;
  SELECT count(*) AS sessoes FROM clientes_users_sessoes WHERE revogada_em IS NULL;
'"
# Comparar com mesmas queries na HostGator antes do stop — deve bater.

# 5) Apontar backend pra novo host (passo 5 da Fase 2)
```

**Downtime estimado:** 3-5 min.

### 6.2 InfluxDB

**Tamanho atual:** confirmar com `du -sh /var/lib/docker/volumes/portifolio_influxdb_data/_data` na HostGator. Esperado <1 GB no estágio atual.

**Procedimento (janela ~10 min):**
```bash
# 1) Backup
ssh deploy@hostgator "docker exec portifolio-influxdb influx backup /tmp/influx-backup --org zen"
ssh deploy@hostgator "tar czf - -C /tmp influx-backup" > influx-backup.tar.gz
wrangler r2 object put backups/influxdb/$(date +%Y%m%d-final).tar.gz --file influx-backup.tar.gz

# 2) Restore na VPS data
cat influx-backup.tar.gz | ssh deploy@vps-data "tar xzf - -C /tmp"
ssh deploy@vps-data "docker exec data-influxdb influx restore /tmp/influx-backup --full"

# 3) Validação
ssh deploy@vps-data "docker exec data-influxdb influx bucket list --org zen"
# Deve listar todos os buckets cliente_<slug> + portifolio_prod

# Spot check de dados:
ssh deploy@vps-data "docker exec data-influxdb influx query 'from(bucket:\"portifolio_prod\") |> range(start: -7d) |> count()' --org zen"
```

**Downtime estimado:** 8-12 min (Influx restore é mais lento que pg_restore).

### 6.3 Volume `backend_keys` (chaves RSA do JWT)

**Crítico:** se perder, todos os JWTs em circulação invalidam imediatamente.

**Procedimento:**
```bash
# 1) Backup criptografado
ssh deploy@hostgator "
  cd /var/lib/docker/volumes/portifolio_backend_keys/_data
  tar czf - .
" | age -r <chave-publica-age> > backend-keys-$(date +%Y%m%d).tar.gz.age
wrangler r2 object put backups/keys/$(date +%Y%m%d).tar.gz.age --file backend-keys-*.age

# 2) Em CADA api-N (boot via cloud-init), restore:
wrangler r2 object get backups/keys/latest.tar.gz.age --file /tmp/keys.age
age -d -i /etc/age/identity.txt /tmp/keys.age | tar xzf - -C /var/lib/docker/volumes/api_backend_keys/_data
chown -R 10001:10001 /var/lib/docker/volumes/api_backend_keys/_data
```

**Identidade `age`:** gerada uma vez, chave privada armazenada em DigitalOcean secret + Ansible Vault (não no git).

### 6.4 Janela de manutenção total

| Item | Downtime |
|---|---|
| Fase 2 (DB) | 15-30 min |
| Fase 3 (LB cutover) | <5 min |
| Outras fases | 0 |
| **Total acumulado** | **<35 min** ao longo de 12 semanas |

Agendar Fase 2 em domingo 03:00 UTC (00:00 BRT) — janela de tráfego mais baixo. Anunciar com 48h de antecedência via página de status (mesmo sem clientes pagantes, virtude da disciplina).

---

## 7. CI/CD pós-split

### 7.1 Workflows por repo

| Repo | Workflow | Trigger | Ação |
|---|---|---|---|
| **dsplayground-api** | `ci.yml` | PR, push main | pytest 211 testes + ruff + mypy |
| **dsplayground-api** | `release.yml` | tag `v*` ou push main | `docker build` + `docker push ghcr.io/.../api:<sha>` + `:latest` |
| **dsplayground-api** | `deploy.yml` | `workflow_run` release OK | runner LB ssh-deploya em api-1, api-2, ... sequencial com health check |
| **dsplayground-landing** | `ci.yml` | PR, push main | vitest 15 testes + astro check |
| **dsplayground-landing** | `deploy-pages.yml` | push main | CF Pages auto-deploy |
| **dsplayground-portfolio** | `ci.yml` | PR, push main | eslint + vitest |
| **dsplayground-portfolio** | `deploy-pages.yml` | push main | CF Pages auto-deploy |
| **dsplayground-infra** | `ci.yml` | PR, push main | ansible-lint + tflint + `docker compose config` |
| **dsplayground-infra** | `apply.yml` | `workflow_dispatch` (manual) | `terraform plan` + apply (com aprovação) |

### 7.2 Estratégia de deploy

**API: registry-based (não build-on-host).**

```yaml
# release.yml
- uses: docker/build-push-action@v5
  with:
    context: .
    push: true
    tags: |
      ghcr.io/danpqdan/dsplayground-api:${{ github.sha }}
      ghcr.io/danpqdan/dsplayground-api:latest
    secrets: |
      "NODE_AUTH_TOKEN=${{ secrets.NODE_AUTH_TOKEN }}"

# deploy.yml (no runner self-hosted da VPS LB)
- name: Deploy api-1
  run: |
    ssh deploy@api-1 "
      docker pull ghcr.io/danpqdan/dsplayground-api:${{ github.sha }} &&
      docker compose up -d --no-deps backend &&
      curl -f http://localhost:5000/health/app
    "
- name: Deploy api-2 (após api-1 saudável)
  run: |
    ssh deploy@api-2 "..."
```

**Estáticos:** Cloudflare Pages cuida sozinho.

### 7.3 Rollback testado

```bash
# Pegar SHA anterior
PREV_SHA=$(gh release list -R danpqdan/dsplayground-api --limit 2 | tail -1 | awk '{print $1}')

# Deploy do SHA anterior em todos os api-N
for node in api-1 api-2; do
  ssh deploy@$node "docker pull ghcr.io/.../api:$PREV_SHA && docker tag ghcr.io/.../api:$PREV_SHA ghcr.io/.../api:latest && docker compose up -d --no-deps backend"
done
```

**Meta:** rollback completo em <2 min após decisão.

---

## 8. Observabilidade multi-host

### 8.1 Prometheus na VPS data

**Scrape config (gerado pelo Ansible):**
```yaml
scrape_configs:
  - job_name: 'data-self'
    static_configs:
      - targets: ['localhost:9100', 'localhost:9090']

  - job_name: 'lb'
    static_configs:
      - targets: ['10.0.0.10:9100']  # node-exporter no LB

  - job_name: 'api'
    file_sd_configs:
      - files: ['/etc/prometheus/targets/api.yml']
        refresh_interval: 30s

  - job_name: 'backend-app'
    file_sd_configs:
      - files: ['/etc/prometheus/targets/api.yml']
    metrics_path: '/metrics'
    scheme: http
    relabel_configs:
      - source_labels: [__address__]
        regex: '(.+):9100'
        target_label: __address__
        replacement: '${1}:5000'
```

`/etc/prometheus/targets/api.yml` é gerado pela Ansible role `api-node` quando provisiona ou remove host:
```yaml
- targets: ['10.0.1.10:9100', '10.0.1.11:9100']
  labels: { service: api }
```

### 8.2 Logs

**Default (Fase 5):** logs locais em cada VM, retenção 7 dias com `logrotate`.

**Promoção pra centralizado** (gatilho: volume > 1 GB/dia):
- Loki na VPS data
- Filebeat em cada VM enviando push (não pull, pra simplificar firewall)

### 8.3 Alertas mínimos

| Alerta | Threshold | Ação |
|---|---|---|
| `api_node_down` | `up{job="api"} == 0` por 2 min | LB já remove via health-check; alerta apenas notifica Discord |
| `lb_down` | LB não responde `/health` por 1 min | Pager (crítico — sem LB = sem produto) |
| `data_disk_high` | `node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes < 0.15` | Notifica; ação manual |
| `postgres_p95_query_high` | p95 > 500ms por 1h | Avalia se promoção pra replica é hora |
| `cpu_sustained` | api-N CPU > 80% por 1h | Avalia se hora de adicionar nó |

Webhook Discord: livre, suficiente pra time de 1 dev. Promover pra OpsGenie quando segundo dev entrar.

---

## 9. Custo total mensal

### 9.1 Cenário A — DigitalOcean SP (recomendado)

| Item | Custo (US$/mês) | R$ aprox. |
|---|---|---|
| LB `s-1vcpu-2gb` SP1 | 12.00 | 60 |
| api-1 `s-2vcpu-4gb` SP1 | 24.00 | 120 |
| api-2 `s-2vcpu-4gb` SP1 | 24.00 | 120 |
| data `s-2vcpu-4gb` SP1 | 24.00 | 120 |
| Cloudflare Pages | 0.00 | 0 |
| Cloudflare R2 (10 GB free + esperado <50 GB) | 0.50 | 3 |
| Backups DO snapshots | 1.20 | 6 |
| **Total Fase 5** | **85.70** | **428** |

### 9.2 Cenário B — Hetzner EU (custo mínimo)

| Item | Custo (€/mês) | R$ aprox. |
|---|---|---|
| LB CPX11 | 3.79 | 21 |
| api-1 CPX21 | 7.05 | 39 |
| api-2 CPX21 | 7.05 | 39 |
| data CX22 | 5.79 | 32 |
| Cloudflare Pages | 0.00 | 0 |
| Cloudflare R2 | 0.50 | 3 |
| Backups Hetzner | 0.00 (via R2) | 0 |
| **Total Fase 5** | **24.18** | **134** |

### 9.3 Comparação com atual

| Cenário | Custo R$/mês | Capacidade | SPOF |
|---|---|---|---|
| Atual (HostGator) | ~50 | 1 vCPU | 8 |
| Fase 5 — Cenário A | ~428 | 6 vCPU + redundância | 2 (LB, data) |
| Fase 5 — Cenário B | ~134 | 9 vCPU + redundância | 2 (LB, data) |

**Critério decisão A vs B:** se MRR projetado < R$ 1.500 nos primeiros 6 meses, Cenário B; senão A.

---

## 10. Riscos e mitigação

| # | Risco | Prob | Impacto | Mitigação | Dono |
|---|---|---|---|---|---|
| 1 | Migração Postgres corrompe ou perde linhas | Baixa | Alto | Backup pré + comparar `count(*)` por tabela; rollback restaurando volume original | Daniel |
| 2 | InfluxDB restore inflama disco (>40 GB) | Baixa | Médio | Validar tamanho com `du` antes; provisionar VPS data com 80 GB SSD | Daniel |
| 3 | DNS cutover demora >5 min CF | Muito Baixa | Médio | TTL CF 5 min; comunicar manutenção; testar com `dig` antes | Daniel |
| 4 | `ip_hash` quebra session pra mobile NAT | Média | Médio | Monitorar reconnect rate; pular pra Redis adapter se >5% | Daniel |
| 5 | Self-hosted runner em VPS LB compromete LB | Baixa | Alto | Runner roda em container isolado; secrets via env, não disk; alertar acesso anômalo | Daniel |
| 6 | Origin Cert vence (2041) ou rotação manual perdida | Baixa | Alto | Cron `at` pra avisar 90 dias antes; documentar em `dsplayground-infra/docs/cert-rotation.md` | Daniel |
| 7 | Custo dispara antes de receita chegar | Média | Médio | Cenário B como fallback; downgrade VPS specs se MRR < custo em 3 meses | Daniel |
| 8 | CF Pages outage longo derrubando landing | Baixa | Médio | Aceitar (CF é mais confiável que self-host); como fallback opcional, manter container nginx servindo `dist` (sem deploy ativo) | Daniel |
| 9 | Build do landing falha por GitHub Packages auth | Média | Baixo | NODE_AUTH_TOKEN com expiry monitorado; rotacionar a cada 6 meses | Daniel |
| 10 | Volume `backend_keys` corrompe = JWTs invalidados | Baixa | Alto | Backup encriptado em R2 + cópia em cada api-N; rotation procedure documentada | Daniel |
| 11 | api-N não consegue conectar VPC privada na DO | Baixa | Alto | Validar conectividade via Ansible health task antes de promover ao LB | Daniel |
| 12 | CrowdSec migração perde decisões existentes | Baixa | Baixo | Export `cscli decisions list -o json` antes; import depois | Daniel |

---

## 11. Cronograma sugerido (semanas)

```
Semana  1   2   3   4   5   6   7   8   9  10  11  12
        │   │   │   │   │   │   │   │   │   │   │   │
F0:     ████████                                          Split de repos + CI por repo
F1:         ████████                                      Estáticos pro CDN
F2:                 ████████████                          VPS data + migração DBs
F3:                             ████████                  VPS LB + api-1
F4:                                     ████████          api-2 + sticky validado
F5:                                             ████████  Terraform module + docs
                                                          
Marcos:    │   │       │       │       │           │
           │   │       │       │       │           ▲ auto-scale validado <15min
           │   │       │       │       ▲ 2 nós produção, sticky OK
           │   │       │       ▲ LB ativo, api-1 servindo
           │   │       ▲ DB isolado na VPS data
           │   ▲ estáticos no CDN, browser nunca mais bate na origem
           ▲ 4 repos prontos com CI verde
```

---

## 12. Apêndices

### A. Comandos críticos (snippets prontos)

**Provisionar nó api-N novo:**
```bash
cd dsplayground-infra/terraform
terraform apply -var="api_node_count=3" -auto-approve
ansible-playbook -i inventory.ini playbook.yml -l api-3 --tags api-node
ssh deploy@vps-lb "ansible-playbook -i inventory.ini lb.yml --tags upstream-reload"
curl https://api.dsplayground.com.br/health/app  # deve voltar 200
```

**Drain + deploy de 1 nó:**
```bash
ssh deploy@vps-lb "
  sed -i 's/server 10.0.1.10:5000.*/server 10.0.1.10:5000 down;/' /etc/nginx/conf.d/upstream.conf
  nginx -s reload
"
sleep 30  # drena conexões existentes
ssh deploy@api-1 "docker pull ghcr.io/.../api:latest && docker compose up -d --no-deps backend"
ssh deploy@api-1 "for i in 1 2 3; do curl -fsS http://localhost:5000/health/app && exit 0; sleep 2; done; exit 1"
ssh deploy@vps-lb "
  sed -i 's/server 10.0.1.10:5000 down;/server 10.0.1.10:5000 max_fails=2 fail_timeout=30s;/' /etc/nginx/conf.d/upstream.conf
  nginx -s reload
"
```

**Backup manual completo (dry-run de DR):**
```bash
ssh deploy@vps-data "
  docker exec data-postgres pg_dumpall -U portifolio | gzip > /tmp/pg-$(date +%F).sql.gz
  docker exec data-influxdb influx backup /tmp/influx-$(date +%F)
  tar czf /tmp/influx-$(date +%F).tar.gz -C /tmp influx-$(date +%F)
"
scp deploy@vps-data:/tmp/{pg,influx}-*.{sql.gz,tar.gz} ./local-backup/
wrangler r2 object put backups/dr-$(date +%F)/ --file ./local-backup/
```

**Rollback rápido pra SHA anterior:**
```bash
PREV=$(gh release list -R danpqdan/dsplayground-api --limit 2 | tail -1 | awk '{print $1}')
for node in api-1 api-2; do
  ssh deploy@$node "docker pull ghcr.io/.../api:$PREV && docker tag .../api:$PREV .../api:latest && docker compose up -d --no-deps backend"
done
```

### B. Variáveis Ansible novas

Adicionar em `dsplayground-infra/ansible/group_vars/all.yml`:

```yaml
# === Topologia ===
api_nodes:
  - { name: api-1, private_ip: 10.0.1.10 }
  - { name: api-2, private_ip: 10.0.1.11 }

vps_data_private_ip: 10.0.0.20
vps_lb_private_ip: 10.0.0.10

# === Registry (deploy via pull) ===
registry_image_api: ghcr.io/danpqdan/dsplayground-api
registry_pull_token: !vault |
  $ANSIBLE_VAULT;1.1;AES256
  ...  # PAT GitHub com read:packages

# === Backups R2 ===
r2_account_id: !vault | ...
r2_access_key: !vault | ...
r2_secret_key: !vault | ...
r2_bucket: dsplayground-backups

# === age (criptografia de backend_keys) ===
age_recipient: age1...  # publica
age_identity: !vault | ...  # privada (decrypt no boot da api-N)

# === Cloudflare ===
cf_zone_id: !vault | ...
cf_api_token: !vault | ...  # com permissão DNS edit + Pages deploy
```

### C. Decisões adiadas (gatilhos pra reabrir)

| Decisão | Adiar até... |
|---|---|
| **Redis adapter pro Socket.IO** | Reconnect rate >5% OU >2 nós permanentes |
| **Postgres replica leitura** | p95 query > 500ms por 1h sustentado |
| **InfluxDB Cloud (paid)** | Volume > 30 GB OU ingest > 5k pts/s OU primeiro cliente Pro |
| **Cloudflare Load Balancer** ($5/mês) | Multi-região (>1 datacenter) OU LB self-hosted CPU > 70% |
| **mTLS LB↔API** | Múltiplos provedores OU >3 nós OU compliance exigir |
| **Loki centralizado pra logs** | Volume > 1 GB/dia OU >3 hosts |
| **OpenTelemetry tracing** | Bug de produção que `grep` em log não resolve |
| **Auto-scaling real (não manual)** | Picos previsíveis (ex: campanhas) que justifiquem |
| **Migração pra Hetzner** (se Cenário A) | MRR < R$ 1.500 em 6 meses |
| **Kubernetes** | >10 nodes (ainda assim avaliar — pode ser lock-in desnecessário) |

---

## Fontes de verdade após esta migração

- **Estado atual operacional**: `docs/PROJETO.md` (atualizar §2 Arquitetura quando Fase 5 fechar)
- **Recovery procedures**: `ark/docs/dashboard-cliente.md` §22 (atualizar com novos hosts/volumes)
- **Comandos por dia-a-dia**: `CLAUDE.md` (substituir `/opt/portifolio` por mapa multi-host)
- **Este doc**: histórico do caminho — não atualizar pós-Fase 5; congela como "como chegamos aqui"

---

## Manutenção deste doc

Atualizar **só** durante a execução das fases. Pós-Fase 5, este doc vira histórico e a operação corrente migra pros docs canônicos acima. Não duplicar.
