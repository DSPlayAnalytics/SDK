# Changelog

Todas as mudancas significativas deste pacote sao registradas aqui. Segue [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/) e [SemVer](https://semver.org/lang/pt-BR/).

## [Unreleased]

## [0.1.0] - 2026-04-28

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
