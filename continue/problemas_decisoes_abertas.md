# Problemas e Decisões em Aberto

## Resolvido nesta revisão

- `backend/config.py`, `backend/.env`, `backend/.env.example` e `backend/.env.production` foram ajustados para remover tokens reais e operar com variáveis de ambiente locais.
- `frontend/.env.production` foi alinhado ao uso local inicial, sem URL de produção.
- A documentação em `docs/` foi revisada para UTF-8.
- Vitest, React Testing Library, jsdom e setup de testes do frontend foram integrados.
- Comentários antigos com encoding incorreto foram removidos ou substituídos nos arquivos alterados.
- A cobertura inicial do frontend foi ampliada para fluxo de coleta de `HeatmapUtils`.
- `npm audit fix`, `npm update` e atualização de dependências diretas reduziram o audit do frontend para 0 vulnerabilidades.
- `docker-compose.yml` e Dockerfiles locais foram adicionados para execução em containers Linux.
- O Docker Compose foi validado via WSL com a distro Ubuntu.
- `frontend`, `backend` e InfluxDB subiram com `docker compose`.
- O frontend foi acessado localmente em `http://localhost:3000`.
- O backend foi acessado localmente em `http://localhost:5000`.
- O InfluxDB subiu e respondeu em `http://localhost:8086`, mas as credenciais do painel ainda não estão confirmadas.
- A correção de `Blueprint` em `backend/app.py` foi aplicada para funcionar também em `FLASK_ENV=development`.
- A cobertura inicial de `WebSocketService` foi adicionada com socket mockado.
- `docs/levantamento-sdk-analytics.md` foi expandido com contrato técnico proposto para o SDK de analytics.
- `HeatmapUtils` passou a aceitar páginas dinâmicas apenas via mapa `paginas`, sem chaves predefinidas no contrato de analytics.
- O backend passou a aceitar `paginas` dinâmicas no DTO, no resumo de resposta e na criação de métricas temporais.
- `backend/test_dados_dinamicos.py` cobre páginas dinâmicas no DTO e nas métricas temporais.
- O código reutilizável de analytics do frontend foi separado em `frontend/src/sdk`, com `index.ts` como ponto público.
- Foram adicionados fixture e testes sintéticos de analytics sem browser para validar o backend por Socket.IO.
- SDK passou a emitir *deltas por tick* (nao cumulativos). Cada emissao contem apenas eventos/segundos observados desde o ultimo commit; `parar()` descarrega o residuo final. Documentado em `docs/levantamento-sdk-analytics.md`. Cobertura em `frontend/src/testes/DiagnosticoColecaoTemporal.test.ts`.
- `iniciarAnalytics({ websocketUrl, appId, ambiente, debug?, intervaloEnvioMs? })` implementado em `frontend/src/sdk/iniciarAnalytics.ts`. Cada emissao agora carrega `app_id` e `ambiente` no envelope. SDK nao depende mais de `../config.js`; app consumidor injeta a config no boot (`App.jsx`). Cobertura em `frontend/src/testes/iniciarAnalytics.test.ts` e `WebSocketService.test.ts`.
- Camada de normalizacao implementada em `frontend/src/sdk/normalizadores/` (10 normalizadores puros, 1 teste por modulo). Contrato passou a `paginas[pageId][0].eventos: [{ tipo, timestamp, dados }]`. `HeatmapUtils` refatorado para buffer unico. Web Vitals (LCP/CLS/INP) via lib `web-vitals` entra como evento `web_vital` e e persistido em measurement separado no InfluxDB. `enviarEvento(nome, propriedades)` publicado no `sdk/index.ts` para eventos de negocio. Catalogo de eventos em `docs/eventos-analytics-catalogo.md`.
- Backend ganhou camada de ingestao em `backend/ingestao/`: `validador.py` rejeita payloads invalidos com lista de erros por caminho (ex.: `paginas./[0].eventos[2].tipo`) e `servico_ingestao.py` isola validacao, transformacao e persistencia do handler Socket.IO. Handler em `backend/app.py` passou a so delegar. Ack de erro estruturado (`{status, code, message, fields}`). Erros de InfluxDB nao derrubam a ingestao — sao logados e ignorados. Cobertura em `backend/test_validador_payload.py` e `backend/test_servico_ingestao.py`.
- Fila offline persistente em `frontend/src/sdk/filaAnalytics.ts`: interface `StorageFila` com implementacoes `StorageIndexedDB` (producao), `StorageLocalStorage` (fallback) e `StorageMemoria` (testes/SSR). `FilaAnalytics` gerencia FIFO com limite configuravel (`limiteFilaOffline`, default 500) descartando os mais antigos. `WebSocketService` passou a enfileirar sempre e drenar na conexao/tick periodico, confirmando item a item apos ack. Novos metodos publicos: `limparFilaOffline()` (LGPD — revogacao de consentimento) e `tamanhoFilaOffline()`. Cobertura em `frontend/src/testes/filaAnalytics.test.ts` + cenarios de drenagem/limite/reload em `WebSocketService.test.ts`. README do SDK atualizado com a mencao obrigatoria ao armazenamento local no banner de consentimento.
- Observabilidade e sanidade: `backend/test_sanidade.py` cobre os 3 estados do InfluxDB (saudavel, degradado, indisponivel), comportamento sem `influxdb_service` e resiliencia a erro de persistencia. Health separado por camada: `/health/app`, `/health/socketio`, `/health/influxdb` (alem do `/health` agregado original). Logs estruturados `evento=<estagio> session_id=... id_registro=... app_id=...` em cada estagio (recebido, validado, rejeitado, persistido_temporal, persistido_webvital, erro_persistencia) via `backend/ingestao/logs.py`.
- Fixtures de exemplo + CLI: `backend/fixtures/analytics_payload_invalido.json` cobre erros comuns; `backend/scripts/validar_fixture.py` roda o validador contra qualquer payload JSON e imprime caminhos de erro. Testado contra fixture valida (ok) e invalida (7 problemas).
- Empacotamento minificado do SDK: `npm run build:sdk` (com `frontend/vite.sdk.config.js` + `frontend/tsconfig.sdk.json`) gera `frontend/dist/sdk/index.js` (ESM, ~7 KB gzip), `index.cjs`, `index.d.ts` e source maps. Externals preservados (`react`, `react-dom`, `socket.io-client`, `uuid`, `web-vitals`). Smoke test em `frontend/scripts/smoke-sdk-bundle.mjs` valida o bundle.
- README operacional raiz (`README.md`) atualizado com comandos Docker/WSL (up, ps, logs, stop, down -v), health checks via curl, sequencia de testes backend/frontend, CLI de validacao e links para catalogo de eventos + README do SDK.

