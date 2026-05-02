# Changelog

Todas as mudancas significativas deste pacote sao registradas aqui. Segue [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/) e [SemVer](https://semver.org/lang/pt-BR/).

## [Unreleased]

## [0.4.0] - 2026-05-01

### Added
- `identify(userId, traits?)` — associa eventos subsequentes a um user; emite
  `__identify`; retorna `false` se userId vazio/whitespace.
- `group(groupId, traits?)` — agrupa user em organização (B2B); emite `__group`.
- `reset()` — logout / LGPD "esquecer tudo": apaga userId + groupId, regenera
  anonId, emite `__reset`.
- `UserStore` — persiste userId/groupId/anonId em localStorage com fallback em
  memória; resistente a `QuotaExceededError`. Exportado como singleton `userStore`.
- `iniciarAnalytics` aceita `userId?` e `groupId?` para hidratação SSR.
- Envelopes `analytics_data` incluem `user_id`/`group_id` quando definidos;
  campos omitidos quando não setados (sem `null` literal).
- `trackPurchase(value, currency, metadata?)` → evento `__purchase`.
- `trackSignup(plan, metadata?)` → evento `__signup`.
- `trackConversion(type, value?, metadata?)` → evento `__conversion`.
- Todos os helpers comerciais sanitizam metadata (apenas primitivos).
- `schema_version` `1.1` → `1.2` (backend aceita >= 1.0).

### Security
- Traits e metadata dos helpers comerciais viajam apenas no payload do evento —
  nunca persistem em storage local (política anti-PII).

### Breaking changes
- Nenhum. API existente preservada; novos campos são opt-in.

## [0.4.0-rc.2] - 2026-05-01

### Added
- `trackPurchase(value, currency, metadata?)` — registra compra/transação; emite
  `__purchase` com `value` (>= 0, finito) e `currency` (ISO 4217, ex.: "BRL").
- `trackSignup(plan, metadata?)` — registra cadastro; emite `__signup` com `plan`.
- `trackConversion(type, value?, metadata?)` — conversão genérica; emite `__conversion`
  com `type` e `value` opcionais. Retorna `false` se `value` for fornecido mas não-finito.
- Todos os helpers sanitizam `metadata` (só primitivos, descarta objetos/arrays/funções).
- Backend roteia eventos `__purchase`/`__signup`/`__conversion` para measurement
  `conversion_events` no InfluxDB (requer backend-2, PR #XX em portifolio).

## [0.4.0-rc.1] - 2026-05-01

### Added
- `identify(userId, traits?)` — associa eventos subsequentes a um user; emite
  evento interno `__identify`; retorna `false` se userId vazio/whitespace.
- `group(groupId, traits?)` — agrupa user em organizacao (B2B); emite `__group`.
- `reset()` — logout / "esquecer tudo" LGPD: apaga userId + groupId, regenera
  anonId, emite `__reset`.
- `UserStore` — persiste userId/groupId/anonId em localStorage com fallback
  em memoria; resistente a `QuotaExceededError`; exportado como singleton
  `userStore`.
- `iniciarAnalytics` aceita `userId?` e `groupId?` para hidratacao SSR antes
  da primeira conexao WebSocket.
- Envelopes `analytics_data` passam a incluir `user_id` e `group_id` quando
  definidos no `userStore` (campos omitidos se nao setados — sem `null` literal).
- `schema_version` bumped de `1.1` → `1.2` (compativel com backend schema 1.2;
  backend aceita clientes >= 1.0).

### Security
- Traits passam so no payload do evento, **nunca** persistem em storage local
  (politica anti-PII documentada em README v0.4).
- `sanitizarTraits` filtra tipos nao-primitivos (objetos, arrays, funcoes)
  para prevenir envio acidental de DOM nodes ou closures.

## [0.3.2] - 2026-05-01

### Security
- Bump `uuid` `^13.0.0` → `^14.0.0` corrige
  [GHSA-w5hq-g745-h8pq](https://github.com/advisories/GHSA-w5hq-g745-h8pq)
  (moderate — buffer bounds check em `v3/v5/v6` quando `buf` e' provido).
  SDK so usa `v4()` (nao afetada na pratica), mas `npm audit` agora retorna
  zero. Pre-requisito pra abrir o repo publico — `npm audit` em CI publico
  vai gerar PR/badge automatico.

### Internal
- Sem mudanca em API publica. ESM/CJS/UMD bundles inalterados em forma; so
  o uuid embedado no UMD vem da v14 (sub-bytes diferentes mas mesmo
  comportamento de `v4()`).

## [0.3.1] - 2026-05-01

### Fixed
- `HeatmapUtils.empilharEventoNoAtivo` agora enfileira eventos quando nao ha
  pagina ativa (`bufferAtivo === null`) e drena no primeiro `iniciar()`. Antes
  retornava `false` silenciosamente, perdendo todo evento disparado antes do
  controller mount: web vitals iniciais (LCP candidato, CLS de primeiros layout
  shifts) e `enviarEvento` chamado no module-load (ex.: `app_carregado`).

### Why
Em apps que registram analytics no top-level (`App.jsx` chamando
`iniciarAnalytics` antes de qualquer route mount), `iniciarWebVitals` registra
listeners de `web-vitals` antes de existir HeatmapUtils ativo. Resultado em
prod: dashboards Event Explorer e Web Vitals empty mesmo com `page_analytics`
funcionando, porque so eventos pos-iniciar chegavam ao `_eventos`.

Buffer cap em 100 eventos descartando os mais novos preserva o early signal
e evita memory leak se nenhum controller jamais ativar (ex.: SSR-only build
ou erro de boot do React). `resetarRegistro` zera o buffer pra nao vazar
entre testes.

### Changed
- Contrato de `enviarEvento(nome, props)` em pagina nao-ativa: agora retorna
  `true` (enfileirado) em vez de `false` (perdido). Tests existentes ajustados
  em `tests/eventosCustomizados.test.ts`.

## [0.3.0] - 2026-04-29

### BREAKING CHANGE
- Socket.IO path mudou de `/api/socket.io/` para `/socket.io/`. Esta versao
  do SDK so funciona com backend portifolio que tenha removido o prefixo
  `/api/` dos blueprints (commit que casa: ver `ark/docs/api-prefix-redundancia.md`).
  Em prod, atualizar nginx + backend ANTES de bumpar SDK.

### Changed
- `src/WebSocketService.tsx`: path do Socket.IO sem `/api/` (alinha com a
  decisao de manter so o subdominio `api.X` como prefixo, sem duplicar no path).

### Why
Antes o SDK montava `https://api.dsplayground.com.br/api/socket.io/` —
o `api.` do subdominio + `/api/` do path eram redundantes. Pior: a chamada
de `/auth/sdk-token` (sem `/api/`) batia 404 em prod porque o backend tinha
prefixo. Agora o backend e canonico (sem `/api/`); apex strippa via nginx.

## [0.2.0] - 2026-04-29

### Added
- Bundle IIFE standalone em `dist/sdk.umd.js` (~80 KB minificado, ~24 KB gzip)
  com socket.io-client, web-vitals e uuid inline. Expõe namespace global
  `window.AnalyticsSDK`. Permite uso em sites HTML estaticos (Webflow,
  blogs, paginas de marketing) sem build pipeline. Ver secao
  "Standalone via `<script>`" no README.
- Badges de CI + Publish no topo do README (verdes apos cada workflow run).

### Changed
- `npm run build` agora roda `build:lib` + `build:umd` em sequencia.
- Smoke test (`scripts/smoke-bundle.mjs`) confere artefato UMD adicional
  e a presenca do simbolo `AnalyticsSDK` no bundle.

## [0.1.0] - 2026-04-28

Publicado em GitHub Packages (`https://npm.pkg.github.com`) sob escopo
`@danpqdan` — repo `dsplayground-analytics-sdk` permanece privado durante
fase alpha. Migrar pra npm publico (`@dsplayground/...`) quando passar
de alpha + criar org `dsplayground` no npmjs.com.

### Added
- Extracao do `frontend/src/sdk/` do monorepo `portifolio` para repositorio independente.
- Build via Vite library mode (`vite.config.js`): ESM + CJS + `.d.ts`.
- 19 unit tests (Vitest + jsdom): HeatmapUtils, WebSocketService, eventosCustomizados,
  filaAnalytics, iniciarAnalytics, webVitals, util, DiagnosticoColecaoTemporal +
  10 normalizadores (clique, custom, exposicao, hover, mouseMove, pageExit,
  pageView, scroll, toque, webVital).
- Auth via publishable_key trocada por sdk_jwt no endpoint `/auth/sdk-token` do backend
  (schema 1.1, ver `docs/plano-garantias-sdk-backend.md` no repo `portifolio`).
- 3 storages para fila offline: memoria, localStorage, IndexedDB (selecao automatica).
- Web Vitals via lib `web-vitals@^4` com `reportAllChanges: true` (ver `webVitals.ts`).

### Compatibility
- `SDK_SCHEMA_VERSION = '1.1'`. Backend `portifolio-backend` retorna `426 Upgrade Required`
  quando recebe schema fora do range suportado.
