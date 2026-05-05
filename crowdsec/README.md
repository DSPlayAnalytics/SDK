# CrowdSec

Agente de deteccao e bloqueio de abuso. Le `security.log` do backend e os logs de acesso do Nginx, aplica cenarios de detecao e comunica bans para os bouncers (Nginx, firewall).

## O que protege

- **Flood em `/analytics/*` e `/admin/*`** — cenario `analytics-flood` reage a picos de requisicoes por IP.
- **Token admin errado em `/admin/*`** — cenario `admin-auth-abuse` reage a sequencia de 401s.
- **Exploit scanning generico** — usa cenarios comunitarios via `crowdsec collections install crowdsecurity/http-cve`.

## Subir local

```bash
make crowdsec-up
```

O agente abre dashboard local em `http://localhost:6060` com `cscli metrics`. Bouncer e um container separado ligado ao Nginx (nao incluido por default; adicionar quando o Nginx subir no mesmo host).

## Producao

Role Ansible `crowdsec` (em `ark/ansible/roles/crowdsec/`) instala o agente no host, registra no Central API da CrowdSec (opcional — consentimento para compartilhar IPs maliciosos), e aplica os parsers/scenarios deste diretorio.

## Arquivos

- `docker-compose.crowdsec.yml` — agente em container montando os logs do host.
- `config/acquis.yaml` — fontes de log que o agente le.
- `parsers/backend-analytics.yaml` — parser para o formato `evento=... session_id=...` do backend.
- `scenarios/analytics-flood.yaml` — cenario de flood em endpoints de analytics.
- `scenarios/admin-auth-abuse.yaml` — cenario de auth errada no admin.

## Integracao com o backend

Os logs estruturados `evento=...` facilitam o parser — ele extrai `session_id`, `ip`, `evento` e gera decisoes baseadas em taxa ou padrao. Sem structured logging seria muito mais fragil.
