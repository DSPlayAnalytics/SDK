# /ark — infraestrutura e operacao

Tudo que e servidor, seguranca perimetral, monitoramento e automacao de provisionamento vive aqui. O objetivo e: um operador novo clona o repo, entra em `/ark`, le o que precisa e sobe producao com Ansible + Docker Compose sem depender de conhecimento tribal.

## Mapa

```
ark/
  Makefile                  atalhos para dev e operacao
  nginx/                    configs do proxy reverso (TLS, Socket.IO, rate limit)
  ansible/                  playbooks e roles para provisionar servidor zerado
  crowdsec/                 parsers/cenarios do CrowdSec + docker-compose
  monitoring/               Prometheus + Grafana (docker-compose + provisioning)
  docs/                     documentacao operacional
```

## Fluxo de uso tipico

Dev local do projeto: `make dev` na raiz do repo (equivalente a `docker compose up -d`).
Stack de monitoramento local: `make monitoring-up`.
CrowdSec em dev: `make crowdsec-up`.
Provisionamento de servidor novo: `cd ark/ansible && ansible-playbook -i inventory.ini playbook.yml`.

Cada pasta tem seu proprio `README.md` com detalhes especificos. Este aqui e so o indice.

## Principios

- **Configuracao declarativa**: playbooks Ansible, arquivos Docker Compose e YAML do CrowdSec ficam versionados. Nada de mudanca manual em servidor — se precisou mudar, ajusta aqui e re-executa.
- **Segredos nunca versionados**: `.env.example` em cada pasta mostra o shape; valores reais ficam em `.env` local (gitignored) ou no Ansible Vault.
- **Stack opcional**: monitoramento e CrowdSec sao opt-in. O backend roda sem eles; entram quando o ambiente exige observabilidade ou defesa ativa.
- **Paridade dev/prod**: os mesmos YAML/configs de `/ark` sao usados em dev local (via `make monitoring-up`) e em producao (via Ansible). Evita surpresas no deploy.

## Ordem recomendada de leitura

1. `ark/docs/servidor-producao.md` — arquitetura resumida e ordem de deploy.
2. `ark/nginx/README.md` — como o trafego entra.
3. `ark/crowdsec/README.md` — como bloqueios automatizados funcionam.
4. `ark/monitoring/README.md` — Prometheus + Grafana.
5. `ark/ansible/README.md` — automacao ponta-a-ponta.
