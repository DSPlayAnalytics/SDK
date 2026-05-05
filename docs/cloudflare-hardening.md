# Cloudflare hardening — checklist do operador

Esse doc lista as configuracoes do dashboard Cloudflare que devem
ser revisadas/aplicadas pra fechar o item P3 da auditoria. Tudo
e clicar-e-salvar no painel — sem mudanca de codigo aqui.

Acesso: https://dash.cloudflare.com → conta DS Playground →
zona `dsplayground.com.br`.

Marcar `[x]` quando aplicado e commitar este doc.

---

## SSL/TLS

- [ ] **SSL/TLS → Overview**: modo **Full (strict)** (ja aplicado, manter).
- [ ] **SSL/TLS → Edge Certificates**:
  - [ ] **Always Use HTTPS**: ON
  - [ ] **HTTP Strict Transport Security (HSTS)**: ON com:
    - max-age = 6 meses (15768000s)
    - Include subdomains: ON
    - Preload: OFF (so ligar quando todos subdominios estiverem 100% HTTPS por >6 meses)
    - No-sniff: ON
  - [ ] **Minimum TLS Version**: **1.3**
  - [ ] **Opportunistic Encryption**: ON
  - [ ] **TLS 1.3**: ON
  - [ ] **Automatic HTTPS Rewrites**: ON
  - [ ] **Certificate Transparency Monitoring**: ON
- [ ] **SSL/TLS → Origin Server**:
  - [ ] Confirmar Origin Cert wildcard `*.dsplayground.com.br` valido ate 2041 (ja emitido).
  - [ ] **Authenticated Origin Pulls**: avaliar ON (CF apresenta cert mTLS pro origin
    nginx; nginx valida que so CF chega). Implica adicionar
    `ssl_client_certificate /etc/ssl/cloudflare/cloudflare-ca.pem;`
    + `ssl_verify_client on;` nos vhosts. Rollout cuidadoso — se config quebrar,
    todo o trafego CF cai. Item adiado se nao houver janela.

## Firewall / WAF

- [ ] **Security → WAF → Managed rules**:
  - [ ] **Cloudflare Managed Ruleset**: ON (free tier inclui o set principal).
  - [ ] Verificar que `Action: Block` esta ativo pras categorias OWASP.
- [ ] **Security → WAF → Custom rules** (free tier permite 5 regras):
  - [ ] Bloquear paths comuns de scan: regex no field `URI Path` matches
    `/wp-admin|/wp-login|/.git|/.env|/phpmyadmin|/server-status` → Block.
  - [ ] (Opcional) Geo-block paises sem trafego legitimo (ex: nao-BR e nao-US se
    audiencia for so Brasil) → Challenge ou Block.
- [ ] **Security → Bots**:
  - [ ] **Bot Fight Mode**: ON (free tier; bloqueia bots auto-detectados).
  - [ ] **Super Bot Fight Mode**: avaliar paid (~$20/mes). Pega ataques mais sofisticados.
- [ ] **Security → DDoS**: HTTP DDoS attack protection — manter no padrao **High**.
- [ ] **Security → Settings**:
  - [ ] **Security Level**: Medium (default OK; High pode trolar usuarios legitimos).
  - [ ] **Challenge Passage**: 30 minutes
  - [ ] **Browser Integrity Check**: ON

## Rate limiting

- [ ] **Security → WAF → Rate limiting rules** (free tier permite 1 regra):
  - [ ] Endpoints sensiveis: `/cliente/auth/login` ou `/auth/sdk-token` →
    se mais de 50 req/min do mesmo IP, Challenge ou Block por 1h.
  - Justificativa: nginx ja tem rate limit (zone=cliente_auth 10r/s) mas
    CF protege antes do request chegar no origin.

## DNS

- [ ] **DNS → Records**: confirmar todos os subdominios usados em prod
  estao **proxiados (laranja)**:
  - [ ] dsplayground.com.br (apex → CF Pages — `comercial`)
  - [ ] api.dsplayground.com.br
  - [ ] portifolio.dsplayground.com.br
  - [ ] app.dsplayground.com.br
  - [ ] grafana.dsplayground.com.br
  - [ ] influx.dsplayground.com.br
  - Subdominios cinza (DNS only) quebram TLS porque CF Origin Cert so vale
    com proxy ativo.
- [ ] **DNS → Settings → DNSSEC**: ON (passo 2 — adicionar DS record no
  registrar do dominio).
- [ ] **DNS → Email Routing**: confirmar `contato@dsplayground.com.br` ainda
  redireciona pra inbox principal (usado em links da landing).

## Speed / Performance (security-adjacent)

- [ ] **Speed → Optimization → Network**: HTTP/3 (with QUIC) ON.
- [ ] **Speed → Optimization → Auto Minify**: HTML/CSS/JS — avaliar OFF se
  CSP causar problema (minify pode injetar comentarios que CSP rejeita).

## Caching

- [ ] **Caching → Configuration → Browser Cache TTL**: 4 hours (default
  razoavel; nao subir muito porque dificulta hotfix de assets).
- [ ] **Caching → Configuration → Always Online**: ON (cache do CF serve
  pagina cached se origin cair).

## Workers / Pages

- [ ] **Workers & Pages → projeto `comercial`**: confirmar deploy auto
  do branch main.
- [ ] **Workers & Pages → Settings → Functions/Logs**: avaliar habilitar
  log retention pra investigar incidentes na landing.

## Notifications

- [ ] **Notifications**: criar pelo menos 2 alertas pra email do operador:
  - [ ] **HTTP DDoS Attack Alerter**
  - [ ] **Origin Error Alerter** (5xx > X% em Y min)
  - [ ] (Opcional) Free SSL Certificate alerter (avisa sobre expiracao;
    embora origin seja 2041, certs CF→browser sao gerenciados por eles).

## Audit Logs

- [ ] **Manage Account → Audit Log**: revisar trimestralmente. Especialmente
  apos cada rotacao de credencial CF (R2, API tokens).

---

## Quando aplicar

Sessao dedicada de ~30min. Depois de cada item, validar:
- Origem ainda responde 200: `curl -I https://api.dsplayground.com.br/health/app`
- WAF nao bloqueando trafego legitimo: olhar **Security → Events** logo apos.
  Filtrar por Action=Blocked. Se aparecer trafego do proprio dominio
  bloqueado, ajustar regra.

Cada bloco deste doc e independente — pode-se ir aplicando aos poucos.

## Pos-aplicacao

Atualizar item P3 em `ark/docs/seguranca-auditoria-2026-05-02.md` de
🟡 pra ✅, com data + nivel de cobertura aplicado.
