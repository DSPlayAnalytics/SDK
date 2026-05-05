# Documentação

Estado canônico do projeto: **[`PROJETO.md`](./PROJETO.md)**.

`PROJETO.md` consolida tudo que estava nos 16 arquivos anteriores desta pasta
(estado em 2026-04-29). Para detalhes profundos:

- **`CLAUDE.md`** (raiz) — comandos operacionais, regras pra agentes, estado da VPS
- **`AGENTS.md`** (raiz) — padrões de código + fluxo de PR
- **`ark/docs/dashboard-cliente.md`** — design do produto multi-tenant + recovery runbook
- **`ark/docs/servidor-producao.md`** — arquitetura VPS, TLS, hardening
- **`ark/docs/api-prefix-redundancia.md`** — histórico do refactor canonical sem `/api/`

## Manutenção

Ao alterar arquitetura, schema, contrato de eventos ou fluxo de deploy:

1. Atualize o **código** primeiro.
2. Atualize **`PROJETO.md`** com o novo estado/pendência.
3. Se afeta comandos operacionais, atualize **`CLAUDE.md`**.
4. Commit único com código + doc.
