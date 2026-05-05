# Contas, acessos e infra do produto

> Snapshot em **2026-04-30**. Inventário do que existe, o que falta, e
> procedimento de recovery. Atualizar a cada mudança de credencial ou conta.
>
> **Princípio:** segredo nunca vai pro git. Tudo aqui é metadado (provedor,
> escopo, dono, onde está armazenado). Valores reais vivem em vault offline
> (1Password / Bitwarden / age key) ou em variáveis de ambiente.

---

## 1. Inventário de provedores ativos

| Provedor | Conta / login | Função | 2FA? | Pagamento | Quem tem acesso |
|---|---|---|---|---|---|
| **GitHub** | `danpqdan` | Repos: `portifolio`, `comercial`, `dsplayground-analytics-sdk`; Container Registry; Actions self-hosted runner | ❓ verificar | n/a | só Daniel |
| **Cloudflare** | `Danieltisantos@gmail.com` | DNS proxy, Origin Cert (válido até 2041), Pages project `comercial` | ❓ verificar | ❓ cartão pessoal | só Daniel |
| **HostGator** | ❓ login não documentado | VPS produção (Rocky 9.7, IP único) | ❓ | ❓ cartão pessoal | só Daniel |
| **Registrador `dsplayground.com.br`** | ❓ desconhecido (Registro.br? GoDaddy? outro?) | Domínio | ❓ | ❓ | só Daniel |
| **Email do produto** (`contato@dsplayground.com.br`) | **NÃO EXISTE AINDA** | Receber contato comercial / Business plan | n/a | n/a | — |
| **Email transacional (Resend / SES / Postmark)** | **NÃO EXISTE AINDA** | Magic-link, welcome, alerts de quota/cardinalidade | n/a | n/a | — |
| **Billing/payments** (Stripe / MercadoPago) | **NÃO EXISTE AINDA** | Upgrade de plano free→pro→business | n/a | n/a | — |
| **Conta empresa / CNPJ** | ❓ pessoa física ou PJ? | Emissão de NF, separação de despesas | n/a | n/a | só Daniel |

**Pra preencher:** os campos `❓` precisam confirmação e os "NÃO EXISTE AINDA" são pendências priorizadas no `docs/PROJETO.md` §10.

---

## 2. Tokens e segredos em uso

Lista de tokens **vivos** (e onde devem viver). Valor real **NUNCA** neste arquivo.

| Token | Função | Onde mora hoje | Escopo / TTL | Rotação | Status |
|---|---|---|---|---|---|
| `gh auth token` (PAT amplo) | Operação local + scripts | Keyring do `gh CLI` | `admin:enterprise, admin:org, repo, workflow, ...` (escopo gigante) | Quando vazar | 🔴 **VAZADO em 2026-04-29** (chat) — rotacionar |
| `NODE_AUTH_TOKEN` (CF Pages) | `npm ci` baixar `@danpqdan/dsplayground-analytics-sdk` do GitHub Packages durante build CF | CF Pages secret (projeto `comercial`) | Atualmente o PAT amplo (mesmo vazado acima) | 90d | 🔴 substituir por PAT enxuto `read:packages` only |
| `NODE_AUTH_TOKEN` (Ansible) | Build do container `landing`/`frontend` na VPS | `/opt/portifolio/.env` (mode 0640) gerado pelo Ansible a partir de `group_vars/all.yml` | Mesmo PAT (mesmo problema) | 90d | 🟡 substituir junto |
| `INFLUXDB_TOKEN` (admin) | Backend escreve nos buckets + `provisionar_cliente.py` cria buckets/tokens | `group_vars/all.yml` (vault) → `.env` no host (0640) | admin do org `zen` | Anual ou em incidente | ✅ ok |
| `POSTGRES_PASSWORD` | Backend conecta no Postgres | mesmo lugar | scope DB `portifolio_auth` | Anual | ✅ ok |
| `flask_secret_key` | Flask sessions, signing | mesmo lugar | n/a (random 32 bytes) | Em incidente | ✅ ok |
| `admin_api_token` | Endpoints `/admin/analytics/sessao/*` (LGPD) | mesmo lugar | bearer custom | Anual | ✅ ok |
| `grafana_admin_password` | Login admin do Grafana | mesmo lugar | admin Grafana | Anual | ✅ ok |
| Cookie `cliente_session` (sessões humanas) | Auth dashboard cliente | Apenas browser do cliente; sha256-hash em Postgres `clientes_users_sessoes` | HttpOnly+Secure+SameSite=Strict, TTL 7d | n/a | ✅ ok |
| `sdk_jwt` (RS256) | SDK ingest | Memória do SDK (5min TTL); chave RSA em volume `backend_keys` | scope `["ingest"]` + `site_id` | RSA: rotaciona em incidente; JWT: 5min auto | ✅ ok |
| `publishable_key` (por site) | Cliente embute no JS pra trocar por JWT | Postgres `publishable_keys` | scope `["sdk-token-issue"]` | Cliente solicita (não implementado UX) | ⚠️ ainda sem UX no dashboard pro cliente ver/rotacionar |
| `RESEND_API_KEY` | Magic-link em prod | **NÃO CONFIGURADO** — em dev cai no stdout do container | n/a | n/a | 🔴 P1 — ver §3 |
| `CF_API_TOKEN` (auto-criado pelo CF Pages no setup) | Deploy automático do `comercial` | Cloudflare Pages secrets do projeto | Workers scripts edit + Routes edit | Anual | ✅ ok |
| `age` keypair pra backups (chaves RSA do `backend_keys`) | Restore após DR | **NÃO EXISTE AINDA** — backup hoje é só volume Docker no host | n/a | n/a | 🟡 P1 — backup offline |

