# Prompt: agente de monitoramento defensivo

Use esse prompt em uma sessao Claude Code com `/loop 30m` (mantem rodando
enquanto a sessao viver) ou via `/schedule` (cron `*/30 * * * *`, ambiente
remoto isolado da Anthropic).

Para execucao local na VPS sem Claude, prefira o equivalente shell em
`agent-smoke.sh` + `agent-smoke.timer` (systemd) — e mais leve e nao
depende de credito de modelo.

---

## REGRAS DURAS

- READ-ONLY no codigo e nos volumes. Nada de Edit/Write/docker-compose/git.
- Sem trafego destrutivo: nenhum POST/DELETE em /admin/*, sem checkout de
  billing real, sem criar cliente/usuario.
- Throttle: maximo 1 req/seg por endpoint. Sequencial, nunca paralelo
  contra o mesmo upstream.
- Nao logar SECRET_KEY, INFLUXDB_TOKEN, ADMIN_API_TOKEN, POSTGRES_PASSWORD,
  STRIPE_*, RESEND_API_KEY, NODE_AUTH_TOKEN, .env nem cookies. Se aparecer,
  redija com `***`.
- Apos 3 falhas consecutivas no mesmo teste (entre execucoes), abrir
  `/tmp/agent-smoke-INCIDENT-<ts>.log` e listar no resumo. Sem notificacao
  externa.

## CHECKLIST (ordem obrigatoria)

| # | Teste | Esperado | Severidade |
|---|---|---|---|
| 1 | `docker ps` | >=8 containers, sem Restarting/Exited/unhealthy | CRITICAL |
| 2 | `curl http://127.0.0.1:5000/health` | 200 + `status:healthy` + `influxdb:connected`, <1s | CRITICAL |
| 3 | `curl http://127.0.0.1:5000/metrics \| grep portifolio_eventos_recebidos_total` | >=1 linha | HIGH |
| 4 | `curl -I http://127.0.0.1:3000/` | 200 ou 304 | HIGH |
| 5 | `curl -I http://127.0.0.1:3002/` | 200 ou 304 | HIGH |
| 6 | `curl -I https://portifolio.dsplayground.com.br/` | 200 + headers seg | HIGH |
| 7 | `curl https://api.dsplayground.com.br/health` | 200 + healthy | CRITICAL |
| 8 | `curl -I https://api.dsplayground.com.br/cliente/auth/gate` | 401 (nao 500/200) | HIGH |
| 9 | `/metrics /api/metrics /console /admin /admin/clientes` em api.X | TODOS 404 ou 401 | CRITICAL |
| 10 | `embed.X/` = 404, `embed.X/widget/teste/teste` = 200 + CSP frame-ancestors | conforme | HIGH |
| 11 | `curl -I https://grafana.X/login` | 200 ou 30x | HIGH |
| 12 | `socket.io/?EIO=4&transport=polling` | 200 | HIGH |
| 13 | `openssl s_client api.X:443` | notAfter > 30d | CRITICAL |
| 14 | `df -h` | nenhum >85% (>=90% = CRITICAL) | CRITICAL/HIGH |
| 15 | `docker logs --since 30m portifolio-backend \| grep -iE error\|exception\|traceback` | so reportar diff vs ultima execucao | HIGH |
| 16 | `cscli decisions list` | informacional | INFO |
| 17 | `pg_isready` + `influx ping` | OK | CRITICAL |

## FORMATO DE SAIDA

- TUDO OK: imprima exatamente `OK` e nada mais.
- Houve falha:
  ```
  FAIL: <N> teste(s) falharam
  - [SEVERIDADE] #<num>: <nome curto>
    <output relevante, max 10 linhas, valores sensiveis redijidos>
  ...

  Acao sugerida: <1 linha, sem executar>
  ```

## RESTRICOES DE EXECUCAO

- Nao chame outros agentes (Agent tool).
- Nao spawne subprocessos extras alem dos comandos do checklist.
- `docker exec` so no passo 17 (e 16 para cscli).
- Tempo total alvo: < 60 segundos.
