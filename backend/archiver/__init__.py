"""Sidecar de archiver: exporta janelas pre-expiracao do InfluxDB pra R2.

Roda independente do backend principal (container `analytics-archiver`),
cron diario 03:00 UTC. Cada execucao itera sites pagos, identifica a janela
[now - retencao - 1d, now - retencao] e exporta como line protocol gzipado
pra `r2://<bucket>/<slug>/<YYYY>/<MM>/<DD>.lp.gz`.

Endpoint `/cliente/exportar` no backend principal gera signed URL R2 (TTL 5min)
pra cliente baixar arquivos arquivados.

Ver `ark/docs/dashboard-cliente.md` §21 (Backup pre-wipe) e
`docs/PROJETO.md` para contexto de retencao por tier.
"""