## Problemas ainda abertos

- A cobertura do frontend ainda deve avançar para hooks e componentes que integram analytics.
- O build minificado/distribuível do SDK ainda precisa ser definido a partir de `frontend/src/sdk/index.ts`.
- O usuário WSL `daniel` ainda não foi adicionado ao grupo `docker`; enquanto isso, comandos Docker no WSL podem exigir execução com `-u root`.
- As credenciais de acesso ao painel do InfluxDB local ainda precisam ser confirmadas ou documentadas para teste.
- **Evolucao do backend pos-SDK**: `docs/plano-atualizacao-analytics.md` foi concluido. Proximos passos especificos do servidor estao em `docs/plano-backend.md` (5 frentes: dividas imediatas, API de consulta, LGPD, observabilidade/deploy, multi-cliente). `docs/backend/INFLUXDB_SCHEMA.md` foi reescrito para refletir o schema atual (delta, `page_analytics` + `web_vitals`, measurements antigos marcados como depreciados).
- **Estrutura `/ark` criada**: Makefile (atalhos dev/test/monitoring/crowdsec/ansible), Nginx (vhost + ssl hardening), Ansible (playbook + roles base/docker/analytics-stack/nginx/monitoring/crowdsec + inventario exemplo + group_vars), CrowdSec (docker-compose + parser dos logs estruturados + cenarios de flood e admin abuse), monitoring stack (Prometheus + Grafana com datasource InfluxDB + dashboard overview). Documentacao em `ark/docs/servidor-producao.md`.
- **Plano comercial atualizado (`docs/plano-clientes-ambientes.md`)**: especificacao de PostgreSQL para tokens/sites/quotas, modelo de auth JWT com refresh rotativo, handshake Socket.IO autenticado, **garantias testaveis de isolamento** via rooms por `site_id`, RLS no Postgres, filtro compulsorio em queries REST, pool de conexoes com particionamento por site. Lista cinco testes de isolamento que precisam passar antes de liberar o modo comercial.
- **Frentes A/B/C/D do plano backend concluidas** (24 itens). Frente E (multi-cliente) segue bloqueada pela decisao em `docs/plano-clientes-ambientes.md`. Entregas:
  - A: queries com `sum()`, dead code removido, scripts de teste antigos deletados, `security.log` com rotacao, decisao documentada sobre volatilidade de `active_sessions`.
  - B: endpoints REST `/analytics/metricas`, `/analytics/web-vitals`, `/analytics/custom-events` + measurement dedicado `custom_events` + doc em `docs/backend/api-consulta.md`.
  - C: endpoints admin `/admin/analytics/sessao/<id>` (GET e DELETE) com auth via `ADMIN_API_TOKEN`, audit log em `security.log`, `backend/scripts/configurar_retencao.py`, `user_agent` virou field (alta cardinalidade resolvida).
  - D: logs `evento=...` em todo o ciclo (conectado/recebido/validado/persistido/desconectado/backpressure), `DEPLOY-GUIDE` ampliado com Gunicorn/Nginx/variaveis/backup/restore, sinal de backpressure via `fila_pendente()`. Follow-up: `/metrics` Prometheus e Dockerfile.prod real.
  - Testes: backend passou de 37 para **48 testes**, incluindo validacao de rate limits de parametros e auth admin. Frontend 80/80, lint limpo. Logs reais capturados via `test_ingestao_analytics_socketio`.

## Decisões registradas

- O projeto opera inicialmente apenas em ambiente local de desenvolvimento.
- O plano multi-cliente será implementado no futuro, mas toda evolução deve preservar separação de ambientes.
- A regra de autenticação, CORS, rate limit e isolamento será definida junto da estratégia de buckets no InfluxDB.
- A API de consulta para terceiros será definida depois; a tendência é usar Grafana com acesso de leitura aos buckets ou views do cliente.
- O SDK público de analytics deve ser precedido por levantamento do estado atual, contrato de inicialização, eventos aceitos e schema público.
- A fila offline do SDK deve usar cache local do navegador, pois o envio principal será por Socket.IO.
- A cobertura mínima deve incluir modelos geradores, funções de serviço e endpoints antes de evoluir novas funcionalidades.
- O plano de atualização da camada de analytics deve preservar a capacidade de uso open source local e evitar acoplamentos que dificultem uma futura comercialização.

## Documentos relacionados

- `docs/plano-clientes-ambientes.md`
- `docs/levantamento-sdk-analytics.md`
- `docs/plano-atualizacao-analytics.md`
- `docs/testes-analytics-sem-browser.md`
