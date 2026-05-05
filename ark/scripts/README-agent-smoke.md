# agent-smoke — monitor defensivo dos servicos

Roda 17 checks read-only contra a stack de producao e alerta apenas quando
algo regride. Tres formas de uso, em ordem de simplicidade:

## 1. systemd timer (recomendado pra producao)

> Nota: a sandbox que gerou esses arquivos so liberou a criacao do `.service`.
> O `.timer` precisa ser criado manualmente — colei o conteudo abaixo como
> heredoc para um `cat > arquivo`.

Criar o timer:

```bash
sudo tee /etc/systemd/system/agent-smoke.timer > /dev/null <<'UNIT'
[Unit]
Description=Roda agent-smoke a cada 30min
Documentation=file:/opt/portifolio/ark/scripts/agent-smoke-prompt.md

[Timer]
# Primeira execucao 2min apos boot (dar tempo dos containers subirem).
OnBootSec=2min
# Depois disso, a cada 30 minutos.
OnUnitActiveSec=30min
# Persistente: se a maquina ficou desligada e perdeu janelas, recupera 1 vez.
Persistent=true
Unit=agent-smoke.service

[Install]
WantedBy=timers.target
UNIT
```

Instalar service + ativar:

```bash
sudo cp /opt/portifolio/ark/systemd/agent-smoke.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now agent-smoke.timer
```

Verificar:

```bash
systemctl list-timers agent-smoke.timer
journalctl -u agent-smoke.service --since '1 hour ago'
```

A primeira execucao acontece 2min apos o enable (e depois a cada 30min).
O service grava streak de falhas em `/var/lib/agent-smoke/` e abre arquivos
de incidente em `/tmp/agent-smoke-INCIDENT-*.log` quando o mesmo teste
falha 3x consecutivas.

Para alertar no Telegram/Slack/email, plugar no `OnFailure=` do service ou
fazer um wrapper que `tail` o journal e roteie:

```bash
journalctl -fu agent-smoke.service | grep -E '^FAIL'
```

## 2. Shell direto (debug / one-shot)

```bash
/opt/portifolio/ark/scripts/agent-smoke.sh
echo "exit=$?"
```

Sai 0 e imprime `OK` quando tudo passa. Sai 1 e imprime relatorio markdown
quando algo regride.

## 3. Prompt para sessao Claude Code

`agent-smoke-prompt.md` contem o mesmo checklist em formato de prompt para
agente. Use com `/loop 30m <prompt>` (sessao aberta) ou via `/schedule`
(agente remoto Anthropic). Mais caro que o systemd timer; recomendado
apenas se voce quer correlacao inteligente alem do checklist mecanico.

## O que e checado

| # | Categoria | Severidade |
|---|---|---|
| 1, 2, 7, 9, 13, 14, 17 | Containers, health, edge, endpoints sensiveis, TLS, disco, dbs | CRITICAL |
| 3-6, 8, 10-12, 15 | Metrics, frontends, auth gate, embed, grafana, socketio, logs | HIGH |
| 16 | CrowdSec decisions | INFO |

Detalhe completo em `agent-smoke-prompt.md`.

## Custos / impacto

- ~17 requests por execucao, 1/segundo, total ~30s.
- 14 hits no Cloudflare (cacheaveis, custo zero).
- 3 hits internos no backend (`/health`, `/metrics`).
- 2 `docker exec` (postgres, influxdb) + 1 `docker logs`.

A 30min de intervalo: ~816 execucoes/mes, ~13.872 requests/mes. Dentro
de qualquer cota.

## Relacionado

- `prod-regression.yml` no GitHub Actions roda 3x/dia checks similares
  via Internet — complementar, nao substitui.
- `smoke-test-arquitetura.sh` (mesmo diretorio) testa **arquitetura**
  pos-deploy (presenca de arquivos, configs, certs). Roda manualmente.