---

## 3. Pendências de infra do produto

Comunicado em 2026-04-30: **zero infra para login UX, publish_key visível, email, esqueci-senha, upgrade de plano**. Backend de cadastro funciona; tudo que vem depois é gap.

### 3.1 Bloqueios de signup público

| # | Item | Severidade | Onde | Estimativa |
|---|---|---|---|---|
| **PG-1** | **Hostname pro dashboard do cliente** — quando CF Pages assumir apex, `/cliente/metricas/*` quebra (CF Pages é estático, não roteia pro Grafana via auth_request). Decidir entre: (a) `app.dsplayground.com.br` ou `dashboard.X` dedicado; (b) CF Pages Functions com fetch pro origin LB; (c) deixar landing fora do apex enquanto não decide | 🔴 P0 | nginx + DNS + Cloudflare | 1-2d (decidir) + 0.5d (implementar) |
| **PG-2** | **Email transacional** (Resend recomendado — free tier 100/dia, 3k/mês). Sem isso magic-link cai no stdout do container = "esqueci senha" totalmente quebrado em prod | 🔴 P1 | `group_vars/all.yml` + `email_sender.py` (já tem stub) | 0.5d |
| **PG-3** | **Email do produto `contato@dsplayground.com.br`** — landing em `precos.astro` referencia. Opções: (a) Cloudflare Email Routing → forward pro Gmail (free); (b) Google Workspace ($6/user/mês); (c) Zoho Mail (free 5 users). | 🟡 P1 | Cloudflare/registrador | 1-2h |
| **PG-4** | **Dashboard de Settings do cliente** — UX pro cliente ver: publishable_key (com botão copiar), trocar senha/email, ver plano atual, ver consumo do dia/mês, baixar export LGPD. Hoje cliente cadastra mas só vê Grafana | 🟡 P1 | new pages no `comercial` repo + endpoints REST autenticados | 3-5d |
| **PG-5** | **Recover password UX** — magic-link já tem endpoint `/cliente/auth/magic-link/{solicitar,verificar}` mas falta tela `/cliente/esqueci-senha` no landing | 🟡 P1 | `comercial` repo (Astro page) | 0.5d (depende de PG-2) |
| **PG-6** | **Upgrade de plano** — billing integration. Stripe (paid) ou MercadoPago (BR). Rotina: cliente seleciona plano → checkout → webhook backend → atualiza `sites.plano` + `quotas`. | 🟢 P2 | new module `backend/billing/` + integração + webhook | 5-7d |
| **PG-7** | **Conta empresa/CNPJ** — emitir NF pra primeiro cliente pago. Opções: PJ MEI (free) / ME / SLU. Decisão tributária. | 🟡 P1 antes do primeiro cliente | externo (contador) | varia |

### 3.2 Hardening de contas (urgente)

