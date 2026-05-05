# Contribuindo

Obrigado pelo interesse. Este SDK esta em fase **alpha** publicada em
GitHub Packages — API e schema podem mudar entre `0.x.y` minors. Mesmo
assim, queremos qualidade de coisa madura: 89 testes unitarios passando,
zero CVE high+ em deps de prod, lint sem warning.

## Sumario

- [Sumario](#sumario)
- [Setup](#setup)
- [Test-Driven Development (obrigatorio)](#test-driven-development-obrigatorio)
- [Pre-commit hooks](#pre-commit-hooks)
- [Estilo de codigo](#estilo-de-codigo)
- [Conventional Commits (pt-BR)](#conventional-commits-pt-br)
- [SemVer e mudancas que bumpam schema](#semver-e-mudancas-que-bumpam-schema)
- [Pull request](#pull-request)
- [Reporting de seguranca](#reporting-de-seguranca)

## Setup

Pre-requisitos:

- Node.js >= 20
- npm >= 10 (vem com Node 20)
- (recomendado) [`gitleaks`](https://github.com/gitleaks/gitleaks#installing) instalado localmente

```bash
git clone https://github.com/danpqdan/dsplayground-analytics-sdk.git
cd dsplayground-analytics-sdk
npm install      # instala deps + ativa husky pre-commit hooks
npm test         # 89 testes Vitest, deve passar antes de qualquer mudanca
npm run lint     # tsc --noEmit
npm run build    # ESM + CJS + UMD em dist/
```

## Test-Driven Development (obrigatorio)

**Escreva o teste primeiro.** Esta regra nao e negociavel para mudancas
em logica de coleta, normalizadores ou contrato de wire (`schema-eventos.md`).
Bug fix? Reproduz num teste vermelho antes de tocar o codigo. Feature
nova? Comeca por um teste que descreve o comportamento desejado.

Por que: bugs aqui escapam pra prod e contaminam dashboards de cliente,
que e impossivel de re-coletar. Testes evitam regressao silenciosa em
borderline (ex.: page_view sem dados, mouse_move sem amostragem,
scroll_depth duplicado).

Estrutura de testes:

- `tests/<nome>.test.ts` — unit tests por modulo (Vitest + jsdom)
- Cada normalizador em `src/normalizadores/` tem teste correspondente
  em `tests/normalizar*.test.ts`
- Use `vi.useFakeTimers()` para tempo deterministico (ver
  `tests/eventosCustomizados.test.ts`)

Pattern aceito (red → green → refactor):

```bash
# 1. red — escreve teste, roda, falha
npm run test:watch

# 2. green — implementa o minimo pro teste passar
# 3. refactor — limpa sem mudar comportamento; testes continuam verdes
```

PRs sem testes para nova logica sao rejeitados. Documentacao e mudanca
em config (lint, build, ci.yml) estao isentas.

## Pre-commit hooks

Husky roda apos `npm install`. Tres camadas em ordem custo-crescente:

| Camada | O que checa | Como pular (com critério) |
|---|---|---|
| `lint-staged` | `tsc --noEmit` no projeto inteiro (respeitando tsconfig.json) | corrige erros TS |
| `gitleaks protect` | secrets em arquivos staged (regras default + custom em `.gitleaks.toml`) | `git commit --no-verify` se ja conferiu |
| `npm audit --audit-level=high` | CVE high+ em deps de prod | `npm audit fix`, ou `--no-verify` em emergencia |

`gitleaks` precisa estar instalado localmente. Sem ele, o pre-commit
avisa e segue — **CI ainda roda gitleaks no PR**, entao nada vai pra
`main` sem passar.

`--no-verify` so em commit emergencial. Se voce usou, mencione no PR
description (ex.: "rodei `--no-verify` porque audit pegou CVE em
devDependency, ja patcheado em PR separado").

## Estilo de codigo

- **TypeScript strict-ish**: `tsconfig.json` tem `strict: false` por
  legado, mas escrita nova deve ser type-safe (sem `any` salvo em
  fronteira de DOM API).
- **Sem comentarios obvios**. Codigo bem nomeado nao precisa de
  comentario explicando o que. So o **porque** quando nao-obvio
  (constraint escondido, workaround pra bug especifico, invariante).
- **Imports relativos** com extensao `.ts` (`./util/obterElementoId.ts`),
  sao required pelo `allowImportingTsExtensions`.
- **Pt-BR em identificadores de dominio** (`empilharEvento`, `bufferAtivo`,
  `iniciarColecaoTempoReal`). Termos tecnicos universais ficam em ingles
  (`HeatmapUtils`, `WebSocketService`, `connect`, `disconnect`).
- **Sem emojis em codigo, comentarios ou docs** salvo se o usuario
  pediu explicitamente.

## Conventional Commits (pt-BR)

Formato:

```
<tipo>(<escopo>): <descricao no imperativo, em pt-BR, ate 72 chars>

[corpo opcional explicando o porque, nao o que]

[footers opcionais — closes #N, BREAKING CHANGE, etc]
```

Tipos aceitos:

- `feat` — nova funcionalidade
- `fix` — bug fix
- `docs` — apenas docs (README, CONTRIBUTING, docs/)
- `refactor` — mudanca interna sem alterar comportamento
- `test` — adicao/correcao de testes
- `chore` — config, build, deps, lint
- `perf` — melhoria de performance comprovada por benchmark
- `ci` — workflow GitHub Actions

Escopos comuns: `heatmap`, `socket`, `auth`, `fila`, `web-vitals`,
`custom-events`, `examples`, `build`.

Exemplos:

```
fix(heatmap): drena buffer pre-iniciar no primeiro iniciar()
docs(examples): adiciona exemplo React + secao CSP/iframe no README
test(normalizadores): cobre caso de target null em normalizarClique
chore(deps): bump uuid 13.0.0 -> 14.0.0 (CVE GHSA-w5hq-g745-h8pq)
```

**Nao adicionar trailer `Co-Authored-By: Claude`** — preferencia de
manutencao, history fica mais limpo sem.

Breaking changes:

```
feat(socket)!: muda path Socket.IO de /api/socket.io/ pra /socket.io/

BREAKING CHANGE: SDK >= 0.3 so funciona com backend portifolio que
removeu o prefixo /api/ dos blueprints. Atualizar nginx + backend
ANTES de bumpar SDK em prod.
```

## SemVer e mudancas que bumpam schema

Em fase alpha (`0.x.y`):

- **`0.x.0`** (minor) — feature nova, fix com mudanca observavel,
  breaking change em API publica (sim, em alpha breaking pode ir em minor).
- **`0.x.y`** (patch) — bugfix sem mudanca de contrato, docs, build,
  deps que nao mudam comportamento publico.

Quando bumpar `SDK_SCHEMA_VERSION` (em `src/iniciarAnalytics.ts`):

- **Major schema** (`1.x` → `2.0`): remocao/renomeacao de campo obrigatorio,
  mudanca de tipo, novo `tipo` de evento que o backend ainda nao persiste.
  Coordenar com merge no backend antes — backend precisa subir
  `min_client_schema` e `max_client_schema` simultaneamente.
- **Minor schema** (`1.1` → `1.2`): campo opcional novo, novo enum-value
  com fallback, endurecimento que nao quebra clientes conformes.

Quando passar de alpha (`0.x` → `1.0`), publicar em npmjs.org publico
sob escopo `@dsplayground` (criar org primeiro). Documentar em
[CHANGELOG.md](./CHANGELOG.md) com link pra issue/PR.

## Pull request

1. Branch a partir de `main`: `git checkout -b feat/<descricao-curta>`
2. Commits Conventional. Pre-commit deve passar (verde local).
3. Testes verdes: `npm test`. Se mexeu em normalizador ou wire format,
   atualize [`docs/schema-eventos.md`](./docs/schema-eventos.md).
4. Atualize [`CHANGELOG.md`](./CHANGELOG.md) na secao `[Unreleased]`.
   Bump de versao (`package.json`) so quando for releasar — em PR de
   feature, deixar pra release branch.
5. Push e abre PR. Template:

```markdown
## Summary

- O que mudou e por que (1-3 bullets)

## Test plan

- [ ] `npm run lint` passa
- [ ] `npm test` passa (ou novos testes adicionados)
- [ ] CI verde (gitleaks + audit + build-and-test)
```

CI roda automaticamente. Tres workflows:

- `secrets-scan` — gitleaks-action com `.gitleaks.toml`
- `audit` — `npm audit --audit-level=high --omit=dev`
- `build-and-test` — lint + test + build + smoke

Merge precisa de pelo menos `build-and-test` verde. Squash-merge e o
default — preserva history limpo no `main`.

## Reporting de seguranca

Vulnerabilidade no SDK ou no backend que ele consome? **Nao abra issue
publica.** Mande email pra `danieltisantos@gmail.com` com:

- Descricao da falha (idealmente com PoC reproduzivel)
- Versao afetada (`package.json` do SDK + commit hash do backend, se
  aplicavel)
- Impacto estimado (vazamento de dados? RCE? bypass de auth?)

Resposta em ate 72h. Se confirmado, abro CVE/advisory no GitHub Security
e te credito (a menos que prefira anonimo).
