# Portifolio Analytics

Aplicacao full-stack com frontend React + Vite e backend Flask + Socket.IO. O backend recebe eventos de analytics do frontend por WebSocket, transforma os dados em metricas temporais e grava no InfluxDB 2.7. A evolucao planejada e abstrair essa coleta para que terceiros consigam instalar um modulo de analytics em seus proprios sistemas e consultar dados de navegacao de forma clara.

## Estrutura

```text
backend/              API Flask, Socket.IO, DTOs e integracao InfluxDB
backend/dto/          Objetos de transferencia de analytics
frontend/             Aplicacao React + Vite
frontend/src/         Componentes, paginas, hooks, utils, estilos e assets
docs/                 Documentacao tecnica, deploy e historico de correcoes
continue/             Problemas encontrados e decisoes em aberto
AGENTS.md             Guia de contribuicao e regras para agentes
```

## Requisitos

- Python 3.11+
- Node.js 18+ e npm 9+
- InfluxDB 2.7 quando a persistencia temporal estiver habilitada

## Configuracao do Backend

1. Crie e ative um ambiente virtual.
2. Instale as dependencias.
3. Configure variaveis de ambiente a partir de `backend/.env.example`.

```bash
cd backend
python -m venv venv
# Windows: venv\Scripts\activate
# Linux/macOS: source venv/bin/activate
pip install -r requirements.txt
python app.py
```

Por padrao, o backend sobe em `http://localhost:5000`. Em producao, revise `FLASK_ENV`, `SECRET_KEY`, `CORS_ORIGINS`, `INFLUXDB_URL`, `INFLUXDB_TOKEN`, `INFLUXDB_ORG`, `INFLUXDB_BUCKET` e `INFLUXDB_ENABLED`.

## Configuracao do Frontend

```bash
cd frontend
npm install
npm run dev
```

O frontend de desenvolvimento roda via Vite em `http://localhost:3000`. Configure `frontend/.env.development` com:

```env
VITE_API_URL=http://localhost:5000
VITE_WEBSOCKET_URL=http://localhost:5000
VITE_DEBUG=true
```

## Build e Preview

```bash
cd frontend
npm run build
npm run preview
```

O build de producao e gerado em `frontend/dist/`. Para deploy com Nginx e Gunicorn/Eventlet, consulte `docs/backend/DEPLOY-GUIDE.md` e os documentos em `docs/`.

## Execucao Local com Docker

Frontend, backend e InfluxDB 2.7 sobem em containers Linux via Docker Compose:

```bash
docker compose up --build -d        # sobe todos os servicos em background
docker compose ps                    # confere estado e portas
docker compose logs backend --tail=50
docker compose stop                  # para sem remover containers
docker compose down                  # para e remove containers e rede
docker compose down -v               # inclui limpeza de volumes (reset total)
```

No Windows com WSL Ubuntu, rode os comandos a partir de `/mnt/d/portifolio` dentro da distro:

```bash
wsl -d Ubuntu -- bash -lc "cd /mnt/d/portifolio && docker compose up -d"
```

Caso o usuario nao esteja no grupo `docker`, use `-u root` no WSL.

Health checks:

```bash
curl http://localhost:5000/health/app
curl http://localhost:5000/health/socketio
curl http://localhost:5000/health/influxdb
```

Servicos locais: frontend `http://localhost:3000`, backend `http://localhost:5000`, InfluxDB `http://localhost:8086`. O Compose usa bucket `portifolio_dev`, org `zen` e token `dev-local-influxdb-token` — apenas para desenvolvimento local.

## Testes e Qualidade

Backend (dentro do container):

```bash
docker compose exec -T backend python -m unittest discover -s . -p 'test_*.py'
```

Cobertura atual: validador de payload, servico de ingestao, contrato Socket.IO, dados dinamicos, sanidade, API de consulta e admin LGPD.

Frontend (dentro do container):

```bash
docker compose exec -T frontend sh -c 'cd /app && npm run test && npm run lint'
```

CLI de validacao de payload contra uma fixture:

```bash
docker compose exec -T backend python scripts/validar_fixture.py fixtures/analytics_payload_sintetico.json
docker compose exec -T backend python scripts/validar_fixture.py fixtures/analytics_payload_invalido.json
```

O frontend usa Vitest + React Testing Library. Antes de novas funcionalidades de analytics, escreva testes para componentes, hooks, objetos e funcoes de coleta/envio, seguindo o guia em `AGENTS.md`.

## Documentacao

- Documentos tecnicos ficam em `docs/`.
- Problemas e decisoes pendentes ficam em `continue/`.
- O plano de clientes e ambientes (DB relacional, tokens, pool isolado de WebSocket) fica em `docs/plano-clientes-ambientes.md`.
- O levantamento atual do SDK de analytics fica em `docs/levantamento-sdk-analytics.md`.
- Guia de uso do SDK (consumidor) fica em `frontend/src/sdk/README.md`. Exemplo em JS puro em `frontend/src/sdk/examples/vanilla.js`.
- Catalogo de eventos coletados fica em `docs/eventos-analytics-catalogo.md`.
- Infraestrutura, Nginx, Ansible, CrowdSec, Prometheus+Grafana e documentacao de servidor ficam em `ark/`.

## Operacao

Atalhos de operacao via `make` (Makefile em `ark/Makefile`):

```bash
make -f ark/Makefile help             # lista alvos
make -f ark/Makefile dev              # docker compose up -d
make -f ark/Makefile test             # backend + frontend
make -f ark/Makefile monitoring-up    # Prometheus + Grafana (ark/monitoring/)
make -f ark/Makefile crowdsec-up      # CrowdSec agent
make -f ark/Makefile ansible-apply    # provisiona servidor via playbook
```
- Atualize este `README.md` quando comandos, instalacao, variaveis ou fluxo de execucao mudarem.

## Direcao de Arquitetura

A camada de analytics deve evoluir para um modulo reutilizavel por clientes terceiros. Novas funcoes devem deixar claro quais dados serao coletados, como serao normalizados e quando serao enviados ao backend. O projeto opera inicialmente apenas em ambiente local, mas o backend deve caminhar para isolamento multi-cliente, autenticacao por cliente, rate limit por assinatura, separacao por buckets ou tags no InfluxDB e consultas analiticas por periodo, pagina, sessao e evento.

