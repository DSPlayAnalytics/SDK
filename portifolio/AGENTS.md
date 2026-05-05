# Repository Guidelines

## Arquitetura e Objetivo do Produto

Este repositório contém um portfólio full-stack com um backend Flask + Socket.IO em `backend/` e um frontend React + Vite em `frontend/`. O backend recebe eventos de analytics via WebSocket, valida os dados e persiste métricas temporais no InfluxDB 2.7. A direção futura é transformar esse backend em uma plataforma de analytics multi-cliente, onde clientes assinantes possam coletar e consultar dados de navegação de suas próprias páginas.

O frontend tem duas responsabilidades: renderizar a experiência atual do portfólio e evoluir a camada de analytics para um módulo reutilizável por terceiros. Novas rotinas de coleta devem ser abstraídas para permitir integração clara em outros sistemas, com funções explícitas para informar quais dados serão coletados e enviados ao backend.

## Estrutura do Projeto

- `backend/app.py`: API Flask, eventos Socket.IO, validações e recebimento de analytics.
- `backend/influxdb_service.py`: integração e escrita no InfluxDB.
- `backend/dto/`: objetos de transferência usados para analytics.
- `frontend/src/components/`, `pages/`, `hooks/`, `utils/`: UI, telas e utilitários de coleta/envio.
- `landing/`: **espelho manual** da landing comercial — repo canônico é `danpqdan/comercial` (CF Pages builda dele). Qualquer alteração aqui em `landing/` precisa ser replicada no `comercial` para chegar em produção no apex `dsplayground.com.br`. Não é submodule, não há sync automático. Ver `ark/docs/embed-iframe.md` → "Gotchas conhecidos da Fase 1" para histórico do problema.
- **SDK** (`@danpqdan/dsplayground-analytics-sdk`): repo separado público em `danpqdan/dsplayground-analytics-sdk`, consumido aqui via npm package. **Não há pasta `sdk/` aqui** — extraído em 2026-04-28. Para mexer no SDK, ir no repo dedicado e fazer release; consumidores (este repo + `comercial`) atualizam `package.json` + `npm install`. Detalhes operacionais no README do SDK.
- `ark/`: infraestrutura (Nginx, Ansible, CrowdSec, monitoring) — ver `ark/docs/servidor-producao.md` (canônico).
- `docs/`: documentação técnica, deploy, InfluxDB e histórico de correções.
- `continue/`: problemas encontrados, decisões em aberto e próximos passos documentados.

## Comandos de Desenvolvimento

Frontend, a partir de `frontend/`:

```bash
npm install
npm run dev
npm run test
npm run build
npm run preview
npm run lint
```

Backend, a partir de `backend/` com Python 3.11+:

```bash
pip install -r requirements.txt
python app.py
python test_service.py
python test_influxdb.py
python test_queries.py
python test_final.py
```

Ambiente local containerizado:

```bash
docker compose up --build
```

Quando estiver usando WSL no Windows, inicie os containers a partir da distro Ubuntu apontando para o projeto montado em `/mnt/d/portifolio`:

```bash
wsl -d Ubuntu -- bash -lc "cd /mnt/d/portifolio && docker compose up --build -d"
```

Se o usuário do WSL ainda não tiver permissão no socket do Docker (`permission denied while trying to connect to the docker API at unix:///var/run/docker.sock`), execute temporariamente como `root`:

```bash
wsl -d Ubuntu -u root -- bash -lc "cd /mnt/d/portifolio && docker compose up --build -d"
```

Para verificar o ambiente de teste:

```bash
wsl -d Ubuntu -u root -- bash -lc "cd /mnt/d/portifolio && docker compose ps"
curl -I http://localhost:3000
curl -I http://localhost:5000
curl -I http://localhost:8086/health
```

Os serviços esperados são `frontend` em `http://localhost:3000`, `backend` em `http://localhost:5000` e InfluxDB em `http://localhost:8086`.

## Padrões de Código

Use variáveis, funções, classes de domínio e nomes de arquivos novos em português pt-BR sempre que fizer sentido para o negócio. Preserve nomes técnicos exigidos por bibliotecas, APIs públicas ou padrões de framework. Use 4 espaços em Python e 2 espaços no frontend. Componentes React usam PascalCase; hooks usam `useNome`; módulos Python usam `snake_case`. Documentos devem ser gravados em UTF-8.

## Testes e Extreme Programming

Siga Extreme Programming com TDD: antes de criar funcionalidade, rotina, campo, objeto ou comportamento novo, escreva ou atualize testes unitários. Para backend, mantenha o padrão `test_*.py`. Para frontend, use Vitest + React Testing Library com testes em `frontend/src/testes/`. Nenhuma abstração de analytics deve avançar sem testes cobrindo modelos geradores, funções de serviço, endpoints, contrato de entrada, transformação e envio.

## Provisionamento e Testes de Infra

**Toda implementação que toca infra (roles Ansible, nginx, Grafana, Postgres schema, novos serviços do backend que exigem configuração no host) deve ser testada e executada via provisionamento em `ark/teste-ambiente-a` antes de ir para produção.**

Fluxo obrigatório:

1. Ajustar roles em `ark/ansible/roles/` e/ou templates em `ark/nginx/`, `ark/monitoring/`.
2. Rodar `ark/teste-ambiente-a` (ver `ark/teste-ambiente-a/README.md`):
   - `docker compose -f docker-compose.teste-a.yml up -d`
   - `ansible-playbook ... playbook-teste.yml --skip-tags firewall,tls`
   - Re-rodar para validar **idempotência** (`changed=0` na 2ª execução).
3. Só então mergear para `main` (que dispara o CD automático na VPS).

Migrações de schema Postgres e configurações de Grafana devem ter task Ansible idempotente (`creates:`, `CREATE IF NOT EXISTS`, `state: present`) — nunca aplicar manualmente direto no host.

## Documentação

Todo novo `.md` técnico deve ficar em `docs/`, exceto `README.md` e `AGENTS.md` na raiz. Atualize `README.md` quando comandos, instalação, variáveis de ambiente ou fluxo principal mudarem. Registre problemas e decisões pendentes em arquivos claros dentro de `continue/`. Antes de implementar o SDK público de analytics, atualize `docs/levantamento-sdk-analytics.md` com o estado atual e o contrato proposto.

## Commits e Pull Requests

Use mensagens curtas no estilo Conventional Commits em português, por exemplo `feat: abstrair coleta de analytics` ou `fix: corrigir envio temporal`. PRs devem explicar impacto em backend/frontend, listar testes executados, citar decisões em aberto e incluir screenshots quando houver mudança visual.

## Segurança e Configuração

Nunca versionar tokens reais, segredos, URLs privadas ou credenciais do InfluxDB. Use `.env.example` apenas com placeholders. Configurações sensíveis devem vir de variáveis de ambiente. O projeto opera inicialmente em desenvolvimento local, mas toda alteração deve manter separação de ambientes. O modelo multi-cliente, autenticação, CORS, rate limit e buckets será definido futuramente conforme `docs/plano-clientes-ambientes.md`.
