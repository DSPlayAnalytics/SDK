# GitHub repo hardening — runbook P2

Endereca P2 da auditoria de seguranca 2026-05-02. Ate agora a `main` aceita
push direto, secret scanning nao foi confirmado, dependabot nao existia.

## Checklist (fazer no GitHub web)

Repositorio: https://github.com/danpqdan/portifolio

### 1. Branch protection na `main` 🔴 ESSENCIAL

`Settings > Branches > Branch protection rules > Add rule`

```
Branch name pattern: main

Require a pull request before merging:        ☑
  Require approvals:                          ☑  1 reviewer
  Dismiss stale pull request approvals
    when new commits are pushed:              ☑

Require status checks to pass before merging: ☑
  Require branches to be up to date:          ☑
  Status checks (digite e selecione):
    - compose-config        (ci.yml)
    - ansible-syntax        (ci.yml)
    - frontend              (ci.yml)
    - backend               (ci.yml)
    - prod-regression       (prod-regression.yml — se rodar em PR)

Require conversation resolution before merging: ☑

Do not allow bypassing the above settings:    ☐  (deixar OFF — admin pode
                                                 emergency push se precisar.
                                                 Trade-off conhecido)

Restrict who can push to matching branches:   ☐  (vazio = qualquer com write)
```

**Risco se nao fizer**: hoje qualquer commit em main aciona o CD direto.
Sem PR, sem review, sem CI verde garantido = risco de regredir mesmo
fixes recentes da auditoria.

### 2. Secret scanning + push protection 🔴 ESSENCIAL

`Settings > Code security and analysis`

```
Secret scanning:           Enable
Push protection:           Enable  (bloqueia push com secret detectado)
Validity checks:           Enable  (alerta se secret esta valido)
Non-provider patterns:     Enable  (custom regex, config opcional)
```

**Por que importa**: hoje, se voce ou um colaborador commitar uma chave
AWS/Stripe/JWT por engano, ela fica no historico publico (mesmo apos
deletar o commit — fica em refs/orphan). Push protection bloqueia ANTES
do push — voce reescreve sem leak.

### 3. Dependabot ✅ FEITO

`.github/dependabot.yml` adicionado neste commit. Cobre:
- pip (backend)
- npm (frontend, landing)
- docker (3 Dockerfiles)
- github-actions

Ativo a partir do proximo Monday 06:00 UTC. Para ver alertas existentes:
`Settings > Code security and analysis > Dependabot alerts: Enable`.

### 4. CodeQL (code scanning) 🟡 RECOMENDADO

`Security > Code scanning > Set up code scanning > Default`

GitHub adiciona workflow `.github/workflows/codeql.yml` automatico.
Linguagens detectadas: Python, JavaScript/TypeScript.

Custo: ~5min de CI por PR. Vale pra detectar XSS, SQL injection, hardcoded
creds que pip-audit nao pega.

### 5. Self-hosted runner: rever escopo 🟡 IMPORTANTE

`Settings > Actions > Runners`

Confirmar:
- Runner `production-vps` com label `production-vps` configurado.
- Runner em **`Repository`-level** (nao Organization), pra so este repo
  poder usar.
- **Repo e PRIVADO** (`Settings > General > Danger Zone > Change visibility`).
  Self-hosted runner em repo PUBLICO permite forks rodarem codigo
  arbitrario na sua VPS — risco enorme.

### 6. Environment "production" com required reviewer 🟡 RECOMENDADO

`Settings > Environments > New environment: production`

```
Required reviewers:        ☑  voce mesmo (ou time)
Wait timer:                0 min  (ou 5 min se quiser cooldown)
Deployment branches:       Selected branches: main
```

`deploy.yml` ja usa `environment: production` (verificado linha 31). Com
required reviewer, **CD pausa** apos CI verde e espera approval humano
pra disparar deploy. Trade-off: latencia +1-5min por deploy vs
proteca contra deploy malicioso/erro.

### 7. 2FA obrigatorio 🟡 IMPORTANTE

`Settings > Members > Require two-factor authentication`

Bloqueia colaboradores sem 2FA — protege chave comprometida do GitHub.

(Se for repo solo, voce mesmo precisa de 2FA na sua conta GitHub.)

### 8. Visibilidade do repo 🔴 VERIFICAR

`Settings > General > Danger Zone`

Status:
- **Privado**: ✅ OK pra self-hosted runner
- **Publico**: ❌ DESATIVAR self-hosted runner imediatamente (forks
  rodariam codigo na sua VPS)

CLAUDE.md ja avisa esse ponto (sec "Risco" no CI/CD). Confirmar.

## O que precisa de auth admin do GitHub

| Acao | Permissao |
|---|---|
| Branch protection | Repo admin |
| Secret scanning | Repo admin (Pro/Team plan ou repo publico) |
| Dependabot | Repo admin (Free plan inclui) |
| CodeQL | Repo admin (Free pra repo publico, paid pra privado de Org) |
| Environment + required reviewer | Repo admin |
| 2FA enforcement | Org admin (se Org); Account settings (se solo) |

## Custo

- Branch protection: gratuito
- Secret scanning: gratuito em repo publico, **pago em repo privado (GitHub Advanced Security)** — verificar plano
- Dependabot: gratuito
- CodeQL: gratuito em repo publico, **pago em privado (GitHub Advanced Security)**
- Environment required reviewer: gratuito (Free tier)
- 2FA: gratuito

**Se repo e privado e plano e Free**: secret scanning e CodeQL ficam
indisponiveis. Mitigacao: rodar `gitleaks` localmente em pre-commit hook
(grava de graca) + `pip-audit`/`npm audit` no CI (ja temos os comandos).

## Validacao pos-config

Apos aplicar 1-8:

1. Tentar push direto na main:
   ```bash
   git checkout main
   git commit --allow-empty -m "test push direto"
   git push origin main
   ```
   Esperado: rejeitado com "protected branch" (passo 1 OK).

2. Abrir PR de teste e checar:
   - CI rodou? (compose-config + ansible-syntax + frontend + backend)
   - Required reviewer apareceu?
   - Status checks bloqueando merge ate todos passarem?

3. Tentar commitar um fake secret pra testar push protection:
   ```bash
   echo "AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE" >> /tmp/leak.txt
   git add /tmp/leak.txt && git commit -m "test"
   git push
   ```
   Esperado: rejeitado com mensagem de secret scanner.

## Manutencao

- **Toda Monday**: revisar PRs do Dependabot. Aprovar minor/patch sem
  drama; majors com mais cuidado.
- **Mensal**: rever `Security > Dependabot alerts` e `Security > Code
  scanning alerts` (se CodeQL ativo).
- **Quando criar branch novo**: confirmar que branch protection na main
  ainda esta ativa.