| # | Item | Severidade | Ação |
|---|---|---|---|
| **HS-1** | Verificar **2FA habilitado** em GitHub e Cloudflare (idealmente hardware key — YubiKey ~R$300 unidade) | 🔴 P0 | painel de cada provedor |
| **HS-2** | Salvar **recovery codes** offline (não em browser/cloud sync) | 🔴 P0 | papel + cofre, ou age-encrypted offline file |
| **HS-3** | **Rotacionar PAT amplo** `ghp_TjbESMOV7vi...` (vazou em chat 2026-04-29) | 🔴 P0 | https://github.com/settings/tokens — revogar + emitir novo |
| **HS-4** | **Criar PAT enxuto** com só `read:packages` pra usar em CF Pages e Ansible (substituir o amplo) | 🔴 P0 | https://github.com/settings/tokens/new?scopes=read:packages |
| **HS-5** | **Billing alert** em Cloudflare e HostGator — notifica se gasto subir além do esperado | 🟡 P1 | painel de cada provedor |
| **HS-6** | **Backup offline de credenciais** — vault Ansible (`/.vault-password`), age key dos backups, recovery codes. 1Password Family ($5/mês) ou Bitwarden Premium ($10/ano) ou local file age-encrypted em pen drive | 🟡 P1 | escolher provider |

---

## 4. Procedimentos de recovery

### 4.1 Perdi acesso ao GitHub

1. Recovery codes (salvos em §HS-2) → usar pra recuperar 2FA
2. Sem recovery codes: contato `support.github.com` com prova de identidade (foto do RG + selfie) — pode demorar dias
3. Repos críticos (`portifolio`, `comercial`) têm cópias locais? Sim — clones em `D:/portifolio/` e `D:/comercial-tmp/`. SDK em outro repo separado.
4. **Mitigação preventiva**: Daniel deveria configurar segundo dispositivo de 2FA (YubiKey + TOTP em 2 dispositivos diferentes).

### 4.2 Perdi acesso à Cloudflare

1. Recovery codes
2. Sem: support.cloudflare.com — verificação por email da conta
3. Origin Cert atual (`/etc/ssl/cloudflare-origin/`) continua funcionando até vencer (2041) mesmo se conta CF cair, MAS sem painel CF não consegue mexer em DNS — DNS quebra → produto cai
4. **Mitigação preventiva**: ter conta secundária CF (gratuita) com mesmo domínio mas como Member da org principal — segundo ponto de acesso

### 4.3 PAT GitHub vazou

1. https://github.com/settings/tokens → revogar imediatamente
2. Auditar uso recente: https://github.com/settings/security-log → buscar atividade suspeita
3. Se foi usado: rotacionar tudo que dependia (NODE_AUTH_TOKEN no CF Pages, Ansible vault, env do runner)

### 4.4 VPS HostGator comprometida

Procedimento completo em `ark/docs/dashboard-cliente.md` §22 (cenários A-E). Resumo:
- Restaurar volumes Docker do backup
- Provisionar VPS nova (HostGator panel ou novo provedor)
- Re-aplicar Ansible
- Migrar DNS Cloudflare pro novo IP

### 4.5 Backups precisam de recovery

- Postgres: `pg_dump` diário (pendente automatizar — hoje manual)
- InfluxDB: `influx backup` (idem)
- `backend_keys` (RSA do JWT): hoje só no volume Docker — sem backup remoto. **Pendência crítica** (pendência §HS-6).

---

## 5. Checklist de hardening (revisar trimestralmente)

- [ ] 2FA habilitado em GitHub, Cloudflare, registrador, Google
- [ ] Hardware key (YubiKey ou similar) como segundo fator
- [ ] Recovery codes salvos offline (papel ou age-encrypted)
- [ ] PAT amplo rotacionado e PAT enxuto (`read:packages`) em uso
- [ ] Billing alerts em todos provedores
- [ ] Backup offline do vault Ansible (`/.vault-password`)
- [ ] Backup offline da age key (quando existir)
- [ ] DNS protegido com DNSSEC (depende do registrador)
- [ ] Cloudflare account com pelo menos 2 admin (acesso secundário)
- [ ] Domínio com auto-renew ativo (registrador)
- [ ] Cartão de pagamento dos provedores com data de validade > 12m
- [ ] Email do `Danieltisantos@gmail.com` com 2FA (todas as recovery dependem dele)

---

## 6. Manutenção deste doc

- **Sempre atualizar** quando: criar/revogar token, mudar provedor, adicionar/remover usuário, configurar email novo, pagar plano novo
- **Nunca commitar** valores reais de tokens — apenas metadata (escopo, dono, validade)
- Ponteiro neste doc é a **única referência** que o código deve fazer pra credenciais (caminho do vault, nome da env var)
